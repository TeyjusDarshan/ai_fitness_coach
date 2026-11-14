"""Tests for ai_usage: cost maths and what each recorder writes. The root
conftest replaces ai_usage.recorder._insert with a mock (the fixture
`_no_ai_usage_writes`), so nothing reaches the database."""
from types import SimpleNamespace

import pytest

from ai_usage import prices, record_claude, record_langchain, record_stt, record_tts, set_feature_prefix


@pytest.fixture(autouse=True)
def _rate(monkeypatch):
    monkeypatch.setenv("USD_INR_RATE", "94")
    yield
    set_feature_prefix("")


def _row(insert):
    insert.assert_called_once()
    return insert.call_args.args[0]


def test_claude_response_is_priced_and_converted(_no_ai_usage_writes):
    response = SimpleNamespace(
        id="msg_1", model="claude-sonnet-5-5",
        usage=SimpleNamespace(input_tokens=7000, output_tokens=2000, cache_read_input_tokens=1000,
                              cache_creation_input_tokens=0),
    )

    record_claude(response, "summary_questions", user_id="usr_1", session_id=84)

    row = _row(_no_ai_usage_writes)
    # 7000*2 + 2000*10 + 1000*0.10 = 34100 per million -> $0.0341
    assert row["cost_usd"] == pytest.approx(0.0341)
    assert row["cost_inr_total"] == pytest.approx(0.0341 * 94, abs=1e-4)
    assert (row["provider"], row["feature"], row["user_id"], row["session_id"], row["request_id"]) == (
        "anthropic", "summary_questions", "usr_1", 84, "msg_1"
    )
    assert row["usd_inr_rate"] == 94


def test_unknown_model_records_tokens_without_a_cost(_no_ai_usage_writes):
    response = SimpleNamespace(model="claude-mystery", usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    record_claude(response, "x")
    row = _row(_no_ai_usage_writes)
    assert row["input_tokens"] == 10 and row["cost_usd"] is None and row["cost_inr_total"] is None


def test_a_response_without_usage_is_ignored(_no_ai_usage_writes):
    record_claude(SimpleNamespace(), "x")
    _no_ai_usage_writes.assert_not_called()


def test_langchain_run_is_summed_into_one_row(_no_ai_usage_writes):
    def msg(inp, out, cache_read=0):
        return SimpleNamespace(
            usage_metadata={"input_tokens": inp, "output_tokens": out,
                            "input_token_details": {"cache_read": cache_read}},
            response_metadata={"model_name": "claude-sonnet-5"},
        )
    messages = [SimpleNamespace(), msg(1000, 100), msg(3000, 200, cache_read=1000)]

    record_langchain(messages, "plan_generation", user_id="usr_1")

    row = _row(_no_ai_usage_writes)
    assert (row["calls"], row["input_tokens"], row["output_tokens"], row["cache_read_tokens"]) == (2, 3000, 300, 1000)
    assert row["cost_usd"] == pytest.approx((3000 * 2 + 300 * 10 + 1000 * 0.20) / 1_000_000)


def test_stt_is_billed_per_second_of_audio(_no_ai_usage_writes, monkeypatch):
    monkeypatch.setattr("ai_usage.recorder.audio_seconds", lambda audio: 16.2)
    record_stt(b"webm", "a.webm", "saaras:v4", "voice_note_stt", user_id="usr_1", session_id=81)
    row = _row(_no_ai_usage_writes)
    assert row["audio_seconds"] == 16.2
    assert row["cost_inr"] == pytest.approx(17 * 0.49 / 60, abs=1e-4)   # 17 billed seconds
    assert row["cost_inr_total"] == row["cost_inr"]


def test_tts_is_billed_per_character(_no_ai_usage_writes):
    set_feature_prefix("dry_run_")
    record_tts("x" * 600, "bulbul:v3", "summary_tts", user_id="usr_1")
    row = _row(_no_ai_usage_writes)
    assert (row["characters"], row["cost_inr"], row["feature"]) == (600, 1.8, "dry_run_summary_tts")


def test_a_failed_write_never_raises(_no_ai_usage_writes):
    _no_ai_usage_writes.side_effect = RuntimeError("db down")
    record_tts("hi", "bulbul:v3", "summary_tts")  # no exception


def test_dated_model_names_are_priced_like_the_base_model():
    assert prices.claude_cost_usd("claude-opus-5-5-20261101", 1_000_000, 0) == 4.0
