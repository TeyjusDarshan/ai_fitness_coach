"""Tests for the meal reminders (voice_processor/meal_reminders.py). The
repository, Sarvam and WhatsApp are all mocked."""
from datetime import date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from voice_processor import meal_reminders as mr

DAY = date(2026, 11, 23)
USER = "9876543210"
PHONE = "919876543210"
IST = ZoneInfo("Asia/Kolkata")


def _log(created_at, *meals):
    return {"id": 1, "created_at": created_at, "meal_log_items": [{"meal": meal} for meal in meals]}


def _client(user_id=USER, name="Priya", phone=PHONE, tz="Asia/Kolkata"):
    return {"user_id": user_id, "name": name, "whatsapp_number": phone, "timezone": tz}


@pytest.fixture
def repo():
    repo = MagicMock()
    repo.list_reminder_recipients.return_value = [_client()]
    repo.get_meal_reminder.return_value = None
    repo.list_counted_meal_logs.return_value = []
    repo.reply_window.return_value = {"window_open": True}
    repo.create_meal_reminder.return_value = {"id": 77}
    return repo


@pytest.fixture
def sender(monkeypatch):
    sender = MagicMock()
    sender.send.return_value = "https://audio/reminder.ogg?v=1"
    monkeypatch.setattr(mr, "Sender", lambda: sender)
    # Every client's "now" is 23 Nov 12:00 in her own zone unless a test says otherwise.
    monkeypatch.setattr(mr, "now_in", lambda tz=None: datetime(2026, 11, 23, 12, 0, tzinfo=ZoneInfo(tz or "Asia/Kolkata")))
    return sender


def _created(repo):
    return repo.create_meal_reminder.call_args.args[0]


# --- what's missing ---------------------------------------------------------

def test_each_slot_only_asks_about_meals_not_yet_logged():
    breakfast_only = {"breakfast"}
    assert mr.missing_meals("breakfast", breakfast_only) == []
    assert mr.missing_meals("lunch", breakfast_only) == ["lunch"]
    assert mr.missing_meals("dinner", breakfast_only) == ["lunch", "snack", "dinner"]
    assert mr.missing_meals("lunch", set()) == ["breakfast", "lunch"]
    assert mr.missing_meals("dinner", {"breakfast", "lunch"}) == ["snack", "dinner"]


def test_a_dish_with_no_meal_counts_by_when_it_was_logged_in_her_zone():
    # 03:30 UTC = 09:00 IST, 07:30 UTC = 13:00 IST, 12:00 UTC = 17:30 IST, 15:00 UTC = 20:30 IST
    logs = [_log("2026-11-23T03:30:00+00:00", None), _log("2026-11-23T07:30:00+00:00", None),
            _log("2026-11-23T12:00:00+00:00", None), _log("2026-11-23T15:00:00+00:00", None)]
    assert mr.logged_meals(logs) == {"breakfast", "lunch", "snack", "dinner"}
    assert mr.logged_meals([_log("2026-11-23T03:30:00+00:00", "dinner")]) == {"dinner"}
    # 12:00 UTC is 17:30 in India (snack) but 12:00 in London (lunch).
    assert mr.logged_meals([_log("2026-11-23T12:00:00+00:00", None)], "Europe/London") == {"lunch"}


def test_the_text_names_only_the_missing_meals():
    assert mr.reminder_text("Priya", ["lunch"]).startswith("வணக்கம் Priya! இன்னைக்கு மதிய சாப்பாடு என்ன")
    text = mr.reminder_text(None, ["snack", "dinner"])
    assert text.startswith("வணக்கம்! இன்னைக்கு ஸ்னாக்ஸ் அப்புறம் இரவு சாப்பாடு என்ன")
    assert "காலை" not in text


# --- which slot is due ---------------------------------------------------------

@pytest.mark.parametrize("hour, minute, slot", [
    (10, 59, None), (11, 0, "breakfast"), (11, 44, "breakfast"), (11, 45, None),
    (15, 10, "lunch"), (19, 59, None), (20, 30, "dinner"), (23, 0, None),
])
def test_a_slot_is_due_for_45_minutes_after_its_time(hour, minute, slot):
    assert mr.due_slot(datetime(2026, 11, 23, hour, minute, tzinfo=IST)) == slot


def test_due_mode_uses_each_clients_own_clock(repo, sender, monkeypatch):
    # 05:35 UTC: 11:05 in India, 09:35 in Dubai, 05:35 in London, 18:35 in Auckland.
    utc = datetime(2026, 11, 23, 5, 35, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(mr, "now_in", lambda tz=None: utc.astimezone(ZoneInfo(tz)))
    repo.list_reminder_recipients.return_value = [
        _client("in", tz="Asia/Kolkata"), _client("ae", phone="971501234567", tz="Asia/Dubai"),
        _client("uk", phone="447700900123", tz="Europe/London"),
    ]

    counts = mr.run(repo)

    assert counts == {"sent": 1, "not_due": 2}
    assert _created(repo)["user_id"] == "in" and _created(repo)["slot"] == "breakfast"


def test_dubai_gets_breakfast_at_11_her_time(repo, sender, monkeypatch):
    # 07:05 UTC = 11:05 in Dubai (12:35 in India: nothing due there).
    utc = datetime(2026, 11, 23, 7, 5, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(mr, "now_in", lambda tz=None: utc.astimezone(ZoneInfo(tz)))
    repo.list_reminder_recipients.return_value = [_client(phone="971501234567", tz="Asia/Dubai")]

    assert mr.run(repo) == {"sent": 1}

    assert _created(repo)["slot"] == "breakfast"
    repo.reply_window.assert_called_once_with("971501234567")
    assert sender.send.call_args.args[1] == "971501234567"


def test_the_reminder_date_is_her_local_date(repo, sender, monkeypatch):
    # 22:10 UTC on the 22nd is already 11:10 on the 23rd in Auckland.
    utc = datetime(2026, 11, 22, 22, 10, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(mr, "now_in", lambda tz=None: utc.astimezone(ZoneInfo(tz)))
    repo.list_reminder_recipients.return_value = [_client(phone="64211234567", tz="Pacific/Auckland")]

    mr.run(repo)

    assert _created(repo)["reminder_date"] == "2026-11-23"
    repo.list_counted_meal_logs.assert_called_once_with(USER, DAY)


# --- one client --------------------------------------------------------------

def test_a_missing_meal_with_an_open_window_is_sent(repo, sender):
    repo.list_counted_meal_logs.return_value = [_log("2026-11-23T03:30:00+00:00", "breakfast")]

    counts = mr.run(repo, slot="lunch")

    assert counts == {"sent": 1}
    repo.list_counted_meal_logs.assert_called_once_with(USER, DAY)
    repo.reply_window.assert_called_once_with(PHONE)
    assert _created(repo) == {"user_id": USER, "reminder_date": "2026-11-23", "slot": "lunch",
                              "missing_meals": ["lunch"], "status": "pending"}
    user_id, phone, text, day, slot = sender.send.call_args.args
    assert (user_id, phone, day, slot) == (USER, PHONE, DAY, "lunch")
    assert "மதிய சாப்பாடு" in text and "காலை டிபன்" not in text
    fields = repo.update_meal_reminder.call_args.args[1]
    assert repo.update_meal_reminder.call_args.args[0] == 77
    assert (fields["status"], fields["audio_url"]) == ("sent", "https://audio/reminder.ogg?v=1") and fields["sent_at"]


def test_everything_logged_sends_nothing(repo, sender):
    repo.list_counted_meal_logs.return_value = [_log("2026-11-23T03:30:00+00:00", "breakfast")]

    assert mr.run(repo, slot="breakfast") == {"skipped_logged": 1}

    assert _created(repo)["status"] == "skipped_logged"
    repo.reply_window.assert_not_called()
    sender.send.assert_not_called()


@pytest.mark.parametrize("window", [None, {"window_open": False}])
def test_a_closed_or_unknown_window_is_skipped(repo, sender, window):
    repo.reply_window.return_value = window

    assert mr.run(repo, slot="breakfast") == {"skipped_window_closed": 1}

    assert _created(repo) == {"user_id": USER, "reminder_date": "2026-11-23", "slot": "breakfast",
                              "missing_meals": ["breakfast"], "status": "skipped_window_closed", "error": None}
    sender.send.assert_not_called()


def test_a_client_with_no_whatsapp_number_is_skipped(repo, sender):
    repo.list_reminder_recipients.return_value = [_client(phone=None)]

    assert mr.run(repo, slot="breakfast") == {"skipped_window_closed": 1}

    assert _created(repo)["error"] == "no WhatsApp number"
    repo.reply_window.assert_not_called()


def test_a_slot_already_handled_today_is_left_alone(repo, sender):
    repo.get_meal_reminder.return_value = {"id": 5, "status": "sent"}

    assert mr.run(repo, slot="dinner") == {"already_handled": 1}

    repo.get_meal_reminder.assert_called_once_with(USER, DAY, "dinner")
    repo.create_meal_reminder.assert_not_called()
    sender.send.assert_not_called()


def test_losing_the_insert_race_does_not_send(repo, sender):
    repo.create_meal_reminder.return_value = None

    assert mr.run(repo, slot="breakfast") == {"already_handled": 1}
    sender.send.assert_not_called()


def test_a_failed_send_is_recorded_and_the_next_client_still_gets_hers(repo, sender):
    repo.list_reminder_recipients.return_value = [_client("1111111111", "A", "911111111111"), _client(name="B")]
    sender.send.side_effect = [RuntimeError("tts down"), "https://audio/b.ogg"]

    assert mr.run(repo, slot="breakfast") == {"failed": 1, "sent": 1}

    first, second = repo.update_meal_reminder.call_args_list
    assert first.args[1] == {"status": "failed", "error": "tts down"}
    assert second.args[1]["status"] == "sent"


def test_a_dry_run_stores_and_sends_nothing(repo, sender, capsys):
    assert mr.run(repo, slot="lunch", dry_run=True) == {"sent": 1}

    repo.create_meal_reminder.assert_not_called()
    sender.send.assert_not_called()
    out = capsys.readouterr().out
    assert "missing=['breakfast', 'lunch']" in out and "வணக்கம் Priya" in out


def test_recipients_can_be_limited_to_one_client(repo, sender):
    mr.run(repo, slot="lunch", user_id=USER)

    repo.list_reminder_recipients.assert_called_once_with(USER)


def test_nobody_needing_a_reminder_never_builds_the_sender(repo, monkeypatch):
    monkeypatch.setattr(mr, "now_in", lambda tz=None: datetime(2026, 11, 23, 11, 5, tzinfo=IST))
    repo.reply_window.return_value = None
    built = MagicMock()
    monkeypatch.setattr(mr, "Sender", built)

    mr.run(repo)

    built.assert_not_called()
