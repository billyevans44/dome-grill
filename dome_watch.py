"""Watch a SevenRooms venue for open tables and send a phone/email alert.

Standard library only. Configure with environment variables (see README.md).

  python dome_watch.py              run forever, checking every few minutes
  python dome_watch.py --once       do one check, print what was found, exit
  python dome_watch.py --test       send a test notification and exit
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime

VENUE = os.environ.get("VENUE", "grillroomuk")      # SevenRooms venue id of The Dome's Grill Room
DATE = os.environ.get("DATE", "2026-11-13")         # YYYY-MM-DD
PARTY_SIZE = int(os.environ.get("PARTY_SIZE", "2"))
EARLIEST = os.environ.get("EARLIEST", "11:00")      # only alert for slots in this window (24h)
LATEST = os.environ.get("LATEST", "23:30")
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "180"))
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")       # pick something long and unguessable
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")     # optional, sent by ntfy.sh for free
REALERT_MINUTES = int(os.environ.get("REALERT_MINUTES", "15"))

API = "https://www.sevenrooms.com/api-yoa/availability/widget/range"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# The range endpoint returns slots within +/- halo_size_interval * 15 min of time_slot,
# so two queries (14:00 and 20:00, +/- 4h) cover the whole day.
QUERY_TIMES = ["14:00", "20:00"]


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, text/html"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def booking_link():
    q = urllib.parse.urlencode({"date": DATE, "party_size": PARTY_SIZE})
    return f"https://www.sevenrooms.com/reservations/{VENUE}?{q}"


def fetch_day(time_slot):
    """Return the list of shifts for DATE, trying both date formats SevenRooms has used."""
    d = date.fromisoformat(DATE)
    last_error = None
    for start in (d.isoformat(), d.strftime("%m-%d-%Y")):
        params = {
            "venue": VENUE,
            "time_slot": time_slot,
            "party_size": PARTY_SIZE,
            "halo_size_interval": 16,
            "start_date": start,
            "num_days": 1,
            "channel": "SEVENROOMS_WIDGET",
        }
        try:
            body = json.loads(http_get(f"{API}?{urllib.parse.urlencode(params)}"))
        except (urllib.error.URLError, ValueError) as e:
            last_error = e
            continue
        availability = (body.get("data") or {}).get("availability") or {}
        if DATE in availability:
            return availability[DATE]
        last_error = RuntimeError(f"no {DATE} in response: {json.dumps(body)[:300]}")
    raise RuntimeError(f"availability lookup failed: {last_error}")


def slot_time(t):
    """'2026-11-13 19:30:00' -> '19:30'; falls back to parsing '7:30 PM'."""
    iso = t.get("time_iso") or ""
    if len(iso) >= 16:
        return iso[11:16]
    try:
        return datetime.strptime(t.get("time", ""), "%I:%M %p").strftime("%H:%M")
    except ValueError:
        return t.get("time", "?")


def open_slots():
    found = {}
    for qt in QUERY_TIMES:
        for shift in fetch_day(qt):
            for t in shift.get("times") or []:
                if t.get("type") != "book":   # "request"/missing type = not bookable online
                    continue
                hhmm = slot_time(t)
                if EARLIEST <= hhmm <= LATEST:
                    found[hhmm] = shift.get("name") or ""
    return dict(sorted(found.items()))


def notify(title, message, click=None, urgent=True):
    if not NTFY_TOPIC:
        log("NTFY_TOPIC not set, skipping notification")
        return
    headers = {"Title": title, "Priority": "urgent" if urgent else "default", "Tags": "fork_and_knife"}
    if click:
        headers["Click"] = click
        headers["Actions"] = f"view, Book now, {click}"
    if ALERT_EMAIL:
        headers["Email"] = ALERT_EMAIL
    req = urllib.request.Request(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode(), headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.URLError as e:
        log(f"notification failed: {e}")


def check_once():
    slots = open_slots()
    log(f"{VENUE} {DATE} x{PARTY_SIZE}: " + (", ".join(slots) if slots else "nothing available"))
    return slots


def run():
    last_alert = {}            # slot -> time we last alerted about it
    failures = 0
    notify("Dome watcher started", f"Watching {VENUE} on {DATE} for {PARTY_SIZE}.", urgent=False)
    while date.today() <= date.fromisoformat(DATE):
        try:
            slots = check_once()
            failures = 0
            now = time.time()
            due = [s for s in slots if now - last_alert.get(s, 0) > REALERT_MINUTES * 60]
            if due:
                summary = ", ".join(f"{s} ({slots[s]})" if slots[s] else s for s in slots)
                notify(f"TABLE OPEN {DATE}: {', '.join(due)}",
                       f"{PARTY_SIZE} people, {summary}. Tap to book - deposit needed.",
                       click=booking_link())
                for s in due:
                    last_alert[s] = now
        except Exception as e:  # keep watching through network blips
            failures += 1
            log(f"check failed ({failures}): {e}")
            if failures == 5:
                notify("Dome watcher is failing", f"5 checks in a row failed. Last error: {e}", urgent=False)
        time.sleep(INTERVAL + random.uniform(0, 30))
    log("date has passed, stopping")


def main():
    args = sys.argv[1:]
    if args[:1] == ["--test"]:
        notify("Dome watcher test", "If you can read this, alerts work.", click=booking_link())
        log("test notification sent")
    elif args[:1] == ["--once"]:
        check_once()
    else:
        run()


if __name__ == "__main__":
    main()
