# Dome Grill Room table watcher

Checks SevenRooms every ~3 minutes for a table for 2 on Fri 13 Nov 2026 and
pushes an alert to your phone (and optionally email) the moment one appears.
Tap the alert, it opens the booking page, you pay the deposit. Free apart from
hosting.

## 1. Phone alerts (2 min, free)

1. Install **ntfy** on your phone (App Store / Google Play).
2. Tap **+**, subscribe to a topic with a long random name, e.g.
   `dome-grill-k7x2p9q4`. Anyone who knows the name can read it, so don't use
   something guessable.
3. In the app's notification settings for that topic, allow "urgent" alerts to
   make sound / bypass Do Not Disturb.

## 2. Run free on GitHub Actions (no installs, no server)

`.github/workflows/watch.yml` runs one check every 5 minutes (GitHub can run
scheduled jobs a few minutes late when busy). Free for public repos.

1. Repo → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**: name `NTFY_TOPIC`, value your topic.
2. **Actions** tab → enable workflows if asked → **Watch for a table** →
   **Run workflow** to check it once now. A green tick means it worked; open the
   run to see `... nothing available`.

To stop it: Actions → Watch for a table → **...** → **Disable workflow**.
If you also run it on Railway, disable one of them to avoid double alerts.

## 2a. Run on Railway (recommended — keeps going when your PC is off)

Install the CLI (needs Node) and deploy from this folder in PowerShell:

```powershell
npm i -g @railway/cli
railway login
railway init            # create a new project, e.g. "dome-watch"
railway up              # uploads this folder; first run will error until vars are set
railway variables --set "NTFY_TOPIC=dome-grill-k7x2p9q4" --set "ALERT_EMAIL=you@example.com"
railway up
railway logs            # should show "... nothing available" every ~3 min
```

Or with no installs: put these files in a GitHub repo, then in the Railway
dashboard New Project → Deploy from GitHub repo → Variables tab → add the variables.

If the logs show `403` errors, SevenRooms is blocking Railway's data-centre IP —
use 2b instead.

## 2b. Run on Windows

Install Python from python.org (tick "Add to PATH"), then in PowerShell in this folder:

```powershell
$env:NTFY_TOPIC="dome-grill-k7x2p9q4"
python dome_watch.py --test     # you should get a phone notification
python dome_watch.py --once     # one check, prints what it sees
python dome_watch.py            # leave this window open
```

Stop the PC sleeping (Settings → System → Power → Sleep: Never) while it runs.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `VENUE` | `grillroomuk` | SevenRooms venue id (The Dome Grill Room) |
| `NTFY_TOPIC` | — | your ntfy topic name |
| `ALERT_EMAIL` | — | email alerts via ntfy - needs an ntfy.sh account now; ignored (push still sent) if refused |
| `DATE` | `2026-11-13` | date to watch |
| `PARTY_SIZE` | `2` | guests |
| `EARLIEST` / `LATEST` | `11:00` / `23:30` | only alert for slots in this window |
| `INTERVAL_SECONDS` | `180` | gap between checks (+ up to 30s random) |
| `REALERT_MINUTES` | `15` | re-alert about a still-open slot after this long |

It sends a "watcher started" message on launch, a warning if 5 checks in a row
fail, and stops by itself after 13 Nov. Please keep the interval at a few
minutes — hammering the site gets IPs blocked.
