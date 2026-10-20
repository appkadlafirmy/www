"""Test na Lidze Mistrzów bieżącego sezonu: python -m typy test-lm

Bot typuje każdy rozegrany mecz tak, jakby był ranek dnia meczu: zna tylko wcześniejsze wyniki,
formę zawodników z wcześniejszych meczów i kursy sprzed meczu (bez składów). Dopiero potem
sprawdzamy wyniki.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

from . import data, espn, players
from .engine import Engine
from .markets import evaluate, settle
from .picks import select_picks
from .report import KIND_ICON

API = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def _events(slug: str, start: date, end: date) -> list[dict]:
    out, d = [], start
    while d <= end:
        for e in players._get(f"{API}/{slug}/scoreboard?dates={d:%Y%m%d}").get("events", []):
            comp = e["competitions"][0]
            if comp["status"]["type"].get("completed"):
                teams = {c["homeAway"]: c["team"] for c in comp["competitors"]}
                out.append({"id": e["id"], "date": e["date"], "home": teams["home"], "away": teams["away"]})
        d += timedelta(days=1)
    return out


def _pre_match_odds(event_id: str) -> dict[str, float]:
    """Kursy sprzed meczu (DraftKings) z podsumowania meczu w ESPN."""
    s = players._get(f"{API}/all/summary?event={event_id}")
    for o in s.get("pickcenter") or s.get("odds") or []:
        if not isinstance(o, dict):
            continue
        h = espn.american_to_decimal((o.get("homeTeamOdds") or {}).get("moneyLine"))
        a = espn.american_to_decimal((o.get("awayTeamOdds") or {}).get("moneyLine"))
        x = espn.american_to_decimal((o.get("drawOdds") or {}).get("moneyLine"))
        out = {}
        if h and a and x:
            out.update({"1": h, "X": x, "2": a})
        line, ov, un = o.get("overUnder"), espn.american_to_decimal(o.get("overOdds")), \
            espn.american_to_decimal(o.get("underOdds"))
        if line and ov and un:
            out.update({f"O{float(line)}": ov, f"U{float(line)}": un})
        if out:
            return out
    return {}


def run(slug: str = "uefa.champions", start: date = date(2026, 7, 1)) -> None:
    engine = Engine()
    engine.matches = data.load_matches()
    engine._loaded_at = time.time()  # bez pobierania aktualnego terminarza
    teams = {div: {t for m in ms for t in (m.home, m.away)} for div, ms in engine.matches.items()}
    matcher = espn.TeamMatcher(teams)

    events = _events(slug, start, date.today())
    print(f"Rozegrane mecze: {len(events)}\n")
    rows, best = [], []
    for e in sorted(events, key=lambda e: e["date"]):
        kickoff = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(data.PL)
        names, divs = [], []
        for side in ("home", "away"):
            m = matcher.match(e[side]["displayName"], None)
            names.append(m[0] if m else e[side]["displayName"])
            divs.append(m[1] if m else None)
        fx = data.Fixture(div="UCL", kickoff=kickoff, home=names[0], away=names[1], referee=None,
                          odds=_pre_match_odds(e["id"]), home_div=divs[0], away_div=divs[1],
                          espn_id=e["id"], espn_home_id=e["home"]["id"], espn_away_id=e["away"]["id"])
        result = players.match_from_event(e["id"], "UCL", fx.home, fx.away)
        pred = engine.predict(fx)
        if not pred or not result:
            print(f"{fx.home} – {fx.away}: brak kursów/danych, pominięty")
            continue
        evals = evaluate(pred)
        pms, _ = engine.player_markets(fx, pred, use_lineups=False)
        picks = select_picks(pred, evals, pms)
        score = f"{result.hg}:{result.ag}"
        print(f"{kickoff:%d.%m} {fx.home} – {fx.away}  ({score})")
        if not picks:
            print("   bez typu")
        for i, p in enumerate(sorted(picks, key=lambda p: (-p.stars, -p.score))):
            key = p.ev.market.key
            res = players.settle_player(key, e["id"]) if key.startswith("P:") else settle(key, result)
            if res is None:
                print(f"   ? {p.ev.label} (brak danych do rozliczenia)")
                continue
            w, l = res
            outcome = "push" if w == l else "won" if w > l else "lost"
            icon = {"won": "✅", "lost": "❌", "push": "↩️"}[outcome]
            print(f"   {icon} {KIND_ICON.get(p.kind, '•')} {p.ev.label} — {p.ev.prob:.0%}, kurs od {p.min_odds:.2f}")
            row = (p, outcome)
            rows.append(row)
            if i == 0:
                best.append(row)
    _summary("Wszystkie typy (maks. 3 na mecz)", rows)
    _summary("Typ dnia (1 najlepszy na mecz)", best)


def _summary(title: str, rows: list) -> None:
    decided = [(p, o) for p, o in rows if o != "push"]
    if not decided:
        return
    won = sum(o == "won" for _, o in decided)
    exp = sum(p.ev.prob for p, _ in decided)
    profit = sum((p.min_odds - 1) if o == "won" else -1 for p, o in decided)
    print(f"\n=== {title}")
    print(f"Trafione {won}/{len(decided)} = {won / len(decided):.0%} (model zakładał {exp / len(decided):.0%}), "
          f"zwroty: {len(rows) - len(decided)}")
    print(f"Wynik przy grze 1 zł po „kursie od”: {profit:+.2f} zł ({profit / len(decided):+.1%} na typ)")
    kinds: dict[str, list[int]] = {}
    for p, o in decided:
        k = kinds.setdefault(p.kind, [0, 0])
        k[0] += o == "won"
        k[1] += 1
    print("  " + " · ".join(f"{KIND_ICON.get(k, '•')} {k} {w}/{n}" for k, (w, n) in kinds.items()))


def main(args: list[str]) -> None:
    run(args[0] if args else "uefa.champions")
