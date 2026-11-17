"""SQLite 表结构定义与预置的模拟 IT 服务数据。

所有业务数据、会话、工单、工具日志、评估记录均持久化在本文件中定义的表中。
"""
from __future__ import annotations

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    file_type     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT '待处理',
    chunk_count   INTEGER NOT NULL DEFAULT 0,
    error_msg     TEXT,
    source_path   TEXT,
    is_sample     INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);

CREATE TABLE IF NOT EXISTS chunks (
    id           TEXT PRIMARY KEY,
    doc_id       TEXT NOT NULL,
    chunk_index  INTEGER NOT NULL,
    text         TEXT NOT NULL,
    section      TEXT,
    page         INTEGER,
    char_start   INTEGER,
    char_end     INTEGER,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS vectors (
    id           TEXT PRIMARY KEY,
    collection   TEXT NOT NULL,
    chunk_id     TEXT NOT NULL,
    doc_id       TEXT NOT NULL,
    text         TEXT NOT NULL,
    doc_name     TEXT NOT NULL,
    section      TEXT,
    page         INTEGER,
    embedding    TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vectors_collection ON vectors(collection);
CREATE INDEX IF NOT EXISTS idx_vectors_chunk ON vectors(chunk_id);

-- 每个向量集合记录「由哪个 Embedding 模型生成」，禁止不同模型的向量混用
CREATE TABLE IF NOT EXISTS embedding_meta (
    collection      TEXT PRIMARY KEY,
    model_key       TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    dim             INTEGER NOT NULL,
    effective_mode  TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    session_id      TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    pending_ticket  TEXT,
    pending_intent  TEXT
);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    intent        TEXT,
    sources       TEXT,
    trace         TEXT,
    tool_results  TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES conversations(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS tool_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT,
    tool_name    TEXT NOT NULL,
    args_json    TEXT NOT NULL,
    result_json  TEXT,
    status       TEXT NOT NULL,
    error_msg    TEXT,
    elapsed_ms   REAL NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_logs_time ON tool_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS tickets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_no       TEXT NOT NULL UNIQUE,
    fault_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    contact         TEXT,
    department      TEXT,
    urgency         TEXT NOT NULL DEFAULT '普通',
    status          TEXT NOT NULL DEFAULT '待受理',
    handling_note   TEXT NOT NULL DEFAULT '',
    session_id      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_no ON tickets(ticket_no);

CREATE TABLE IF NOT EXISTS it_services (
    service_key   TEXT PRIMARY KEY,
    category      TEXT NOT NULL,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    supported     INTEGER NOT NULL DEFAULT 1,
    apply_channel TEXT NOT NULL,
    sla           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id              TEXT PRIMARY KEY,
    experiment      TEXT NOT NULL,
    params          TEXT NOT NULL,
    metrics         TEXT,
    status          TEXT NOT NULL DEFAULT '运行中',
    embedding_mode  TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_time ON eval_runs(started_at DESC);

CREATE TABLE IF NOT EXISTS eval_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL,
    scheme           TEXT NOT NULL DEFAULT '默认',
    question_id      TEXT NOT NULL,
    retrieved        TEXT NOT NULL,
    context_support  REAL,
    recall_at_k      REAL NOT NULL,
    reciprocal_rank  REAL NOT NULL,
    hit              INTEGER NOT NULL,
    elapsed_ms       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_items_run ON eval_items(run_id);

CREATE TABLE IF NOT EXISTS human_evals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             TEXT,
    question_id        TEXT NOT NULL,
    answer_correctness REAL,
    citation_accuracy  REAL,
    note               TEXT,
    evaluator          TEXT,
    created_at         TEXT NOT NULL
);
"""

# 模拟企业 IT 服务目录（明确为模拟数据，非真实企业信息）
SEED_IT_SERVICES = [
    ("software_install", "软件安装", "常用办公软件安装", "Office、企业微信、浏览器等标准软件由 IT 服务台统一推送安装，员工无需单独申请。", 1, "IT 服务台工单", "1 个工作日"),
    ("design_software", "软件安装", "设计类专业软件", "Photoshop、AutoCAD、Figma 等设计软件需部门负责人审批后由 IT 安装，许可证数量有限。", 1, "部门审批 + IT 服务台工单", "3 个工作日"),
    ("admin_permission", "账号权限", "本地管理员权限", "默认不开放本地管理员权限；确有需要的，需提交用途说明并经部门负责人与信息安全双审批。", 0, "权限申请流程（双审批）", "3 个工作日"),
    ("vpn_account", "账号权限", "VPN 与远程办公账号", "入职后自动开通基础 VPN；远程长期办公需额外申请，账号有效期与在职状态绑定。", 1, "账号权限申请流程", "1 个工作日"),
    ("email_reset", "账号权限", "企业邮箱密码重置", "可通过自助重置链接或携带工牌到 IT 服务台办理，重置后需首次登录修改密码。", 1, "自助服务 / IT 服务台", "即时"),
    ("network_wifi", "网络故障", "办公无线网络接入", "公司无线网络需使用域账号认证；无法连接时先检查证书与账号状态，再排查网卡驱动。", 1, "IT 服务台工单", "4 小时"),
    ("printer", "办公设备", "打印机与扫描仪", "公共打印区设备由行政统一维护，卡纸、驱动异常可提交 IT 服务台工单。", 1, "IT 服务台工单", "1 个工作日"),
    ("meeting_room", "行政事务", "会议室预约系统", "会议室通过行政预约系统预订，账号问题由 IT 服务台处理，场地问题由行政处理。", 1, "行政预约系统", "即时"),
]
