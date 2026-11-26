"""Tests for backend/client_summary/service.py, with the repositories and
the Claude call mocked."""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.client_summary import service

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
PROFILE = {"user_id": "u1", "name": "Asha", "gender": "female", "profile": {"goals": {"primary_goal": "strength"}}}


def _repo(latest=None, comments=None):
    repo = MagicMock()
    repo.get_profile_row.return_value = PROFILE
    repo.get_joint_pain.return_value = [{"joint": "knee", "pain_level": "mild"}]
    repo.get_plans.return_value = []
    repo.get_question_rounds.return_value = []
    repo.get_exercise_names.return_value = {}
    repo.get_comments.return_value = comments or []
    repo.get_period_logs.return_value = []
    repo.get_latest.return_value = latest
    repo.read_text.return_value = "OLD SUMMARY"
    repo.save.side_effect = lambda row, text: {**row, "id": 1, "storage_path": f"u1/v{row['version']}.txt"}
    return repo


def _latest(state_hash):
    return {"version": 2, "storage_path": "u1/v2.txt", "covers_until": "2026-11-24T00:00:00+00:00",
            "state_hash": state_hash}


COMMENT = [{"comment": "Knee ached.", "created_at": "2026-11-25T00:00:00+00:00"}]


def test_first_run_reads_everything_and_saves_version_1():
    repo, summarize = _repo(comments=COMMENT), MagicMock(return_value=("NEW", "claude-sonnet-5-5"))
    result = service.summarize_client(repo, MagicMock(), "u1", summarize, now=NOW)
    message = summarize.call_args.args[0]
    assert "FIRST SUMMARY" in message and "PREVIOUS SUMMARY" not in message
    repo.get_comments.assert_called_once_with("u1", None, NOW)
    row, text = repo.save.call_args.args
    assert (row["version"], row["covers_from"], row["covers_until"], row["rebuilt"], text) == (
        1, None, NOW.isoformat(), False, "NEW")
    assert result["nothing_new"] is False
    assert result["summary"]["text"] == "NEW" and result["summary"]["version"] == 1


def test_update_sends_previous_text_and_only_the_window():
    repo = _repo(latest=_latest("whatever"), comments=COMMENT)
    summarize = MagicMock(return_value=("V3", "m"))
    service.summarize_client(repo, MagicMock(), "u1", summarize, now=NOW)
    since = datetime(2026, 11, 24, tzinfo=timezone.utc)
    repo.get_comments.assert_called_once_with("u1", since, NOW)
    message = summarize.call_args.args[0]
    assert "PREVIOUS SUMMARY\nOLD SUMMARY" in message and "Knee ached." in message
    row = repo.save.call_args.args[0]
    assert row["version"] == 3 and row["covers_from"] == since.isoformat()


def test_nothing_new_and_same_state_skips_the_call():
    from backend.client_summary import render
    same = render.state_hash(PROFILE, [{"joint": "knee", "pain_level": "mild"}])
    repo, summarize = _repo(latest=_latest(same)), MagicMock()
    result = service.summarize_client(repo, MagicMock(), "u1", summarize, now=NOW)
    summarize.assert_not_called()
    repo.save.assert_not_called()
    assert result["nothing_new"] is True and result["summary"]["text"] == "OLD SUMMARY"


def test_state_change_alone_triggers_an_update():
    repo, summarize = _repo(latest=_latest("stale-hash")), MagicMock(return_value=("V3", "m"))
    assert service.summarize_client(repo, MagicMock(), "u1", summarize, now=NOW)["nothing_new"] is False
    summarize.assert_called_once()


def test_rebuild_ignores_the_previous_text_but_keeps_numbering():
    repo, summarize = _repo(latest=_latest("x")), MagicMock(return_value=("FRESH", "m"))
    service.summarize_client(repo, MagicMock(), "u1", summarize, rebuild=True, now=NOW)
    repo.read_text.assert_not_called()
    assert "FIRST SUMMARY" in summarize.call_args.args[0]
    row = repo.save.call_args.args[0]
    assert row["version"] == 3 and row["rebuilt"] is True and row["covers_from"] is None


def test_unknown_client():
    repo = _repo()
    repo.get_profile_row.return_value = None
    with pytest.raises(service.ClientNotFoundError):
        service.summarize_client(repo, MagicMock(), "nobody", MagicMock(), now=NOW)
