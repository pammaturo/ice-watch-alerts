"""Ice Watch live alerts for Fordham Fantasy 16.

Runs every few minutes during NFL games (GitHub Actions). Sends a push to the
league's ntfy topic when:
  - THIN ICE: a starter is at 0 or below and his game has reached the 4th quarter
    (i.e. the 3rd quarter just ended)
  - ICED: a starter's game is final and he finished at 0 or below
Counts QB, RB, WR, TE, FLEX and K starters. D/ST, bench and IR never count.
Each alert is sent once per player per week (remembered in state.json).
"""
import json, os, urllib.request

LEAGUE_ID = os.environ.get("LEAGUE_ID", "634873482")
SEASON = os.environ.get("SEASON", "2026")
TOPIC = os.environ.get("NTFY_TOPIC", "")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
TRACKER_URL = os.environ.get("TRACKER_URL", "")

LEAGUE = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"
SB = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={w}&dates=" + SEASON
SLOTS = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 17: "K"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def push(title, body, tags):
    if DRY_RUN or not TOPIC:
        print(f"[dry run] {title}: {body}")
        return
    req = urllib.request.Request(
        f"https://ntfy.sh/{TOPIC}", data=body.encode(), method="POST",
        headers={"Title": title, "Tags": tags, **({"Click": TRACKER_URL} if TRACKER_URL else {})})
    urllib.request.urlopen(req, timeout=30).read()
    print(f"sent {title}: {body}")


def main():
    try:
        state = json.load(open(STATE_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"sent": []}
    sent = set(state["sent"])

    info = get(LEAGUE + "?view=mStatus&view=mTeam")
    w = info["status"]["latestScoringPeriod"]
    teams = {t["id"]: (t.get("name") or "").strip() for t in info["teams"]}

    games = {}
    for ev in get(SB.format(w=w)).get("events", []):
        st = ev["status"]
        info_g = {"final": st["type"]["completed"], "period": st.get("period", 0),
                  "name": ev["shortName"], "clock": st["type"].get("shortDetail", "")}
        for c in ev["competitions"][0]["competitors"]:
            games[int(c["team"]["id"])] = info_g
    if not any(g["period"] >= 4 or g["final"] for g in games.values()):
        print("No games in the 4th quarter or final yet.")
        return

    new_sent = False
    for t in get(LEAGUE + f"?view=mRoster&scoringPeriodId={w}")["teams"]:
        for e in t["roster"]["entries"]:
            slot = e["lineupSlotId"]
            if slot not in SLOTS:
                continue
            p = e["playerPoolEntry"]["player"]
            g = games.get(p.get("proTeamId"))
            if not g:
                continue  # bye week
            s = next((s for s in p.get("stats", []) if s.get("scoringPeriodId") == w
                      and s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1), None)
            pts = round(s["appliedTotal"], 2) if s else 0.0
            if pts > 0:
                continue
            who = f"{p['fullName']} ({SLOTS[slot]}, {teams[t['id']]})"
            if g["final"]:
                key = f"iced-{w}-{t['id']}-{p['id']}"
                if key not in sent:
                    push("ICED", f"{who} finished with {pts:.2f} pts. {g['name']}, Week {w}", "tumbler_glass")
                    sent.add(key); new_sent = True
            elif g["period"] >= 4:
                key = f"thin-{w}-{t['id']}-{p['id']}"
                if key not in sent:
                    push("Thin ice", f"{who} has {pts:.2f} pts heading into the 4th. {g['name']}, {g['clock']}", "warning")
                    sent.add(key); new_sent = True

    # keep only this week and last week so the file stays small
    keep = {str(w), str(w - 1)}
    state["sent"] = sorted(k for k in sent if k.split("-")[1] in keep)
    if new_sent or len(state["sent"]) != len(sent):
        json.dump(state, open(STATE_FILE, "w"), indent=1)
    print(f"Week {w}: done.")


if __name__ == "__main__":
    main()
