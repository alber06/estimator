"""Tests for session schemas and in-memory store."""

from app.schemas.session import ConversationHistory, ProjectMetadata, Session
from app.services.sessions import SessionStore


def test_conversation_history_trims_oldest_preserving_system() -> None:
    history = ConversationHistory(system_prompt="You are an estimator.", max_turns=4)
    for i in range(6):
        role = "user" if i % 2 == 0 else "assistant"
        history.append(role, f"message-{i}")

    assert history.system_prompt == "You are an estimator."
    assert len(history.messages) == 4
    assert history.messages[0].content == "message-2"
    assert history.messages[-1].content == "message-5"

    llm_messages = history.as_llm_messages()
    assert llm_messages[0] == {"role": "system", "content": "You are an estimator."}
    assert len(llm_messages) == 5


def test_session_store_get_or_create_returns_same_instance() -> None:
    store = SessionStore()
    first = store.get_or_create("abc-123")
    second = store.get_or_create("abc-123")

    assert first is second
    assert isinstance(first.project_metadata, ProjectMetadata)
    assert isinstance(first.conversation_history, ConversationHistory)


def test_session_store_delete() -> None:
    store = SessionStore()
    store.get_or_create("to-delete")
    assert store.delete("to-delete") is True
    assert store.get("to-delete") is None
    assert store.delete("to-delete") is False


def test_session_defaults() -> None:
    session = Session("new-session")
    assert session.project_metadata.project_name == ""
    assert session.project_metadata.mentioned_technologies == []
