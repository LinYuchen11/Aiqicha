"""RAG 评估中心接口：真实运行实验、读取指标、录入人工评估。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.database import eval_repo
from backend.models.schemas import EvalRunRequest, HumanEvalRequest
from backend.services import evaluation_service

router = APIRouter(prefix="/api/evaluation", tags=["评估中心"])


@router.get("/overview")
def overview() -> dict:
    return evaluation_service.overview()


@router.get("/questions")
def questions() -> dict:
    return {
        "问题集": evaluation_service.load_questions(),
        "统计": evaluation_service.question_stats(),
    }


@router.get("/runs")
def runs(limit: int = 50) -> dict:
    return {"实验记录": eval_repo.list_runs(limit)}


@router.get("/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    run = eval_repo.get_run(run_id)
    return {"实验": run, "逐题明细": evaluation_service.run_items(run_id)}


@router.post("/run")
def run_experiment(req: EvalRunRequest) -> dict:
    return evaluation_service.run_experiment(req.experiment, req.params)


@router.get("/human")
def human_evals(run_id: str | None = None) -> dict:
    return {
        "记录": evaluation_service.human_evals(run_id),
        "汇总": eval_repo.human_eval_summary(),
    }


@router.post("/human")
def save_human(req: HumanEvalRequest) -> dict:
    return evaluation_service.save_human_eval(req)
