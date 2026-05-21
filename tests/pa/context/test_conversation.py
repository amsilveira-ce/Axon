"""
tests/pa/context/test_conversation.py

Testes determinísticos do ConversationHistory.
Sem LLM, sem filesystem real (usa tmp_path do pytest).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from axon.config import ConversationConfig
from axon.pa.context.conversation import ConversationHistory, Message


# ---------------------------------------------------------------------------
#   Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config_small() -> ConversationConfig:
    """Janela de 3 mensagens para facilitar testes de overflow."""
    return ConversationConfig(max_messages=3, window_mode="messages")


@pytest.fixture
def config_default() -> ConversationConfig:
    return ConversationConfig()


@pytest.fixture
def empty_history(config_small) -> ConversationHistory:
    return ConversationHistory(session_id="test-session", config=config_small)


@pytest.fixture
def history_with_messages(config_small) -> ConversationHistory:
    h = ConversationHistory(session_id="test-session", config=config_small)
    h.add_message("user",      "hello")
    h.add_message("assistant", "hi there")
    return h


# ---------------------------------------------------------------------------
#   add_message
# ---------------------------------------------------------------------------

def test_add_message_appends_turn(empty_history):
    empty_history.add_message("user", "hello")
    assert len(empty_history.messages) == 1
    assert empty_history.messages[0].role == "user"
    assert empty_history.messages[0].content == "hello"


def test_add_message_preserves_order(empty_history):
    empty_history.add_message("user",      "first")
    empty_history.add_message("assistant", "second")
    empty_history.add_message("user",      "third")
    assert [m.content for m in empty_history.messages] == ["first", "second", "third"]


def test_add_message_updates_timestamp(empty_history):
    before = empty_history.updated_at
    empty_history.add_message("user", "hello")
    assert empty_history.updated_at >= before


# ---------------------------------------------------------------------------
#   Sliding window
# ---------------------------------------------------------------------------

def test_window_not_exceeded_below_limit(empty_history):
    empty_history.add_message("user",      "msg 1")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    # exatamente no limite — não deve cortar
    assert len(empty_history.messages) == 3


def test_window_trims_when_exceeded(empty_history):
    empty_history.add_message("user",      "msg 1")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    empty_history.add_message("assistant", "msg 4")   # overflow
    # deve manter só os últimos 3
    assert len(empty_history.messages) == 3
    assert empty_history.messages[0].content == "msg 2"
    assert empty_history.messages[-1].content == "msg 4"


def test_window_keeps_most_recent(empty_history):
    for i in range(6):
        role = "user" if i % 2 == 0 else "assistant"
        empty_history.add_message(role, f"msg {i}")
    assert len(empty_history.messages) == 3
    assert empty_history.messages[-1].content == "msg 5"


# ---------------------------------------------------------------------------
#   Sumarização no overflow
# ---------------------------------------------------------------------------

def test_summarization_called_when_overflow(empty_history):
    mock_client = MagicMock()
    mock_client.chat.return_value = "summary text"
    
    empty_history.add_message("user",      "msg 1")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    empty_history.add_message("assistant", "msg 4", llm_client=mock_client)

    assert mock_client.chat.called
    assert empty_history.summary == "summary text"


def test_summarization_receives_overflow_messages(empty_history):
    """Verifica que o summarizer recebe exatamente os turnos que saíram."""
    captured: list = []

    mock_client = MagicMock()
    def capture_call(*args, **kwargs):
        captured.append(kwargs.get("messages", args[0] if args else []))
        return "summary"
    mock_client.chat.side_effect = capture_call
    
    empty_history.add_message("user",      "overflow msg")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    empty_history.add_message("assistant", "msg 4", llm_client=mock_client)

    # verifica que "overflow msg" aparece no conteúdo passado ao LLM
    call_content = str(captured)
    assert "overflow msg" in call_content


def test_summarization_accumulates_existing_summary(empty_history):
    """Summary existente deve ser passado para o próximo ciclo."""
    empty_history.summary = "previous summary"

    mock_client = MagicMock()
    mock_client.chat.return_value = "new accumulated summary"
    
    empty_history.add_message("user",      "msg 1")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    empty_history.add_message("assistant", "msg 4", llm_client=mock_client)

    call_args = str(mock_client.chat.call_args)
    assert "previous summary" in call_args
    assert empty_history.summary == "new accumulated summary"


def test_overflow_without_summarizer_discards_messages(empty_history):
    """Sem summarizer, overflow é descartado — summary permanece."""
    empty_history.summary = "existing summary"

    empty_history.add_message("user",      "msg 1")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    empty_history.add_message("assistant", "msg 4")   # overflow, sem summarizer

    assert len(empty_history.messages) == 3
    assert empty_history.summary == "existing summary"   # não muda


def test_summarizer_fallback_on_llm_error(empty_history):
    """Se o LLM falhar, summary anterior é preservado."""
    empty_history.summary = "preserved summary"

    mock_client = MagicMock()
    mock_client.chat.side_effect = Exception("LLM unavailable")
    
    empty_history.add_message("user",      "msg 1")
    empty_history.add_message("assistant", "msg 2")
    empty_history.add_message("user",      "msg 3")
    empty_history.add_message("assistant", "msg 4", llm_client=mock_client)

    assert empty_history.summary == "preserved summary"


# ---------------------------------------------------------------------------
#   get_context — formato OpenAI
# ---------------------------------------------------------------------------

def test_get_context_returns_openai_format(history_with_messages):
    ctx = history_with_messages.get_context()
    assert isinstance(ctx, list)
    for msg in ctx:
        assert "role" in msg
        assert "content" in msg
        assert msg["role"] in ("user", "assistant", "system")


def test_get_context_includes_all_messages(history_with_messages):
    ctx = history_with_messages.get_context()
    contents = [m["content"] for m in ctx]
    assert "hello" in contents
    assert "hi there" in contents


def test_get_context_empty_without_summary(empty_history):
    ctx = empty_history.get_context()
    assert ctx == []


def test_get_context_includes_summary_when_present(empty_history):
    empty_history.summary = "user wants a report"
    ctx = empty_history.get_context()
    assert len(ctx) >= 1
    first = ctx[0]
    assert "[Summary" in first["content"]
    assert "user wants a report" in first["content"]


def test_summary_prepended_before_messages(history_with_messages):
    history_with_messages.summary = "prior context"
    ctx = history_with_messages.get_context()
    # primeiro elemento deve ser o summary
    assert "[Summary" in ctx[0]["content"]
    # mensagens vêm depois
    last_contents = [m["content"] for m in ctx[1:]]
    assert "hello" in last_contents


def test_get_context_str_returns_string(history_with_messages):
    result = history_with_messages.get_context_str()
    assert isinstance(result, str)
    assert "hello" in result
    assert "hi there" in result


def test_get_context_str_empty_returns_no_history(empty_history):
    result = empty_history.get_context_str()
    assert result == "No previous conversation."


def test_get_context_str_includes_summary(empty_history):
    empty_history.summary = "prior intent"
    result = empty_history.get_context_str()
    assert "[Summary" in result
    assert "prior intent" in result


# ---------------------------------------------------------------------------
#   Helpers
# ---------------------------------------------------------------------------

def test_is_empty_true_when_new(empty_history):
    assert empty_history.is_empty() is True


def test_is_empty_false_after_message(empty_history):
    empty_history.add_message("user", "hello")
    assert empty_history.is_empty() is False


def test_is_empty_false_with_summary_only(empty_history):
    empty_history.summary = "something"
    assert empty_history.is_empty() is False


def test_last_user_message_returns_most_recent(history_with_messages):
    history_with_messages.add_message("user",      "second user msg")
    history_with_messages.add_message("assistant", "response")
    assert history_with_messages.last_user_message() == "second user msg"


def test_last_user_message_returns_none_when_empty(empty_history):
    assert empty_history.last_user_message() is None


# ---------------------------------------------------------------------------
#   Persistência
# ---------------------------------------------------------------------------

def test_persist_creates_file(tmp_path, empty_history):
    empty_history.add_message("user", "test")
    empty_history.persist(tmp_path)

    expected = tmp_path / "test-session.json"
    assert expected.exists()


def test_persist_file_contains_valid_json(tmp_path, empty_history):
    empty_history.add_message("user", "hello")
    empty_history.persist(tmp_path)

    path = tmp_path / "test-session.json"
    data = json.loads(path.read_text())
    assert data["session_id"] == "test-session"
    assert len(data["messages"]) == 1


def test_persist_creates_directory_if_missing(tmp_path, empty_history):
    nested = tmp_path / "deep" / "sessions"
    empty_history.persist(nested)
    assert (nested / "test-session.json").exists()


def test_load_returns_same_data(tmp_path, empty_history):
    empty_history.add_message("user",      "hello")
    empty_history.add_message("assistant", "hi")
    empty_history.summary = "some summary"
    empty_history.persist(tmp_path)

    loaded = ConversationHistory.load_or_create("test-session", tmp_path)
    assert loaded.session_id == "test-session"
    assert len(loaded.messages) == 2
    assert loaded.summary == "some summary"
    assert loaded.messages[0].content == "hello"


def test_load_or_create_returns_new_when_not_found(tmp_path):
    h = ConversationHistory.load_or_create("nonexistent-session", tmp_path)
    assert h.session_id == "nonexistent-session"
    assert h.is_empty()


def test_load_or_create_returns_empty_when_not_found(tmp_path, config_small):
    history = ConversationHistory.load_or_create(
        session_id="new-session",
        sessions_dir=tmp_path,
        config=config_small,
    )
    assert history.session_id == "new-session"
    assert history.is_empty()


def test_load_or_create_loads_existing(tmp_path, empty_history, config_small):
    empty_history.add_message("user", "persisted message")
    empty_history.persist(tmp_path)

    loaded = ConversationHistory.load_or_create(
        session_id="test-session",
        sessions_dir=tmp_path,
        config=config_small,
    )
    assert loaded.messages[0].content == "persisted message"


def test_load_or_create_generates_uuid_when_session_id_none(tmp_path, config_small):
    history = ConversationHistory.load_or_create(
        session_id=None,
        sessions_dir=tmp_path,
        config=config_small,
    )
    assert history.session_id is not None
    assert len(history.session_id) > 0


def test_load_or_create_updates_config_on_load(tmp_path, config_small):
    """Config atual do PAConfig sobrescreve o config da sessão carregada."""
    empty_history = ConversationHistory(
        session_id="test-session",
        config=ConversationConfig(max_messages=2),
    )
    empty_history.persist(tmp_path)

    new_config = ConversationConfig(max_messages=10)
    loaded = ConversationHistory.load_or_create(
        session_id="test-session",
        sessions_dir=tmp_path,
        config=new_config,
    )
    assert loaded.config.max_messages == 10


def test_persist_and_reload_roundtrip(tmp_path, config_small):
    """Roundtrip completo — persistir e recarregar preserva todos os dados."""
    original = ConversationHistory(
        session_id="roundtrip",
        config=config_small,
        summary="accumulated summary",
    )
    original.add_message("user",      "what is axon?")
    original.add_message("assistant", "axon is a multi-agent framework")
    original.persist(tmp_path)

    loaded = ConversationHistory.load_or_create("roundtrip", tmp_path)
    assert loaded.summary == "accumulated summary"
    assert len(loaded.messages) == 2
    assert loaded.messages[1].role == "assistant"
    assert "multi-agent" in loaded.messages[1].content