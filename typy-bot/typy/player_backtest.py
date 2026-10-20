"""Test na historii dla typów na zawodników: python -m typy test-zawodnicy [ligi ESPN...]

Dla każdego meczu drużyny (styczeń–maj 2026) liczymy formę zawodników tylko z wcześniejszych meczów
i porównujemy przewidywane szanse z tym, co się naprawdę stało.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from . import players

BINS = [(0.0, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 0.62), (0.62, 0.75), (0.75, 0.85), (0.85, 1.01)]


def _teams(slug: str) -> list[str]:
    d = players._get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/teams")
    try:
        return [t["team"]["id"] for t in d["sports"][0]["leagues"][0]["teams"]]
    except (KeyError, IndexError):
        return []


def run(slugs: list[str], season: int = 2025, start: str = "2026-01-01", end: str = "2026-06-01") -> None:
    calib: dict[str, list[tuple[float, float]]] = defaultdict(list)
    play = []  # (przewidywana szansa gry, czy zagrał)
    for slug in slugs:
        for team_id in _teams(slug):
            for e in players.team_schedule(team_id, season):
                if not (start <= e["date"] < end):
                    continue
                actual = players.event(e["id"])
                if not actual or team_id not in actual["teams"]:
                    continue
                before = datetime.fromisoformat(e["date"].replace("Z", "+00:00"))
                tf = players.team_form(team_id, before)
                if not tf:
                    continue
                stats = {p["id"]: p for p in actual["teams"][team_id]}
                for p in tf.players:
                    if p.p_play > 0 and p.pos != "G":
                        play.append((p.p_play, float(stats.get(p.id, {}).get("minutes", 0) > 0)))
                for m in players.player_markets(tf, None, None):
                    real = stats.get(m.player.id)
                    if not real or real["minutes"] <= 0:
                        continue  # nie zagrał = zwrot stawki, nie liczymy
                    line = float(m.key.rsplit(":", 1)[1])
                    hit = float(real[m.stat] > line)
                    calib[f"{m.stat} >{line}"].append((m.prob, hit))
                    for lo, hi in BINS:
                        if lo <= m.prob < hi:
                            calib[f"  wszystkie {lo:.2f}-{hi:.2f}"].append((m.prob, hit))
                    if m.player.p_play >= 0.8 and 0.62 <= m.prob <= 0.85:
                        calib["TYPY (62–85%, pewny skład)"].append((m.prob, hit))
                    if m.stat == "goals" and m.player.p_play >= 0.8 and m.prob >= 0.35:
                        calib["TYPY strzelec (≥35%)"].append((m.prob, hit))
    print("Rynek                              n   model   naprawdę")
    for k in sorted(calib):
        rows = calib[k]
        n = len(rows)
        print(f"{k:<30} {n:6d}  {sum(r[0] for r in rows) / n:6.1%}  {sum(r[1] for r in rows) / n:6.1%}")
    if play:
        print(f"\nCzy zagra: model {sum(p for p, _ in play) / len(play):.1%}, "
              f"naprawdę {sum(a for _, a in play) / len(play):.1%} (n={len(play)})")
        for lo, hi in ((0.0, 0.5), (0.5, 0.8), (0.8, 1.01)):
            sub = [(p, a) for p, a in play if lo <= p < hi]
            if sub:
                print(f"  szansa gry {lo:.1f}-{hi:.1f}: model {sum(p for p, _ in sub) / len(sub):.1%}, "
                      f"naprawdę {sum(a for _, a in sub) / len(sub):.1%} (n={len(sub)})")


def main(args: list[str]) -> None:
    run(args or ["eng.1", "esp.1"])
