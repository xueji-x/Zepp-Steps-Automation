"""Offline checks: no Zepp account or network calls required."""
from walking import daily_plan, due_steps, MAX_INCREMENT


for day in range(1000):
    plan = daily_plan(f"test-day-{day}", "test-account")
    assert plan == daily_plan(f"test-day-{day}", "test-account")
    assert 8000 < sum(plan) < 15000
    assert all(0 <= value <= MAX_INCREMENT for value in plan)
    previous, last_slot = 0, -1
    for minute in range(1440):
        steps, slot = due_steps(plan, minute, previous, last_slot)
        assert 0 <= steps - previous <= MAX_INCREMENT
        if minute < 480 or minute >= 1260:
            assert steps == previous
        previous, last_slot = steps, slot
    assert previous == sum(plan)

plan = daily_plan("2026-10-26", "test-account")
assert due_steps(plan, 1255, 0, -1)[0] <= MAX_INCREMENT  # late start: no catch-up jump
assert due_steps(plan, 600, 500, 24) == (500, 24)  # repeated execution
assert due_steps(plan, 590, 500, 24) == (500, 24)  # clock moved backward

# Verify that only successful uploads advance persisted progress.
from datetime import datetime
import json
from pathlib import Path
import tempfile
import types
from unittest.mock import patch
import walking

class Clock(datetime):
    value = datetime(2026, 10, 26, 8, 0, tzinfo=walking.TZ)

    @classmethod
    def now(cls, tz=None):
        return cls.value

uploads = []
api = types.SimpleNamespace(login=lambda *args: ("test-token", "test-id"),
                            get_app_token=lambda token: "test-app-token",
                            change_steps=lambda *args: uploads.append(int(args[-1])) or True)
with tempfile.TemporaryDirectory() as directory:
    state_file = Path(directory) / "progress.json"
    with patch.dict("os.environ", {"ACCOUNT": "test-account", "PASSWORD": "test-password",
                                   "STATE_FILE": str(state_file)}), \
         patch.dict("sys.modules", {"main": api}), patch.object(walking, "datetime", Clock):
        walking.run_tick()
        first = state_file.read_text()
        walking.run_tick()
        assert len(uploads) == 1 and state_file.read_text() == first
        Clock.value = Clock.value.replace(minute=5)
        api.change_steps = lambda *args: False
        try:
            walking.run_tick()
            raise AssertionError("Failed upload was not reported")
        except RuntimeError:
            pass
        assert state_file.read_text() == first
        api.change_steps = lambda *args: uploads.append(int(args[-1])) or True
        walking.run_tick()
        assert len(uploads) == 2 and 0 < uploads[-1] - uploads[0] <= MAX_INCREMENT
        Clock.value = Clock.value.replace(day=27, minute=0)
        walking.run_tick()
        assert 0 < uploads[-1] <= MAX_INCREMENT
        assert json.loads(state_file.read_text())["day"] == "2026-10-27"
        Clock.value = Clock.value.replace(hour=23)
        walking.run_tick()
        assert len(uploads) == 3
        assert "test-password" not in state_file.read_text()
        Clock.value = Clock.value.replace(hour=19, minute=25)
        walking.run_tick(catch_up_date="2026-10-27")
        target = sum(walking.daily_plan("2026-10-27", "test-account"))
        assert uploads[-1] == target and 8000 < target < 15000
        assert json.loads(state_file.read_text())["slot"] == walking.SLOTS - 1
        count = len(uploads)
        walking.run_tick(catch_up_date="2026-10-27")
        walking.run_tick()
        assert len(uploads) == count
        try:
            walking.run_tick(catch_up_date="2026-10-26")
            raise AssertionError("Wrong-date catch-up was accepted")
        except ValueError:
            pass
        Clock.value = Clock.value.replace(day=28, hour=8, minute=0)
        walking.run_tick()
        assert len(uploads) == count + 1 and 0 < uploads[-1] <= MAX_INCREMENT
print("PASS: 1000 daily plans; bounded progression; night/repeat skip; failed-upload retry; restart and day rollover")
