"""A bounded daytime schedule; all clock calculations use UTC+8."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import random

TZ = timezone(timedelta(hours=8))
SLOTS = 156  # 08:00 through 20:55, every five minutes
MAX_INCREMENT = 180


def daily_plan(day, account):
    seed = hashlib.sha256(f"{day}:{account}".encode()).digest()
    rng = random.Random(seed)
    target = rng.randint(8001, 14999)
    weights = []
    for slot in range(SLOTS):
        hour = 8 + slot / 12
        # Morning, lunch and evening carry more activity, with quiet intervals.
        busy = 1.25 if hour < 10 or 12 <= hour < 14 or 17 <= hour < 20 else 0.7
        weights.append(busy * rng.uniform(0.25, 1.5))
    increments = [min(MAX_INCREMENT, int(target * w / sum(weights))) for w in weights]
    while sum(increments) < target:
        available = [i for i, value in enumerate(increments) if value < MAX_INCREMENT]
        rng.shuffle(available)
        for i in available[:target - sum(increments)]:
            increments[i] += 1
    return increments


def due_steps(plan, minute, previous, last_slot):
    if not 8 * 60 <= minute < 21 * 60:
        return previous, last_slot
    slot = (minute - 8 * 60) // 5
    if slot <= last_slot:
        return previous, last_slot
    return min(sum(plan[:slot + 1]), previous + MAX_INCREMENT), slot


def run_tick(now=None):
    now = now or datetime.now(TZ)
    minute = now.hour * 60 + now.minute
    if not 8 * 60 <= minute < 21 * 60:
        print("Outside 08:00-21:00 UTC+8; skipped.")
        return
    account = os.environ.get("ACCOUNT", "")
    password = os.environ.get("PASSWORD", "")
    if not account or not password:
        print("Zepp ACCOUNT / PASSWORD not configured; skipped.")
        return
    day = now.date().isoformat()
    path = Path(os.environ.get("STATE_FILE", "state/progress.json"))
    key = hashlib.sha256(account.encode()).hexdigest()
    state = json.loads(path.read_text()) if path.exists() else {}
    if state.get("day") != day or state.get("account") != key:
        state = {"day": day, "account": key, "steps": 0, "slot": -1}
    steps, slot = due_steps(daily_plan(day, account), minute, state["steps"], state["slot"])
    if steps <= state["steps"]:
        print("No new increment; skipped.")
        return
    from main import login, get_app_token, change_steps
    login_token, user_id = login(account, password)
    if not login_token:
        raise RuntimeError("Zepp login failed.")
    app_token = get_app_token(login_token)
    if not app_token:
        raise RuntimeError("Could not obtain app token.")
    # Do not send yesterday's data if a network request crosses midnight.
    current = datetime.now(TZ)
    if current.date() != now.date() or not 8 <= current.hour < 21:
        return
    if not change_steps(account, user_id, app_token, str(steps)):
        raise RuntimeError("Zepp upload failed; progress was not advanced.")
    state.update(steps=steps, slot=slot)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(path)
    print(f"Saved progress: {day}, {steps} steps.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Print today's plan without network access")
    parser.add_argument("--check-login", action="store_true", help="Verify Zepp credentials without uploading steps")
    args = parser.parse_args()
    if args.preview:
        now = datetime.now(TZ)
        plan = daily_plan(now.date().isoformat(), os.environ.get("ACCOUNT", "preview"))
        print(json.dumps({"date": str(now.date()), "timezone": "UTC+8", "target": sum(plan),
                          "maximum_increment": max(plan), "increments": plan}, indent=2))
    else:
        import requests
        try:
            if args.check_login:
                from main import login, get_app_token
                account, password = os.environ.get("ACCOUNT"), os.environ.get("PASSWORD")
                if not account or not password:
                    raise RuntimeError("Missing Zepp credentials.")
                token, _ = login(account, password)
                if not token or not get_app_token(token):
                    raise RuntimeError("Zepp credential check failed.")
                print("Zepp credential check succeeded; no steps uploaded.")
            else:
                run_tick()
        except requests.RequestException as error:
            # Exception URLs can contain tokens or account identifiers.
            print(f"Zepp request failed: {type(error).__name__}")
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
