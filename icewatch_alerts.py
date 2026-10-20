"""Ice Watch for Fordham Fantasy 16: live alerts + website data.

Runs every 5 minutes during NFL games (GitHub Actions). Each run:
  1. Updates data.json (the season-long Ice log the website reads).
  2. Sends a push to the league's ntfy topic when
       THIN ICE: a starter is at 0 or below and his game has reached the 4th quarter
       ICED:     a starter's game is final and he finished at 0 or below
       OFF THIN ICE: a starter who got a thin-ice alert gets above 0
  An empty starting slot (D/ST included) or a starter on a bye week is also an Ice,
  logged once all of that week's games are final.
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
SLOTS = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 23: "FLEX", 17: "K"}  # starters whose score counts
ALL_SLOTS = {**SLOTS, 16: "D/ST"}  # every starting slot, for empty-slot checks


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

    info = get(LEAGUE + "?view=mStatus&view=mTeam&view=mSettings")
    latest = info["status"]["latestScoringPeriod"]
    members = {m["id"]: cap(f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()) for m in info.get("members", [])}
    teams = [{"teamId": t["id"], "team": (t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}").strip(),
              "owner": " & ".join(members.get(o, "") for o in t.get("owners", []))} for t in info["teams"]]
    tmap = {t["teamId"]: t for t in teams}
    # How many of each starting slot a lineup has (D/ST included, for empty-slot checks)
    slot_counts = {int(k): v for k, v in info["settings"]["rosterSettings"]["lineupSlotCounts"].items()
                   if v and int(k) in ALL_SLOTS}

    if os.environ.get("WEEKS"):  # e.g. WEEKS=1-6 to rebuild the whole season
        a, b = os.environ["WEEKS"].split("-")
        weeks = list(range(int(a), int(b) + 1))
    else:
        weeks = [w for w in (latest - 1, latest) if w >= 1]  # last week too, for stat corrections
    fresh, live = [], []

    def ice_alert(w, key, title, body, tags):
        if w == latest and key not in sent:
            push(title, body, tags)
            sent.add(key)

    for w in weeks:
        games, by_id = {}, {}
        for ev in get(SB.format(w=w)).get("events", []):
            st = ev["status"]
            g = {"final": st["type"]["completed"], "period": st.get("period", 0), "id": str(ev["id"]),
                 "name": ev["shortName"], "clock": st["type"].get("shortDetail", ""), "abbr": {}}
            for c in ev["competitions"][0]["competitors"]:
                g["abbr"][int(c["team"]["id"])] = c["team"]["abbreviation"]
                games[int(c["team"]["id"])] = g
            by_id[g["id"]] = g
        week_done = bool(by_id) and all(g["final"] for g in by_id.values())

        for t in get(LEAGUE + f"?view=mRoster&scoringPeriodId={w}")["teams"]:
            tm = tmap[t["id"]]
            filled = {}
            for e in t["roster"]["entries"]:
                slot = e["lineupSlotId"]
                if slot in ALL_SLOTS:
                    filled[slot] = filled.get(slot, 0) + 1
                if slot not in SLOTS:
                    continue  # bench, IR, and filled D/ST never count
                p = e["playerPoolEntry"]["player"]
                s = next((s for s in p.get("stats", []) if s.get("scoringPeriodId") == w
                          and s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1), None)
                # Find his game from that week's box score first (handles players who changed teams)
                g = by_id.get(str(s.get("externalId"))) if s and s.get("externalId") else None
                pro = (s or {}).get("proTeamId") or p.get("proTeamId")  # his team that week
                g = g or games.get(pro)
                pts = round(s["appliedTotal"], 2) if s else 0.0
                who = f"{p['fullName']} ({SLOTS[slot]}, {tm['team']})"
                base = {"id": f"{w}-{t['id']}-{p['id']}", "week": w, "teamId": t["id"], "team": tm["team"],
                        "owner": tm["owner"], "player": p["fullName"], "slot": SLOTS[slot]}
                if not g:
                    # Starter with no game this week (bye): 0 points once the week is over
                    if week_done and pts <= 0:
                        fresh.append({**base, "nfl": "BYE", "points": float(pts), "gameId": "", "status": "Bye week"})
                        ice_alert(w, f"iced-{w}-{t['id']}-{p['id']}", "ICED",
                                  f"{who} was started on a bye week: 0.00 pts, Week {w}", "tumbler_glass")
                    continue
                if not g["final"] and g["period"] < 1:
                    continue  # game not started
                if pts > 0:
                    thin, safe = f"thin-{w}-{t['id']}-{p['id']}", f"safe-{w}-{t['id']}-{p['id']}"
                    if thin in sent:
                        ice_alert(w, safe, "Off thin ice", f"{who} is off Ice Watch with {pts:.2f} pts. "
                                  f"{g['name']}, {g['clock']}", "white_check_mark")
                    continue
                row = {**base, "nfl": g["abbr"].get(pro, ""),
                       "points": float(pts), "gameId": g["id"]}
                if g["final"]:
                    row["status"] = "Played" if s and "210" in s.get("stats", {}) else "Inactive"
                    fresh.append(row)
                    ice_alert(w, f"iced-{w}-{t['id']}-{p['id']}", "ICED",
                              f"{who} finished with {pts:.2f} pts. {g['name']}, Week {w}", "tumbler_glass")
                elif w == latest:
                    row.update({"game": g["name"], "clock": g["clock"], "quarter": g["period"]})
                    live.append(row)
                    if g["period"] >= 4:
                        ice_alert(w, f"thin-{w}-{t['id']}-{p['id']}", "Thin ice",
                                  f"{who} has {pts:.2f} pts heading into the 4th. {g['name']}, {g['clock']}", "warning")

            # Empty starting slots (D/ST included) count once the week's games are all final
            if week_done:
                for slot, need in slot_counts.items():
                    for k in range(filled.get(slot, 0), need):
                        rid = f"{w}-{t['id']}-empty-{ALL_SLOTS[slot].replace('/', '')}-{k + 1}"
                        fresh.append({"id": rid, "week": w, "teamId": t["id"], "team": tm["team"], "owner": tm["owner"],
                                      "player": f"Empty {ALL_SLOTS[slot]} slot", "slot": ALL_SLOTS[slot], "nfl": "—",
                                      "points": 0.0, "gameId": "", "status": "Empty slot"})
                        ice_alert(w, "iced-" + rid, "ICED",
                                  f"{tm['team']} left a {ALL_SLOTS[slot]} slot empty in Week {w}", "tumbler_glass")

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
