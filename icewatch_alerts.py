"""Ice Watch for Fordham Fantasy 16: live alerts + website data.

Runs every 5 minutes during NFL games (GitHub Actions). Each run:
  1. Updates data.json (the season-long Ice log the website reads).
  2. Sends a push to the league's ntfy topic when
       THIN ICE: a starter is at 0 or below and his game has reached the 4th quarter
       ICED:     a starter's game is final and he finished at 0 or below
       OFF THIN ICE: a starter who got a thin-ice alert gets above 0
Counts QB, RB, WR, TE, FLEX and K starters. D/ST, bench and IR never count.
Each alert goes out once per player per week (remembered in state.json).
"""
import json, os, urllib.request
from datetime import datetime, timezone

LEAGUE_ID = os.environ.get("LEAGUE_ID", "634873482")
SEASON = os.environ.get("SEASON", "2026")
TOPIC = os.environ.get("NTFY_TOPIC", "")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
STATE_FILE = os.environ.get("STATE_FILE", "state.json")
DATA_FILE = os.environ.get("DATA_FILE", "data.json")
TRACKER_URL = os.environ.get("TRACKER_URL", "")

LEAGUE = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/segments/0/leagues/{LEAGUE_ID}"
SB = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={w}&dates=" + SEASON
SLOTS = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 17: "K"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def load(path, default):
    try:
        return json.load(open(path))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def push(title, body, tags):
    if DRY_RUN or not TOPIC:
        print(f"[dry run] {title}: {body}")
        return
    headers = {"Title": title, "Tags": tags}
    if TRACKER_URL:
        headers["Click"] = TRACKER_URL
    req = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=body.encode(), method="POST", headers=headers)
    urllib.request.urlopen(req, timeout=30).read()
    print(f"sent {title}: {body}")


def cap(name):
    return " ".join(p[:1].upper() + p[1:] for p in name.split())


def main():
    state = load(STATE_FILE, {"sent": []})
    sent = set(state["sent"])
    data = load(DATA_FILE, {"ice": [], "teams": [], "live": []})

    info = get(LEAGUE + "?view=mStatus&view=mTeam")
    latest = info["status"]["latestScoringPeriod"]
    members = {m["id"]: cap(f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()) for m in info.get("members", [])}
    teams = [{"teamId": t["id"], "team": (t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}").strip(),
              "owner": " & ".join(members.get(o, "") for o in t.get("owners", []))} for t in info["teams"]]
    tmap = {t["teamId"]: t for t in teams}

    weeks = [w for w in (latest - 1, latest) if w >= 1]  # last week too, for stat corrections
    fresh, live = [], []
    for w in weeks:
        games = {}
        for ev in get(SB.format(w=w)).get("events", []):
            st = ev["status"]
            g = {"final": st["type"]["completed"], "period": st.get("period", 0), "id": str(ev["id"]),
                 "name": ev["shortName"], "clock": st["type"].get("shortDetail", "")}
            for c in ev["competitions"][0]["competitors"]:
                games[int(c["team"]["id"])] = {**g, "abbr": c["team"]["abbreviation"]}
        for t in get(LEAGUE + f"?view=mRoster&scoringPeriodId={w}")["teams"]:
            for e in t["roster"]["entries"]:
                slot = e["lineupSlotId"]
                if slot not in SLOTS:
                    continue
                p = e["playerPoolEntry"]["player"]
                g = games.get(p.get("proTeamId"))
                if not g or (not g["final"] and g["period"] < 1):
                    continue  # bye week or game not started
                s = next((s for s in p.get("stats", []) if s.get("scoringPeriodId") == w
                          and s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1), None)
                pts = round(s["appliedTotal"], 2) if s else 0.0
                tm = tmap[t["id"]]
                if pts > 0:
                    # Was flagged on thin ice, now above 0: send an all-clear once
                    thin, safe = f"thin-{w}-{t['id']}-{p['id']}", f"safe-{w}-{t['id']}-{p['id']}"
                    if w == latest and thin in sent and safe not in sent:
                        push("Off thin ice", f"{p['fullName']} ({SLOTS[slot]}, {tm['team']}) is off Ice Watch with "
                             f"{pts:.2f} pts. {g['name']}, {g['clock']}", "white_check_mark")
                        sent.add(safe)
                    continue
                row = {"id": f"{w}-{t['id']}-{p['id']}", "week": w, "teamId": t["id"], "team": tm["team"],
                       "owner": tm["owner"], "player": p["fullName"], "slot": SLOTS[slot], "nfl": g["abbr"],
                       "points": float(pts), "gameId": g["id"]}
                who = f"{p['fullName']} ({SLOTS[slot]}, {tm['team']})"
                if g["final"]:
                    row["status"] = "Played" if s and "210" in s.get("stats", {}) else "Inactive"
                    fresh.append(row)
                    key = f"iced-{w}-{t['id']}-{p['id']}"
                    if w == latest and key not in sent:
                        push("ICED", f"{who} finished with {pts:.2f} pts. {g['name']}, Week {w}", "tumbler_glass")
                        sent.add(key)
                elif w == latest:
                    row.update({"game": g["name"], "clock": g["clock"], "quarter": g["period"]})
                    live.append(row)
                    key = f"thin-{w}-{t['id']}-{p['id']}"
                    if g["period"] >= 4 and key not in sent:
                        push("Thin ice", f"{who} has {pts:.2f} pts heading into the 4th. {g['name']}, {g['clock']}", "warning")
                        sent.add(key)

    ice = [r for r in data.get("ice", []) if r["week"] not in weeks] + fresh
    ice.sort(key=lambda r: (r["week"], r["id"]))
    live.sort(key=lambda r: (-r["quarter"], r["points"], r["player"]))
    new_data = {"week": latest, "teams": teams, "ice": ice, "live": live}
    old_cmp = {k: data.get(k) for k in new_data}
    if new_data != old_cmp:
        new_data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        json.dump(new_data, open(DATA_FILE, "w"), indent=1)
        print("data.json updated")

    keep = {str(latest), str(latest - 1)}
    pruned = sorted(k for k in sent if k.split("-")[1] in keep)
    if pruned != sorted(state["sent"]):
        json.dump({"sent": pruned}, open(STATE_FILE, "w"), indent=1)
    print(f"Week {latest}: {len(ice)} Ices this season, {len(live)} on thin ice right now.")


if __name__ == "__main__":
    main()
