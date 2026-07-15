"""
Tests for utils/llm.py

get_gm_response() just dispatches to a provider-specific function based on
config.LLM_PROVIDER, so that dispatch is tested with the real _call_*
functions swapped out. The provider-specific functions do their own request
shaping and are tested against fake SDK clients:
  - anthropic really is a project dependency, so we monkeypatch the
    AsyncAnthropic class on the real module.
  - openai and aiohttp are *optional* dependencies (commented out in
    requirements.txt) and may not be installed in the test environment, so
    we inject fake modules via sys.modules instead of assuming they exist.
"""

import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import utils.llm as llm


def make_config(**overrides):
    defaults = dict(
        LLM_PROVIDER="anthropic",
        ANTHROPIC_API_KEY="sk-ant-test",
        ANTHROPIC_MODEL="claude-test",
        OPENAI_API_KEY="sk-openai-test",
        OPENAI_MODEL="gpt-test",
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_MODEL="llama-test",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── get_gm_response() — dispatch ────────────────────────────────────────────

async def test_dispatches_to_anthropic(monkeypatch):
    mock = AsyncMock(return_value="reply")
    monkeypatch.setattr(llm, "_call_anthropic", mock)
    config = make_config(LLM_PROVIDER="anthropic")

    result = await llm.get_gm_response([{"role": "user", "content": "hi"}], config)

    assert result == "reply"
    mock.assert_awaited_once()


async def test_dispatches_to_openai(monkeypatch):
    mock = AsyncMock(return_value="reply")
    monkeypatch.setattr(llm, "_call_openai", mock)
    config = make_config(LLM_PROVIDER="openai")

    result = await llm.get_gm_response([], config)

    assert result == "reply"
    mock.assert_awaited_once()


async def test_dispatches_to_ollama(monkeypatch):
    mock = AsyncMock(return_value="reply")
    monkeypatch.setattr(llm, "_call_ollama", mock)
    config = make_config(LLM_PROVIDER="ollama")

    result = await llm.get_gm_response([], config)

    assert result == "reply"
    mock.assert_awaited_once()


async def test_dispatch_is_case_insensitive(monkeypatch):
    mock = AsyncMock(return_value="reply")
    monkeypatch.setattr(llm, "_call_anthropic", mock)
    config = make_config(LLM_PROVIDER="AnThRoPiC")

    await llm.get_gm_response([], config)
    mock.assert_awaited_once()


async def test_unknown_provider_raises_value_error():
    config = make_config(LLM_PROVIDER="grok")
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        await llm.get_gm_response([], config)


# ── _call_anthropic() ────────────────────────────────────────────────────────

class FakeMessages:
    def __init__(self, response_text):
        self.response_text = response_text
        self.create_calls = []

    async def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(text=self.response_text)])


class FakeAsyncAnthropic:
    last_instance = None

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.messages = FakeMessages("The torch flickers.")
        FakeAsyncAnthropic.last_instance = self


async def test_call_anthropic_returns_reply_text(monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    config = make_config()
    messages = [{"role": "user", "content": "I light a torch."}]

    result = await llm._call_anthropic(messages, config)

    assert result == "The torch flickers."


async def test_call_anthropic_passes_system_prompt_model_and_messages(monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    config = make_config(ANTHROPIC_MODEL="claude-special")
    messages = [{"role": "user", "content": "I light a torch."}]

    await llm._call_anthropic(messages, config)

    call = FakeAsyncAnthropic.last_instance.messages.create_calls[0]
    assert call["model"] == "claude-special"
    assert call["system"] == llm.OSE_SYSTEM_PROMPT
    assert call["messages"] == messages


async def test_call_anthropic_marks_last_assistant_message_for_caching(monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    config = make_config()
    messages = [
        {"role": "user", "content": "[Sean]: I open the door."},
        {"role": "assistant", "content": "It creaks open."},
        {"role": "user", "content": "[Sean]: I step through."},
        {"role": "user", "content": "[CURRENT STATE] party is healthy"},
    ]

    await llm._call_anthropic(messages, config)

    sent = FakeAsyncAnthropic.last_instance.messages.create_calls[0]["messages"]
    assert sent[1] == {
        "role": "assistant",
        "content": [{
            "type": "text",
            "text": "It creaks open.",
            "cache_control": {"type": "ephemeral"},
        }],
    }
    # Turns after the breakpoint (the volatile tail) stay unmarked...
    assert sent[0] == messages[0]
    assert sent[2:] == messages[2:]
    # ...and the caller's list is not mutated.
    assert messages[1] == {"role": "assistant", "content": "It creaks open."}


async def test_call_anthropic_without_assistant_turn_adds_no_breakpoint(monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    config = make_config()
    messages = [{"role": "user", "content": "Begin the campaign."}]

    await llm._call_anthropic(messages, config)

    sent = FakeAsyncAnthropic.last_instance.messages.create_calls[0]["messages"]
    assert sent == messages


async def test_call_anthropic_uses_api_key_from_config(monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    config = make_config(ANTHROPIC_API_KEY="sk-ant-specific")

    await llm._call_anthropic([], config)

    assert FakeAsyncAnthropic.last_instance.api_key == "sk-ant-specific"


# ── _call_openai() ───────────────────────────────────────────────────────────

def make_fake_openai_module(response_text):
    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            message = SimpleNamespace(content=response_text)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeAsyncOpenAI:
        def __init__(self, api_key=None):
            self.api_key = api_key
            self.chat = FakeChat()

    module = types.SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI)
    return module, calls


async def test_call_openai_returns_reply_and_prepends_system_message(monkeypatch):
    fake_module, calls = make_fake_openai_module("A goblin snarls.")
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
    config = make_config(OPENAI_MODEL="gpt-special")
    messages = [{"role": "user", "content": "I draw my sword."}]

    result = await llm._call_openai(messages, config)

    assert result == "A goblin snarls."
    call = calls[0]
    assert call["model"] == "gpt-special"
    assert call["messages"][0] == {"role": "system", "content": llm.OSE_SYSTEM_PROMPT}
    assert call["messages"][1:] == messages


async def test_call_openai_missing_package_raises_runtime_error(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "openai", raising=False)
    monkeypatch.setattr(
        "builtins.__import__",
        _blocking_import_for("openai"),
    )
    config = make_config()

    with pytest.raises(RuntimeError, match="pip install openai"):
        await llm._call_openai([], config)


# ── _call_ollama() ───────────────────────────────────────────────────────────

def make_fake_aiohttp_module(response_json):
    calls = []

    class FakeResp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def json(self):
            return response_json

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, json=None):
            calls.append({"url": url, "json": json})
            return FakeResp()

    module = types.SimpleNamespace(ClientSession=FakeSession)
    return module, calls


async def test_call_ollama_returns_reply_and_posts_to_configured_url(monkeypatch):
    fake_module, calls = make_fake_aiohttp_module({"message": {"content": "You hear dripping water."}})
    monkeypatch.setitem(__import__("sys").modules, "aiohttp", fake_module)
    config = make_config(OLLAMA_BASE_URL="http://ollama-host:11434", OLLAMA_MODEL="llama-special")
    messages = [{"role": "user", "content": "I listen."}]

    result = await llm._call_ollama(messages, config)

    assert result == "You hear dripping water."
    assert calls[0]["url"] == "http://ollama-host:11434/api/chat"
    payload = calls[0]["json"]
    assert payload["model"] == "llama-special"
    assert payload["stream"] is False
    assert payload["messages"][0] == {"role": "system", "content": llm.OSE_SYSTEM_PROMPT}
    assert payload["messages"][1:] == messages


async def test_call_ollama_missing_package_raises_runtime_error(monkeypatch):
    monkeypatch.delitem(__import__("sys").modules, "aiohttp", raising=False)
    monkeypatch.setattr(
        "builtins.__import__",
        _blocking_import_for("aiohttp"),
    )
    config = make_config()

    with pytest.raises(RuntimeError, match="pip install aiohttp"):
        await llm._call_ollama([], config)


# ── helpers ──────────────────────────────────────────────────────────────────

def _blocking_import_for(blocked_name):
    """Build a stand-in for builtins.__import__ that fails only for one module."""
    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(f"No module named {blocked_name!r}")
        return real_import(name, *args, **kwargs)

    return _fake_import
