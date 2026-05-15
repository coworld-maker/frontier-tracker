#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from notify import send_notifications
from scraper import GoWildFlight, scrape_go_wild_flights

CONFIG_PATH = Path("config.json")
STATE_PATH = Path("data/seen-flights.json")

# Re-alert for the same flight after 48 hours
RESEEN_TTL_SECONDS = 48 * 60 * 60


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print("config.json not found. Copy config.example.json to config.json and fill it in.")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text())


def load_state() -> dict[str, float]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_state(state: dict[str, float]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def filter_new(flights: list[GoWildFlight], state: dict[str, float]) -> list[GoWildFlight]:
    now = datetime.now(tz=timezone.utc).timestamp()
    return [f for f in flights if now - state.get(f.key(), 0) > RESEEN_TTL_SECONDS]


def update_state(
    new_flights: list[GoWildFlight], state: dict[str, float]
) -> dict[str, float]:
    now = datetime.now(tz=timezone.utc).timestamp()
    updated = {k: v for k, v in state.items() if now - v <= RESEEN_TTL_SECONDS * 3}
    for f in new_flights:
        updated[f.key()] = now
    return updated


def main() -> None:
    print("Frontier Go Wild Tracker starting…")
    config = load_config()
    state = load_state()

    timezone_name = config.get("timezone", "America/Chicago")
    mode = "all Frontier routes" if config.get("all_routes") else f"{len(config.get('routes', []))} route(s)"
    print(f"Mode: {mode}")

    try:
        all_flights = scrape_go_wild_flights(config, timezone_name)
    except Exception as e:
        print(f"Scraper error: {e}")
        sys.exit(1)

    print(f"Found {len(all_flights)} Go Wild flight(s) total.")

    new_flights = filter_new(all_flights, state)
    print(f"{len(new_flights)} new (not seen in last 48h).")

    if new_flights:
        print("Sending notifications…")
        send_notifications(new_flights, config)

    save_state(update_state(new_flights, state))
    print("State saved." if new_flights else "No new flights to report.")
    print("Done.")


if __name__ == "__main__":
    main()
