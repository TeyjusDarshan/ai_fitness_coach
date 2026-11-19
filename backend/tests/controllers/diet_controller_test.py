"""Tests for the diet endpoints (diet_controller.py): who may see and edit
what, and that a recording starts a meal log. The pipeline and the edit
logic are tested in diet/test."""
import io
from unittest.mock import MagicMock

import pytest

from diet.test.fakes import FakeRepo

ADMIN = {"X-Admin-Key": "test-admin-key"}


@pytest.fixture
def ctl(app_module, monkeypatch):
    """The controller with an in-memory repository holding one ready log of
    usr_1's: 2 karandi of rice."""
    import backend.controllers.diet_controller as controller

    repo = FakeRepo()
    repo.enabled = {"usr_1", "usr_2"}
    log = repo.add_log("usr_1", status="ready")
    repo.add_item(log, "Cooked Rice", {1: 42, 2: 1.2}, meal="lunch", quote="rendu karandi sadam",
                  quantity=2, unit="karandi", portion_grams=120)
    repo.get_meal_log_detail = lambda log_id: (
        {**repo.logs[log_id], "meal_log_items": repo.log_items(log_id)} if log_id in repo.logs else None
    )
    repo.list_meal_logs = lambda user_id, start, end: [
        repo.get_meal_log_detail(i) for i, row in repo.logs.items()
        if row["user_id"] == user_id and row["status"] != "discarded"
    ]
    repo.create_meal_log = lambda user_id, logged_for: repo.logs[repo.add_log(user_id, logged_for=logged_for.isoformat())]
    repo.get_targets = lambda user_id: None
    repo.set_targets = MagicMock(return_value=True)

    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.setattr(controller, "diet_repo", repo)
    monkeypatch.setattr(controller, "feedback_storage", MagicMock())
    monkeypatch.setattr(controller.kafka_producer, "send_meal_log_event", MagicMock(return_value=True))
    monkeypatch.setattr(controller.plan_repo, "user_exists", MagicMock(return_value=True))
    controller.repo = repo
    return controller


def _recording(content_type="audio/webm", data=b"voice"):
    return {"audio": (io.BytesIO(data), "meal.webm", content_type)}


def test_recording_starts_a_log_and_publishes_it(ctl, sign_in):
    response = sign_in("usr_1").post("/api/meal-logs", data={**_recording(), "day": "yesterday"})

    assert response.status_code == 201
    log = ctl.repo.logs[response.get_json()["id"]]
    assert (log["user_id"], log["status"], log["audio_path"]) == ("usr_1", "processing", f"meal_{log['id']}.webm")
    assert log["logged_for"] < str(ctl.app_today())
    ctl.kafka_producer.send_meal_log_event.assert_called_once_with(log["id"])


def test_recording_is_refused_when_unusable_or_signed_out(ctl, sign_in, app_module):
    client = sign_in("usr_1")
    assert client.post("/api/meal-logs", data={}).status_code == 400
    assert client.post("/api/meal-logs", data=_recording("video/mp4")).status_code == 415
    assert client.post("/api/meal-logs", data={**_recording(), "day": "tomorrow"}).status_code == 400
    assert app_module.app.test_client().post("/api/meal-logs", data=_recording()).status_code == 401


def test_log_fails_when_the_event_cannot_be_published(ctl, sign_in):
    ctl.kafka_producer.send_meal_log_event.return_value = False

    response = sign_in("usr_1").post("/api/meal-logs", data=_recording())

    assert response.status_code == 502
    assert ctl.repo.logs[2]["status"] == "failed"


def test_she_sees_her_log_and_item_with_ingredients(ctl, sign_in):
    client = sign_in("usr_1")

    log = client.get("/api/meal-logs/1").get_json()
    item = client.get("/api/meal-log-items/1").get_json()

    assert (log["status"], log["items"][0]["name"], log["items"][0]["protein_g"]) == ("ready", "Cooked Rice", 2.9)
    assert "nutrients" not in log["items"][0] and "transcript" not in log
    assert [(i["name"], i["grams"]) for i in item["ingredients"]] == [("Raw white rice", 42), ("Sesame (gingelly) oil", 1.2)]


@pytest.mark.parametrize("method, path, body", [
    ("get", "/api/meal-logs/1", None),
    ("post", "/api/meal-logs/1/confirm", None),
    ("delete", "/api/meal-logs/1", None),
    ("get", "/api/meal-log-items/1", None),
    ("patch", "/api/meal-log-items/1", {"quantity": 1}),
    ("delete", "/api/meal-log-items/1", None),
    ("patch", "/api/meal-log-items/1/ingredients/2", {"grams": 0}),
    ("post", "/api/meal-log-items/1/reset", None),
])
def test_another_client_cannot_see_or_change_her_log(ctl, sign_in, method, path, body):
    response = getattr(sign_in("usr_2"), method)(path, json=body)

    assert response.status_code == 404
    assert 1 in ctl.repo.logs and 1 in ctl.repo.items
    assert {r["grams"] for r in ctl.repo.items[1]["meal_log_item_ingredients"]} == {42, 1.2}


def test_edits_apply_and_come_back_in_the_response(ctl, sign_in):
    client = sign_in("usr_1")

    smaller = client.patch("/api/meal-log-items/1", json={"quantity": 1}).get_json()
    no_oil = client.patch("/api/meal-log-items/1/ingredients/2", json={"grams": 0}).get_json()

    assert (smaller["quantity"], smaller["grams"]) == (1, 60)
    assert no_oil["edited"] and no_oil["ingredients"][1]["grams"] == 0
    assert client.patch("/api/meal-log-items/1", json={"quantity": "2"}).status_code == 400
    assert client.patch("/api/meal-log-items/1/ingredients/2", json={"grams": -1}).status_code == 400

    reset = client.post("/api/meal-log-items/1/reset").get_json()
    assert [i["grams"] for i in reset["ingredients"]] == [21, 0.6]


def test_confirm_and_delete(ctl, sign_in):
    client = sign_in("usr_1")

    assert client.post("/api/meal-logs/1/confirm").get_json()["status"] == "confirmed"
    assert ctl.repo.logs[1]["status"] == "confirmed"
    assert client.delete("/api/meal-logs/1").status_code == 200
    # Kept as discarded (it still counts in the Costs tab), gone for her.
    assert (ctl.repo.logs[1]["status"], ctl.repo.logs[1]["audio_path"]) == ("discarded", None)
    ctl.feedback_storage().remove.assert_called_once_with("meal_1.webm")
    assert client.get("/api/meal-logs/1").status_code == 404
    assert client.get("/api/users/usr_1/diet").get_json()["logs"] == []


def test_day_view_is_her_own_only(ctl, sign_in):
    client = sign_in("usr_1")

    day = client.get("/api/users/usr_1/diet").get_json()

    assert day["totals"] == {"energy_kcal": 158, "protein_g": 2.9, "fibre_g": 0.4, "carbs_g": 32.8, "fat_g": 1.4}
    assert day["targets"] == {"energy_kcal": 1800, "protein_g": 50, "fibre_g": 25, "carbs_g": 225, "fat_g": 60}
    assert client.get("/api/users/usr_2/diet").status_code == 403
    assert client.get("/api/users/usr_1/diet?date=nope").status_code == 400


def test_coach_view_has_every_nutrient_and_needs_the_admin_key(ctl, app_module):
    client = app_module.app.test_client()

    assert client.get("/api/admin/users/usr_1/diet").status_code == 401
    body = client.get("/api/admin/users/usr_1/diet", headers=ADMIN).get_json()

    day = body["days"][0]
    assert day["totals"]["fat_g"] == 1.4 and "calcium_mg" in day["totals"]
    item = day["logs"][0]["items"][0]
    assert item["quote"] == "rendu karandi sadam" and item["ingredients"][0]["name"] == "Raw white rice"


def test_coach_sets_targets(ctl, app_module):
    client = app_module.app.test_client()

    response = client.patch("/api/admin/users/usr_1/nutrition-targets",
                            json={"protein_g": 65, "energy_kcal": 1600}, headers=ADMIN)

    assert response.get_json()["targets"] == {
        "energy_kcal": 1600, "protein_g": 65, "fibre_g": 25, "carbs_g": 225, "fat_g": 60,
    }
    ctl.repo.set_targets.assert_called_once_with("usr_1", {"energy_kcal": 1600, "protein_g": 65})
    for bad in ({"protein_g": 0}, {"energy_kcal": 200}, {"fat_g": "60"}):
        assert client.patch("/api/admin/users/usr_1/nutrition-targets", json=bad, headers=ADMIN).status_code == 400


def test_recent_days_are_her_own_and_include_empty_days(ctl, sign_in):
    ctl.repo.logs[1]["logged_for"] = str(ctl.app_today())
    client = sign_in("usr_1")

    body = client.get("/api/users/usr_1/diet/days").get_json()

    assert len(body["days"]) == 10 and body["targets"]["energy_kcal"] == 1800
    today, yesterday = body["days"][:2]
    assert (today["date"], today["dishes"], today["totals"]["protein_g"]) == (str(ctl.app_today()), 1, 2.9)
    assert (yesterday["dishes"], yesterday["totals"]["energy_kcal"]) == (0, 0)
    assert len(client.get("/api/users/usr_1/diet/days?days=3").get_json()["days"]) == 3
    assert client.get("/api/users/usr_2/diet/days").status_code == 403
    assert client.get("/api/users/usr_1/diet/days?days=x").status_code == 400


@pytest.mark.parametrize("method, path, body", [
    ("post", "/api/meal-logs", None),
    ("get", "/api/meal-logs/1", None),
    ("post", "/api/meal-logs/1/confirm", None),
    ("delete", "/api/meal-logs/1", None),
    ("get", "/api/meal-log-items/1", None),
    ("patch", "/api/meal-log-items/1", {"quantity": 1}),
    ("delete", "/api/meal-log-items/1", None),
    ("patch", "/api/meal-log-items/1/ingredients/2", {"grams": 0}),
    ("post", "/api/meal-log-items/1/reset", None),
    ("get", "/api/users/usr_1/diet", None),
    ("get", "/api/users/usr_1/diet/days", None),
])
def test_everything_is_refused_until_the_coach_switches_it_on(ctl, sign_in, method, path, body):
    ctl.repo.enabled.clear()                       # the default: off

    response = getattr(sign_in("usr_1"), method)(path, json=body)

    assert response.status_code == 403 and response.get_json()["diet_disabled"] is True
    assert 1 in ctl.repo.logs and 1 in ctl.repo.items and len(ctl.repo.logs) == 1
    ctl.kafka_producer.send_meal_log_event.assert_not_called()


def test_coach_switches_diet_tracking_on_and_off(ctl, sign_in, app_module):
    ctl.repo.enabled.clear()
    admin = app_module.app.test_client()
    path = "/api/admin/users/usr_1/diet-tracking"

    assert admin.patch(path, json={"enabled": True}).status_code == 401
    assert admin.patch(path, json={"enabled": "yes"}, headers=ADMIN).status_code == 400
    assert admin.patch(path, json={"enabled": True}, headers=ADMIN).get_json() == {"user_id": "usr_1", "diet_enabled": True}
    assert sign_in("usr_1").get("/api/meal-logs/1").status_code == 200

    admin.patch(path, json={"enabled": False}, headers=ADMIN)
    assert sign_in("usr_1").get("/api/meal-logs/1").status_code == 403
    # What she logged is kept, and the coach can still see it.
    assert admin.get("/api/admin/users/usr_1/diet", headers=ADMIN).get_json()["days"][0]["logs"]
