"""Test na historii: model typuje mecze z przeszłości, znając tylko wcześniejsze dane."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from . import config, data
from .markets import evaluate, settle
from .model import devig, fit_league, predict, score_matrix
from .picks import select_picks


@dataclass
class Bucket:
    n: int = 0
    stake: float = 0.0
    profit: float = 0.0
    prob_sum: float = 0.0
    wins: float = 0.0

    def add(self, prob: float, w: float, l: float, odds: float | None) -> None:
        self.n += 1
        self.prob_sum += prob
        self.wins += w / (w + l) if w + l else 0
        if odds:
            self.stake += 1
            self.profit += w * (odds - 1) - l

    def line(self, name: str) -> str:
        roi = f"{self.profit / self.stake:+.1%}" if self.stake else "  —"
        return (f"{name:<28} typów {self.n:5d}  trafność {self.wins / self.n:6.1%}  "
                f"model mówił {self.prob_sum / self.n:6.1%}  ROI {roi}")


@dataclass
class Report:
    logloss: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    n_matches: int = 0
    goals_pred: float = 0.0
    goals_real: float = 0.0
    buckets: dict[str, Bucket] = field(default_factory=lambda: defaultdict(Bucket))


def run(divs: list[str], season_start: date, season_end: date, warmup_days: int = 42) -> Report:
    rep = Report()
    all_matches = data.load_matches(today=season_end, seasons=4, divs=divs)
    for div, matches in all_matches.items():
        season = [m for m in matches if season_start <= m.date <= season_end]
        if not season:
            continue
        first = season[0].date
        tested = [m for m in season if m.date >= first + timedelta(days=warmup_days)]
        by_week: dict[date, list[data.Match]] = defaultdict(list)
        for m in tested:
            by_week[m.date - timedelta(days=m.date.weekday())].append(m)
        for week, games in sorted(by_week.items()):
            model = fit_league(matches, week)
            for m in games:
                if not all(k in m.odds for k in ("1", "X", "2")):
                    continue
                fx = data.Fixture(div=div, kickoff=data._kickoff(m.date, None), home=m.home,
                                  away=m.away, referee=m.referee, odds=m.odds)
                pred = predict(model, fx)
                if not pred or not pred.lam_model or not pred.lam_market:
                    continue
                _score(rep, pred, m)
    return rep


def _score(rep: Report, pred, m: data.Match) -> None:
    outcome = 0 if m.hg > m.ag else 1 if m.hg == m.ag else 2
    rep.n_matches += 1
    rep.goals_pred += sum(pred.lam)
    rep.goals_real += m.hg + m.ag
    mkt = devig([m.odds["1"], m.odds["X"], m.odds["2"]])
    rep.logloss["rynek"] -= math.log(mkt[outcome])
    lm, lk = pred.lam_model, pred.lam_market
    for w in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
        lam = tuple(math.exp(w * math.log(a) + (1 - w) * math.log(b)) for a, b in zip(lm, lk))
        mat = score_matrix(*lam)
        i, j = np.indices(mat.shape)
        probs = [mat[i > j].sum(), mat[i == j].sum(), mat[i < j].sum()]
        rep.logloss[f"model w={w:.1f}"] -= math.log(max(probs[outcome], 1e-9))

    evals = evaluate(pred)
    for p in select_picks(pred, evals):
        res = settle(p.ev.market.key, m.hg, m.ag, m.hthg, m.htag, m.hcards, m.acards, m.hc, m.ac)
        if res is None:
            continue
        w, l = res
        if w + l == 0:
            continue
        odds = p.ev.odds if p.kind == "value" else None
        rep.buckets[f"{p.kind}"].add(p.ev.prob, w, l, odds)
        rep.buckets[f"{p.kind}: {p.ev.market.group}"].add(p.ev.prob, w, l, odds)
        if p.ev.market.group == "Handicap azjatycki" and p.kind == "value":
            side = "gospodarze" if p.ev.market.key.startswith("AH1") else "goście"
            fav = "faworyt" if p.ev.market.key[3] == "-" else "underdog"
            rep.buckets[f"value AH: {side}/{fav}"].add(p.ev.prob, w, l, odds)
        if p.kind != "value":
            # „ROI”, gdyby bukmacher płacił dokładnie nasz minimalny kurs
            rep.buckets[f"{p.kind} @min_kurs"].add(p.ev.prob, w, l, p.min_odds)


def print_report(rep: Report) -> None:
    n = rep.n_matches
    print(f"Meczów w teście: {n}")
    if not n:
        return
    print(f"Średnio goli: model {rep.goals_pred / n:.2f}, naprawdę {rep.goals_real / n:.2f}")
    print("\nLog-loss 1X2 (mniej = lepiej):")
    for k, v in sorted(rep.logloss.items(), key=lambda kv: kv[1]):
        print(f"  {k:<14} {v / n:.4f}")
    print("\nTypy:")
    for k in sorted(rep.buckets):
        print("  " + rep.buckets[k].line(k))


def main(args: list[str]) -> None:
    """python -m typy test [ROK_STARTU_SEZONU] [LIGI...], np. python -m typy test 2024 E0 SP1"""
    start_year = int(args[0]) if args and args[0].isdigit() else date.today().year - 1
    divs = [a for a in args if not a.isdigit()] or list(config.MAIN_LEAGUES)
    rep = run(divs, date(start_year, 7, 1), date(start_year + 1, 6, 30))
    print(f"Sezon {start_year}/{start_year + 1}, ligi: {' '.join(divs)}")
    print_report(rep)
