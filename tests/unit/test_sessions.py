"""单元测试：会话持久化、隔离、上下文与重置。"""
from __future__ import annotations

from backend.database import conversation_repo as repo


def test_session_isolation():
    first = repo.create_session(title="会话一")
    second = repo.create_session(title="会话二")
    repo.add_message(first["session_id"], "user", "会话一的问题")
    assert len(repo.get_messages(first["session_id"])) == 1
    assert repo.get_messages(second["session_id"]) == []


def test_history_roles_and_pending_persistence():
    session = repo.create_session()
    sid = session["session_id"]
    repo.add_message(sid, "user", "帮我创建工单")
    repo.add_message(sid, "assistant", "请确认信息", intent="ticket_create")
    repo.set_pending(sid, {"fault_type": "网络故障", "contact": "13800000000"}, "ticket_create")
    history = repo.history_for_llm(sid)
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert repo.get_pending(sid)["contact"] == "13800000000"


def test_reset_clears_messages_and_pending():
    session = repo.create_session()
    sid = session["session_id"]
    repo.add_message(sid, "user", "问题")
    repo.set_pending(sid, {"a": 1}, "ticket_create")
    repo.reset_session(sid)
    assert repo.get_messages(sid) == []
    assert repo.get_pending(sid) is None


def test_delete_session_cascades_messages():
    session = repo.create_session()
    sid = session["session_id"]
    repo.add_message(sid, "user", "问题")
    repo.delete_session(sid)
    assert repo.get_session(sid) is None
    assert repo.get_messages(sid) == []
