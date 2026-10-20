# Ice Watch alerts — Fordham Fantasy 16

Push alerts for the whole league, from a free GitHub Actions job that checks ESPN every 5 minutes during games.

- **Thin ice**: a starter is at 0 or below when his game moves to the 4th quarter.
- **ICED**: a starter's game ends and he finished at 0 or below.

QB, RB, WR, TE, FLEX and K starters count. D/ST, bench and IR never count. Each alert goes out once per player per week.

## For league members: get the alerts (1 minute)

1. Install the free **ntfy** app (App Store or Google Play).
2. Tap **+** (Subscribe to topic) and enter: `fordham16-icewatch-4cd9a2`
3. Leave the server as the default (ntfy.sh) and tap Subscribe.

No account is needed. Anyone with the topic name gets the alerts, so keep it inside the league.

## One-time setup (Patrick, about 10 minutes)

1. Sign in at github.com (create a free account if needed).
2. Click **+** at the top right, then **New repository**. Name it `ice-watch-alerts`, set it to **Public** (public repos get unlimited free run time, and nothing in here is private), then **Create repository**.
3. On the new repo page, click **uploading an existing file**. Drag in `icewatch_alerts.py`, `state.json` and `README.md`, then **Commit changes**.
4. Add the schedule file: **Add file → Create new file**, type the name `.github/workflows/ice-watch.yml` (the slashes create the folders), paste in the contents of `ice-watch.yml`, then **Commit changes**.
5. **Settings → Secrets and variables → Actions → Variables tab → New repository variable**:
   - `NTFY_TOPIC` = `fordham16-icewatch-4cd9a2`
   - `TRACKER_URL` = the shared link to the Ice Watch tracker (optional; tapping an alert opens it)
6. **Actions** tab: if asked, click to enable workflows. Open **Ice Watch alerts → Run workflow** to run it once by hand. It should finish green.

## Good to know

- GitHub sometimes starts scheduled runs late when it's busy, so an alert can land 5 to 15 minutes after the moment.
- GitHub pauses schedules in a public repo after 60 days with no commits. The job commits whenever it sends an alert, so this only matters in a long stretch with no Ices.
- The league must stay viewable to the public on ESPN, or the checks stop working.
