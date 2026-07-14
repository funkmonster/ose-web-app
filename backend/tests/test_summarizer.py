"""
Tests for utils/summarizer.py

maybe_update_summary() is the action-counting gate: it should only trigger
an LLM call every SUMMARIZE_EVERY player actions. _generate_summary() is the
actual LLM call + merge; it's tested against fake provider clients the same
way test_llm.py does, plus the "must never crash the GM loop" failure path.
"""

import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import utils.summarizer as summarizer
from utils.summarizer import maybe_update_summary, SUMMARY_KEY, ACTION_COUNT_KEY


def make_config(**overrides):
    defaults = dict(
        LLM_PROVIDER="ollama",  # exercises the get_gm_response fallback branch by default
        SUMMARIZE_EVERY=10,
        SUMMARIZE_CONTEXT_WINDOW=40,
        ANTHROPIC_API_KEY="sk-ant-test",
        ANTHROPIC_MODEL="claude-test",
        OPENAI_API_KEY="sk-openai-test",
        OPENAI_MODEL="gpt-test",
        OLLAMA_BASE_URL="http://localhost:11434",
        OLLAMA_MODEL="llama-test",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


@pytest.fixture
def db():
    fake = AsyncMock()
    fake.get_world_state.return_value = {}
    fake.get_history.return_value = []
    return fake


# ── maybe_update_summary() — counter/threshold logic ────────────────────────

async def test_increments_and_persists_counter_below_threshold(db):
    db.get_world_state.return_value = {}
    config = make_config(SUMMARIZE_EVERY=10)

    triggered = await maybe_update_summary(db, 1, config)

    assert triggered is False
    db.set_world_state.assert_awaited_once_with(1, ACTION_COUNT_KEY, "1")


async def test_counter_continues_from_existing_value(db):
    db.get_world_state.return_value = {ACTION_COUNT_KEY: "3"}
    config = make_config(SUMMARIZE_EVERY=10)

    await maybe_update_summary(db, 1, config)

    db.set_world_state.assert_awaited_once_with(1, ACTION_COUNT_KEY, "4")


async def test_triggers_summary_generation_at_threshold(db, monkeypatch):
    db.get_world_state.return_value = {ACTION_COUNT_KEY: "9"}
    config = make_config(SUMMARIZE_EVERY=10)
    generate = AsyncMock()
    monkeypatch.setattr(summarizer, "_generate_summary", generate)

    triggered = await maybe_update_summary(db, 1, config)

    assert triggered is True
    generate.assert_awaited_once_with(db, 1, config)


async def test_does_not_trigger_one_below_threshold(db, monkeypatch):
    db.get_world_state.return_value = {ACTION_COUNT_KEY: "8"}
    config = make_config(SUMMARIZE_EVERY=10)
    generate = AsyncMock()
    monkeypatch.setattr(summarizer, "_generate_summary", generate)

    triggered = await maybe_update_summary(db, 1, config)

    assert triggered is False
    generate.assert_not_awaited()


async def test_triggers_again_at_second_multiple(db, monkeypatch):
    db.get_world_state.return_value = {ACTION_COUNT_KEY: "19"}
    config = make_config(SUMMARIZE_EVERY=10)
    generate = AsyncMock()
    monkeypatch.setattr(summarizer, "_generate_summary", generate)

    triggered = await maybe_update_summary(db, 1, config)

    assert triggered is True
    db.set_world_state.assert_awaited_once_with(1, ACTION_COUNT_KEY, "20")


# ── _generate_summary() — transcript building ───────────────────────────────

async def test_generate_summary_includes_existing_summary_when_present(db, monkeypatch):
    db.get_world_state.return_value = {SUMMARY_KEY: "The party entered the dungeon."}
    db.get_history.return_value = [
        {"role": "user", "author_name": "Sean", "content": "I open the door."},
        {"role": "assistant", "author_name": None, "content": "It creaks open."},
    ]
    get_gm_response = AsyncMock(return_value="- New bullet point")
    monkeypatch.setattr(summarizer, "get_gm_response", get_gm_response)
    config = make_config(LLM_PROVIDER="ollama")

    await summarizer._generate_summary(db, 1, config)

    user_content = get_gm_response.await_args.args[0][0]["content"]
    assert "EXISTING SUMMARY:\nThe party entered the dungeon." in user_content
    assert "[Sean]: I open the door." in user_content
    assert "[assistant]: It creaks open." in user_content  # falls back to role when no author_name


async def test_generate_summary_omits_existing_summary_section_when_absent(db, monkeypatch):
    db.get_world_state.return_value = {}
    get_gm_response = AsyncMock(return_value="- Bullet")
    monkeypatch.setattr(summarizer, "get_gm_response", get_gm_response)
    config = make_config(LLM_PROVIDER="ollama")

    await summarizer._generate_summary(db, 1, config)

    user_content = get_gm_response.await_args.args[0][0]["content"]
    assert "EXISTING SUMMARY" not in user_content


async def test_generate_summary_uses_configured_history_window(db, monkeypatch):
    monkeypatch.setattr(summarizer, "get_gm_response", AsyncMock(return_value="x"))
    config = make_config(SUMMARIZE_CONTEXT_WINDOW=7)

    await summarizer._generate_summary(db, 1, config)

    db.get_history.assert_awaited_once_with(1, limit=7)


# ── _generate_summary() — ollama / fallback provider path ──────────────────

async def test_ollama_fallback_strips_and_stores_result(db, monkeypatch):
    monkeypatch.setattr(summarizer, "get_gm_response", AsyncMock(return_value="  - Bullet one  \n"))
    config = make_config(LLM_PROVIDER="ollama")

    await summarizer._generate_summary(db, 1, config)

    db.set_world_state.assert_awaited_once_with(1, SUMMARY_KEY, "- Bullet one")


async def test_ollama_fallback_prepends_summarizer_prompt(db, monkeypatch):
    get_gm_response = AsyncMock(return_value="x")
    monkeypatch.setattr(summarizer, "get_gm_response", get_gm_response)
    config = make_config(LLM_PROVIDER="ollama")

    await summarizer._generate_summary(db, 1, config)

    sent_content = get_gm_response.await_args.args[0][0]["content"]
    assert sent_content.startswith(summarizer.SUMMARIZER_PROMPT)


# ── _generate_summary() — anthropic provider path ───────────────────────────

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
        self.messages = FakeMessages("- Anthropic summary")
        FakeAsyncAnthropic.last_instance = self


async def test_anthropic_path_stores_stripped_summary(db, monkeypatch):
    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAsyncAnthropic)
    config = make_config(LLM_PROVIDER="anthropic")

    await summarizer._generate_summary(db, 1, config)

    db.set_world_state.assert_awaited_once_with(1, SUMMARY_KEY, "- Anthropic summary")
    call = FakeAsyncAnthropic.last_instance.messages.create_calls[0]
    assert call["system"] == summarizer.SUMMARIZER_PROMPT


# ── _generate_summary() — openai provider path ──────────────────────────────

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


async def test_openai_path_stores_stripped_summary(db, monkeypatch):
    fake_module, calls = make_fake_openai_module(" - OpenAI summary ")
    monkeypatch.setitem(__import__("sys").modules, "openai", fake_module)
    config = make_config(LLM_PROVIDER="openai")

    await summarizer._generate_summary(db, 1, config)

    db.set_world_state.assert_awaited_once_with(1, SUMMARY_KEY, "- OpenAI summary")
    assert calls[0]["messages"][0] == {"role": "system", "content": summarizer.SUMMARIZER_PROMPT}


# ── _generate_summary() — failure handling ──────────────────────────────────

async def test_llm_failure_is_non_fatal_and_does_not_store_summary(db, monkeypatch):
    monkeypatch.setattr(summarizer, "get_gm_response", AsyncMock(side_effect=RuntimeError("LLM down")))
    config = make_config(LLM_PROVIDER="ollama")

    await summarizer._generate_summary(db, 1, config)  # must not raise

    db.set_world_state.assert_not_awaited()


async def test_unknown_provider_failure_is_swallowed(db, monkeypatch):
    config = make_config(LLM_PROVIDER="not-a-real-provider")
    monkeypatch.setattr(summarizer, "get_gm_response", AsyncMock(return_value="x"))

    # "not-a-real-provider" doesn't match anthropic/openai, so falls into the
    # ollama/fallback branch and still succeeds via get_gm_response — this
    # confirms _generate_summary never raises ValueError for unknown providers.
    await summarizer._generate_summary(db, 1, config)
    db.set_world_state.assert_awaited_once()


async def test_maybe_update_summary_propagates_generation_even_if_it_fails_internally(db, monkeypatch):
    # _generate_summary swallows its own errors, so maybe_update_summary
    # should still report True (a generation attempt happened) even when
    # the underlying LLM call failed.
    db.get_world_state.return_value = {ACTION_COUNT_KEY: "9"}
    config = make_config(SUMMARIZE_EVERY=10, LLM_PROVIDER="ollama")
    monkeypatch.setattr(summarizer, "get_gm_response", AsyncMock(side_effect=RuntimeError("boom")))

    triggered = await maybe_update_summary(db, 1, config)

    assert triggered is True
