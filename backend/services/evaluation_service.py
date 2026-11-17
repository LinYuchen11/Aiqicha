"""RAG 评估服务：真实执行实验并计算指标，不生成任何虚构数据。

标准答案：使用测试问题集中人工审核的「相关块标识」（文档::章节）作为显式
相关文本范围，按文档配对，分母固定，保证不同分块方案之间可比。
自动指标：Recall@K、MRR、命中率、平均响应时间、无答案正确率、
          答案-上下文一致性（词面支撑率）。
人工评估（答案正确性、来源引用准确性）只提供录入接口，默认「待人工评估」。
工具调用类问题由集成测试覆盖，不参与检索指标计算。
"""
from __future__ import annotations

import json
import time
from typing import Any

from backend.core.config import settings
from backend.core.errors import FileError, ParamError
from backend.core.log_utils import get_logger
from backend.database import eval_repo
from backend.models.schemas import HumanEvalRequest
from backend.rag.cleaner import normalize_query, tokenize_for_search
from backend.rag.embeddings import embedding_info, reset_embedder
from backend.rag.rerank import cross_encoder_status
from backend.rag.retriever import search
from backend.rag.vectorstore import get_vector_store
from backend.services.document_service import DEFAULT_COLLECTION, build_experiment_collection

logger = get_logger(__name__)

# 保留原有四组实验，新增第五组 Embedding 对照
EXPERIMENT_LABELS = {
    "chunking": "实验一：文本分块策略",
    "topk": "实验二：Top-K 检索数量",
    "retrieval": "实验三：检索方式对比",
    "rerank": "实验四：重排序优化（原始 / 规则 / CrossEncoder）",
    "embedding": "实验五：Embedding 模型对照（hash vs BGE）",
}

METRIC_NOTES = {
    "Recall@K": "每题 = 命中的「人工审核相关文本范围」数 ÷ 该题标注范围总数；分母固定，不随分块方案变化，因此跨方案可比。按文档配对匹配，不使用全局关键词 OR。",
    "MRR": "每题 = 第一个命中相关范围的结果排名的倒数；未命中记 0；对全部有答案题取平均。",
    "命中率": "至少命中一个相关文本范围的题目数 ÷ 有答案题数。",
    "平均响应时间ms": "检索阶段真实计时（perf_counter）的平均值，含向量计算与排序，不含大模型生成。",
    "无答案正确率": "无答案题中检索未返回任何结果的比例；低相关性判定由检索器的三判据决定（命中二元字组数 < 4 且最大覆盖率 < 0.30 且最高原始余弦 < 0.5），不使用归一化后的综合分。",
    "答案-上下文一致性": "以人工编写的标准答案为参照，计算其二元字组在 Top-K 检索上下文中的覆盖率，衡量检索资料能否支撑答案。这是词面支撑率代理指标，不是语义忠实度，也不调用大模型；抽取式答案天然偏高，仅用于同测试集的方案间对照。",
    "人工评估": "答案正确性与来源引用准确性需要人工判读，系统不自动生成分数，默认状态为「待人工评估」。",
    "工具调用题": "不参与检索指标，由集成测试（场景 D、G）验证真实工具执行。",
    "模型重排实验": "CrossEncoder 不可用时该方案不生成任何数值，报告中如实标注「未运行」，绝不把规则式降级结果写成模型结果。",
    "Embedding 对照实验": "两个方案使用完全相同的测试集与分块参数，分别用各自模型重建独立向量集合；BGE 未安装或加载失败时只记录 hash 方案与未运行说明。",
}

_SKIP_NOTES: list[str] = []


def load_questions() -> list[dict]:
    path = settings.eval_dir / "test_questions.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("问题集") or [])
    except (ValueError, OSError) as exc:
        raise FileError("测试问题集读取失败", str(exc)) from exc


def question_stats() -> dict:
    questions = load_questions()
    by_type: dict[str, int] = {}
    by_eval: dict[str, int] = {}
    for item in questions:
        by_type[item.get("类型", "未分类")] = by_type.get(item.get("类型", "未分类"), 0) + 1
        by_eval[item.get("评估类型", "未分类")] = by_eval.get(item.get("评估类型", "未分类"), 0) + 1
    return {
        "总题数": len(questions),
        "按类型": by_type,
        "按评估类型": by_eval,
        "文件路径": str(settings.eval_dir / "test_questions.json"),
    }


def _evidence_specs(question: dict) -> list[dict]:
    """标准答案：优先使用显式标注「相关块标识」（文档::章节）。

    旧实现把「相关文档 + 相关章节关键词」做全局 OR 匹配，跨文档题的相关集被
    放大，且分母随分块方案变化导致 Recall 不可比。这里按文档配对、分母固定。
    """
    specs: list[dict] = []
    for raw in question.get("相关块标识") or []:
        doc, _, section = str(raw).partition("::")
        specs.append({"文档": doc.strip(), "章节": section.strip(), "标识": str(raw)})
    if specs:
        return specs
    # 兼容未提供「相关块标识」的旧数据：按索引把文档与章节配对
    docs = list(question.get("相关文档") or [])
    sections = list(question.get("相关章节") or [])
    for index, doc in enumerate(docs):
        section = sections[index] if index < len(sections) else ""
        specs.append({"文档": doc, "章节": section, "标识": f"{doc}::{section}"})
    return specs


def _hit_matches_evidence(hit, spec: dict) -> bool:
    if hit.doc_name != spec["文档"]:
        return False
    key = spec["章节"]
    if key and key not in (hit.section or ""):
        return False
    return True


def _context_support(standard_answer: str, hits: list) -> float | None:
    """答案-上下文一致性（词面支撑率）：确定性代理指标，不调用大模型。"""
    answer_tokens = {
        token for token in tokenize_for_search(normalize_query(standard_answer or ""))
        if len(token) >= 2
    }
    if not answer_tokens:
        return None
    context_tokens: set[str] = set()
    for hit in hits:
        context_tokens.update(
            token for token in tokenize_for_search(hit.text) if len(token) >= 2
        )
    return round(
        sum(1 for token in answer_tokens if token in context_tokens) / len(answer_tokens), 6
    )


def _evaluate_question(question: dict, scheme: dict) -> dict | None:
    if question.get("评估类型") == "工具调用":
        return None
    query = question.get("检索问题") or question.get("问题") or ""
    outcome = search(
        query=query,
        collection=scheme["collection"],
        top_k=scheme["top_k"],
        mode=scheme["mode"],
        hybrid_weight=scheme["weight"],
        rerank=scheme["rerank"],
        rerank_mode=scheme.get("rerank_mode"),
    )
    retrieved = [
        {
            "chunk_id": hit.chunk_id, "rank": hit.rank, "score": hit.score,
            "doc_name": hit.doc_name, "section": hit.section,
            "original_rank": hit.original_rank, "rerank_score": hit.rerank_score,
        }
        for hit in outcome.hits
    ]
    specs = _evidence_specs(question)
    base = {
        "question_id": question["id"],
        "retrieved": retrieved,
        "elapsed_ms": outcome.elapsed_ms,
        "context_support": _context_support(question.get("标准答案") or "", outcome.hits),
        "hit": 0,
        "recall_at_k": 0.0,
        "reciprocal_rank": 0.0,
    }
    if not specs:
        # 无答案题：低相关性判定由 retriever 的三判据完成，这里只看是否返回空结果
        return {**base, "类别": "无答案", "无答案正确": not outcome.hits}

    matched: set[int] = set()
    first_rank: int | None = None
    for hit in outcome.hits:
        for index, spec in enumerate(specs):
            if index in matched:
                continue
            if _hit_matches_evidence(hit, spec):
                matched.add(index)
                if first_rank is None or hit.rank < first_rank:
                    first_rank = hit.rank
    return {
        **base,
        "类别": "有答案",
        "无答案正确": None,
        "hit": 1 if matched else 0,
        "recall_at_k": round(len(matched) / len(specs), 6),
        "reciprocal_rank": round(1 / first_rank, 6) if first_rank else 0.0,
    }


def _aggregate(items: list[dict]) -> dict:
    answered = [item for item in items if item["类别"] == "有答案"]
    no_answer = [item for item in items if item["类别"] == "无答案"]

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    return {
        "Recall@K": mean([item["recall_at_k"] for item in answered]),
        "MRR": mean([item["reciprocal_rank"] for item in answered]),
        "命中题数": sum(item["hit"] for item in answered),
        "有答案题数": len(answered),
        "命中率": round(sum(item["hit"] for item in answered) / len(answered), 4) if answered else None,
        "平均响应时间ms": mean([item["elapsed_ms"] for item in answered + no_answer]),
        "答案-上下文一致性": mean([
            item["context_support"] for item in answered
            if item.get("context_support") is not None
        ]),
        "无答案题数": len(no_answer),
        "无答案正确率": (
            round(sum(1 for item in no_answer if item["无答案正确"]) / len(no_answer), 4)
            if no_answer else None
        ),
    }


def _build_schemes(experiment: str, params: dict) -> list[dict]:
    global _SKIP_NOTES
    _SKIP_NOTES = []
    weight = float(params.get("hybrid_weight", settings.hybrid_weight))
    if experiment == "chunking":
        base = params.get("组合") or [
            {"名称": "固定长度 200/40", "块大小": 200, "重叠": 40, "策略": "fixed"},
            {"名称": "句末优先 200/40", "块大小": 200, "重叠": 40, "策略": "semantic"},
            {"名称": "句末优先 400/80", "块大小": 400, "重叠": 80, "策略": "semantic"},
            {"名称": "句末优先 600/120", "块大小": 600, "重叠": 120, "策略": "semantic"},
        ]
        schemes = []
        for index, combo in enumerate(base):
            collection = f"eval_chunking_{index}"
            build_experiment_collection(
                collection, int(combo["块大小"]), int(combo["重叠"]), str(combo["策略"])
            )
            schemes.append({
                "name": str(combo["名称"]), "collection": collection,
                "top_k": 5, "mode": "hybrid", "weight": weight,
                "rerank": False, "params": combo,
            })
        return schemes
    if experiment == "topk":
        return [
            {"name": f"Top-{k}", "collection": DEFAULT_COLLECTION, "top_k": k,
             "mode": "hybrid", "weight": weight, "rerank": False, "params": {"Top-K": k}}
            for k in (3, 5, 10)
        ]
    if experiment == "retrieval":
        return [
            {"name": label, "collection": DEFAULT_COLLECTION, "top_k": 5,
             "mode": mode, "weight": weight, "rerank": False, "params": {"检索方式": label}}
            for label, mode in (("纯向量检索", "vector"), ("关键词检索", "keyword"), ("混合检索", "hybrid"))
        ]
    if experiment == "rerank":
        schemes = [
            {"name": "原始检索排序", "collection": DEFAULT_COLLECTION, "top_k": 5,
             "mode": "hybrid", "weight": weight, "rerank": False, "params": {"重排序": "不启用"}},
            {"name": "规则式重排序", "collection": DEFAULT_COLLECTION, "top_k": 5,
             "mode": "hybrid", "weight": weight, "rerank": True, "rerank_mode": "rule",
             "params": {"重排序": "规则式（非模型），对照组"}},
        ]
        status = cross_encoder_status()
        if status["可用"]:
            schemes.append({
                "name": "CrossEncoder 模型重排序", "collection": DEFAULT_COLLECTION, "top_k": 5,
                "mode": "hybrid", "weight": weight, "rerank": True, "rerank_mode": "local",
                "params": {"重排序": f"CrossEncoder 模型（{status['模型']}）"},
            })
        else:
            _SKIP_NOTES.append(f"CrossEncoder 模型重排序未运行：{status['原因']}")
        return schemes
    raise ParamError("未知的实验类型", f"不支持：{experiment}")


def run_embedding_comparison(params: dict[str, Any] | None = None) -> dict:
    """实验五：hash 与 BGE 用同一测试集、同一分块参数，各自重建独立向量集合。

    BGE 不可用时不生成该方案的任何数值，只写入未运行说明，绝不伪造模型结果。
    """
    params = params or {}
    questions = load_questions()
    if not questions:
        raise FileError("测试问题集为空", "请先准备 data/evaluation/test_questions.json")
    started = time.perf_counter()
    original_mode = settings.embedding_mode
    run_id = eval_repo.create_run("embedding", params, embedding_info()["实际档位"])
    rows: list[dict] = []
    notes: list[str] = []
    try:
        for mode, label in (
            ("hash", "词面哈希向量（离线备用）"),
            ("local", "本地 BGE 语义向量（正式演示推荐）"),
        ):
            object.__setattr__(settings, "embedding_mode", mode)
            reset_embedder()
            info = embedding_info()
            if mode == "local" and not info["是否语义向量"]:
                notes.append(
                    f"BGE 方案未运行，未生成任何指标：{info['降级原因']}。"
                    "可安装可选依赖并确认模型可下载后重跑本实验。"
                )
                continue
            collection = f"eval_embedding_{mode}"
            build_experiment_collection(collection, 400, 80, "semantic")
            scheme = {
                "collection": collection, "top_k": 5, "mode": "hybrid",
                "weight": float(params.get("hybrid_weight", settings.hybrid_weight)),
                "rerank": False,
            }
            items = [
                item for q in questions
                if (item := _evaluate_question(q, scheme)) is not None
            ]
            eval_repo.add_items(run_id, label, items)
            rows.append({
                "方案": label, **_aggregate(items),
                "参数": {
                    "档位": info["实际档位"], "模型": info["模型名称"],
                    "维度": info["向量维度"], "分块": "400/80 semantic", "Top-K": 5,
                },
                "每题明细": [
                    {
                        "题号": item["question_id"], "类别": item["类别"],
                        "Recall@K": item["recall_at_k"], "倒数排名": item["reciprocal_rank"],
                        "命中": bool(item["hit"]), "耗时ms": item["elapsed_ms"],
                        "答案-上下文一致性": item.get("context_support"),
                        "召回块": item["retrieved"][:3],
                    }
                    for item in items
                ],
            })
        metrics = {
            "实验名称": EXPERIMENT_LABELS["embedding"],
            "方案": rows,
            "指标说明": METRIC_NOTES,
            "运行档位说明": "每个方案在各自 Embedding 档位下运行，向量集合独立且按模型指纹校验",
            "未运行方案说明": notes,
            "参与检索题数": sum(1 for q in questions if q.get("评估类型") != "工具调用"),
            "跳过工具调用题数": sum(1 for q in questions if q.get("评估类型") == "工具调用"),
            "总耗时秒": round(time.perf_counter() - started, 2),
            "人工评估状态": "待人工评估（系统不自动生成人工分数）",
        }
        eval_repo.finish_run(run_id, metrics, notes="；".join(notes) or "自动指标由真实检索运行产生")
        return eval_repo.get_run(run_id) or {"id": run_id}
    except Exception as exc:
        eval_repo.finish_run(run_id, {"错误": str(exc)}, status="失败", notes=str(exc))
        raise
    finally:
        object.__setattr__(settings, "embedding_mode", original_mode)
        reset_embedder()


def run_experiment(experiment: str, params: dict[str, Any] | None = None) -> dict:
    """真实执行一组实验：逐题检索 → 计算指标 → 落库 → 返回可复现结果。"""
    params = params or {}
    # 参数合法性优先于数据可用性，避免把参数错误误报成数据缺失
    if experiment not in EXPERIMENT_LABELS:
        raise ParamError("未知的实验类型", f"不支持：{experiment}")
    if experiment == "embedding":
        return run_embedding_comparison(params)
    questions = load_questions()
    if not questions:
        raise FileError("测试问题集为空", "请先准备 data/evaluation/test_questions.json")
    started = time.perf_counter()
    run_id = eval_repo.create_run(experiment, params, embedding_info()["实际档位"])
    rows: list[dict] = []
    try:
        for scheme in _build_schemes(experiment, params):
            items = [item for q in questions if (item := _evaluate_question(q, scheme)) is not None]
            eval_repo.add_items(run_id, scheme["name"], items)
            rows.append({
                "方案": scheme["name"],
                **_aggregate(items),
                "参数": scheme["params"],
                "每题明细": [
                    {
                        "题号": item["question_id"], "类别": item["类别"],
                        "Recall@K": item["recall_at_k"], "倒数排名": item["reciprocal_rank"],
                        "命中": bool(item["hit"]), "耗时ms": item["elapsed_ms"],
                        "答案-上下文一致性": item.get("context_support"),
                        "召回块": item["retrieved"][:3],
                    }
                    for item in items
                ],
            })
        metrics = {
            "实验名称": EXPERIMENT_LABELS[experiment],
            "方案": rows,
            "指标说明": METRIC_NOTES,
            "运行档位": embedding_info(),
            "向量库": get_vector_store().name,
            "跳过方案说明": list(_SKIP_NOTES),
            "参与检索题数": sum(1 for q in questions if q.get("评估类型") != "工具调用"),
            "跳过工具调用题数": sum(1 for q in questions if q.get("评估类型") == "工具调用"),
            "总耗时秒": round(time.perf_counter() - started, 2),
            "人工评估状态": "待人工评估（系统不自动生成人工分数）",
        }
        eval_repo.finish_run(run_id, metrics, notes="自动指标由真实检索运行产生")
    except Exception as exc:
        eval_repo.finish_run(run_id, {"错误": str(exc)}, status="失败", notes=str(exc))
        raise
    return eval_repo.get_run(run_id) or {"id": run_id}


def overview() -> dict:
    runs = eval_repo.list_runs()
    return {
        "问题集": load_questions(),
        "问题集统计": question_stats(),
        "实验记录": runs,
        "已完成实验数": sum(1 for run in runs if run["status"] == "已完成"),
        "人工评估": eval_repo.human_eval_summary(),
        "指标说明": METRIC_NOTES,
        "向量档位": embedding_info(),
        "实验类型": EXPERIMENT_LABELS,
    }


def run_items(run_id: str) -> list[dict]:
    return eval_repo.get_items(run_id)


def save_human_eval(req: HumanEvalRequest) -> dict:
    eval_id = eval_repo.add_human_eval(
        req.run_id, req.question_id, req.answer_correctness,
        req.citation_accuracy, req.note, req.evaluator,
    )
    return {"记录编号": eval_id, "提示": "人工评估记录已保存，与自动指标分开统计。"}


def human_evals(run_id: str | None = None) -> list[dict]:
    return eval_repo.list_human_evals(run_id)


def report_data() -> dict:
    """供报告生成脚本使用：只读取真实已完成的实验记录。"""
    runs = [run for run in eval_repo.list_runs(limit=100) if run["status"] == "已完成"]
    return {
        "实验记录": runs,
        "问题集统计": question_stats(),
        "人工评估": eval_repo.human_eval_summary(),
        "指标说明": METRIC_NOTES,
        "向量档位": embedding_info(),
    }
