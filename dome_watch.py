"""Watch a SevenRooms venue for open tables and send a phone/email alert.

Standard library only. Configure with environment variables (see README.md).

  python dome_watch.py              run forever, checking every few minutes
  python dome_watch.py --once       do one check, print what was found, exit
  python dome_watch.py --check      one check, alert if a table is open (for GitHub Actions)
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
# YYYY-MM-DD, comma-separated for several days (DATE is accepted as an alias)
DATES = [d.strip() for d in (os.environ.get("DATES") or os.environ.get("DATE") or "2026-11-13,2026-11-14")
         .split(",") if d.strip()]
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


def pretty(day):
    d = date.fromisoformat(day)
    return f"{d:%a} {d.day} {d:%b}"   # "Fri 13 Nov"


def upcoming():
    return [d for d in DATES if date.fromisoformat(d) >= date.today()]


def booking_link(day):
    q = urllib.parse.urlencode({"date": day, "party_size": PARTY_SIZE})
    return f"https://www.sevenrooms.com/reservations/{VENUE}?{q}"


def fetch_day(day, time_slot):
    """Return the list of shifts for day, trying both date formats SevenRooms has used."""
    d = date.fromisoformat(day)
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
        if day in availability:
            return availability[day]
        last_error = RuntimeError(f"no {day} in response: {json.dumps(body)[:300]}")
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


def open_slots(day):
    found = {}
    for qt in QUERY_TIMES:
        for shift in fetch_day(day, qt):
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
    try:
        post_ntfy(message, headers)
    except urllib.error.HTTPError as e:
        if "Email" not in headers:
            raise
        # Never let the email part (ntfy.sh refuses anonymous email) block the push
        log(f"email alert refused ({e.code}), sending push only")
        del headers["Email"]
        post_ntfy(message, headers)


def post_ntfy(message, headers):
    req = urllib.request.Request(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode(), headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        log(f"notification failed: {e.code} {e.read().decode(errors='replace')[:200]}")
        raise


def check_once(day):
    slots = open_slots(day)
    log(f"{VENUE} {day} x{PARTY_SIZE}: " + (", ".join(slots) if slots else "nothing available"))
    return slots


def alert(day, slots):
    summary = ", ".join(f"{s} ({slots[s]})" if slots[s] else s for s in slots)
    notify(f"TABLE OPEN {pretty(day)}: {', '.join(slots)}",
           f"{PARTY_SIZE} people, {pretty(day)}: {summary}. Tap to book - deposit needed.",
           click=booking_link(day))


def run():
    last_alert = {}            # (day, slot) -> time we last alerted about it
    failures = 0
    days = ", ".join(pretty(d) for d in DATES)
    notify("Dome watcher started", f"Watching {VENUE} on {days} for {PARTY_SIZE}.", urgent=False)
    while upcoming():
        try:
            for day in upcoming():
                slots = check_once(day)
                now = time.time()
                due = [s for s in slots if now - last_alert.get((day, s), 0) > REALERT_MINUTES * 60]
                if due:
                    alert(day, slots)
                    for s in due:
                        last_alert[(day, s)] = now
            failures = 0
        except Exception as e:  # keep watching through network blips
            failures += 1
            log(f"check failed ({failures}): {e}")
            if failures == 5:
                try:
                    notify("Dome watcher is failing", f"5 checks in a row failed. Last error: {e}", urgent=False)
                except urllib.error.URLError:
                    pass
        time.sleep(INTERVAL + random.uniform(0, 30))
    log("all dates have passed, stopping")


def main():
    args = sys.argv[1:]
    if args[:1] == ["--test"]:
        notify("Dome watcher test", "If you can read this, alerts work.", click=booking_link(DATES[0]))
        log("test notification sent")
    elif args[:1] == ["--once"]:
        for day in DATES:
            check_once(day)
    elif args[:1] == ["--check"]:
        if not upcoming():
            log("all dates have passed, nothing to do")
        errors = []
        for day in upcoming():   # one day failing shouldn't stop the others being checked
            try:
                slots = check_once(day)
                if slots:
                    alert(day, slots)
            except Exception as e:
                log(f"{day} failed: {e}")
                errors.append(e)
        if errors:
            sys.exit(1)          # so the Actions run shows red
    else:
        run()


if __name__ == "__main__":
    main()
