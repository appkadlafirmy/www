"""Model siły drużyn: gole (z xG), kartki i rożne, plus kalibracja do kursów rynku."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from . import config
from .data import Fixture, Match

MAX_GOALS = 10


# ---------------------------------------------------------------- rozkłady

def poisson_pmf(lam: float, n: int) -> np.ndarray:
    k = np.arange(n + 1)
    logp = k * math.log(max(lam, 1e-9)) - lam - np.array([math.lgamma(i + 1) for i in k])
    p = np.exp(logp)
    p[-1] += max(0.0, 1.0 - p.sum())
    return p


def negbin_pmf(mean: float, dispersion: float, n: int) -> np.ndarray:
    """Ujemny dwumianowy o średniej `mean` i wariancji `dispersion * mean`."""
    if dispersion <= 1.02:
        return poisson_pmf(mean, n)
    r = mean / (dispersion - 1.0)
    p = r / (r + mean)
    k = np.arange(n + 1)
    logp = np.array([math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1) for i in k])
    logp += r * math.log(p) + k * math.log(1 - p)
    out = np.exp(logp)
    out[-1] += max(0.0, 1.0 - out.sum())
    return out


def score_matrix(lh: float, la: float, rho: float = config.DIXON_COLES_RHO) -> np.ndarray:
    """P(gole gospodarzy = i, gole gości = j) z korektą Dixona-Colesa."""
    m = np.outer(poisson_pmf(lh, MAX_GOALS), poisson_pmf(la, MAX_GOALS))
    m[0, 0] *= 1 - lh * la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 0] *= 1 + la * rho
    m[1, 1] *= 1 - rho
    return m / m.sum()


# ---------------------------------------------------------------- oceny drużyn

@dataclass
class Ratings:
    base_home: float
    base_away: float
    attack: dict[str, float]
    defence: dict[str, float]
    games: dict[str, float]
    dispersion: float = 1.0
    referee: dict[str, float] = field(default_factory=dict)

    def expected(self, home: str, away: str) -> tuple[float, float]:
        return (self.base_home * self.attack.get(home, 1.0) * self.defence.get(away, 1.0),
                self.base_away * self.attack.get(away, 1.0) * self.defence.get(home, 1.0))


def fit_ratings(obs: list[tuple[str, str, float, float, float]], prior_games: float = 4.0,
                iterations: int = 40) -> Ratings | None:
    """Ważone dopasowanie multiplikatywnego modelu Poissona (atak × obrona przeciwnika).

    obs: (gospodarz, gość, wartość gospodarzy, wartość gości, waga meczu)
    prior_games: ile „meczów przeciętnej drużyny” dodajemy każdemu zespołowi —
    chroni przed skrajnymi ocenami przy małej liczbie danych.
    """
    if len(obs) < 30:
        return None
    teams = sorted({o[0] for o in obs} | {o[1] for o in obs})
    sw = sum(o[4] for o in obs)
    bh = sum(o[2] * o[4] for o in obs) / sw
    ba = sum(o[3] * o[4] for o in obs) / sw
    att = {t: 1.0 for t in teams}
    dfn = {t: 1.0 for t in teams}
    games = {t: 0.0 for t in teams}
    for h, a, _, _, w in obs:
        games[h] += w
        games[a] += w
    for _ in range(iterations):
        num = {t: 0.0 for t in teams}
        den = {t: 0.0 for t in teams}
        for h, a, vh, va, w in obs:
            num[h] += w * vh
            den[h] += w * bh * dfn[a]
            num[a] += w * va
            den[a] += w * ba * dfn[h]
        r = (bh + ba) / 2
        att = {t: (num[t] + prior_games * r) / (den[t] + prior_games * r) for t in teams}
        num = {t: 0.0 for t in teams}
        den = {t: 0.0 for t in teams}
        for h, a, vh, va, w in obs:
            num[a] += w * vh
            den[a] += w * bh * att[h]
            num[h] += w * va
            den[h] += w * ba * att[a]
        dfn = {t: (num[t] + prior_games * r) / (den[t] + prior_games * r) for t in teams}
        ga = math.exp(sum(math.log(v) for v in att.values()) / len(att))
        gd = math.exp(sum(math.log(v) for v in dfn.values()) / len(dfn))
        att = {t: v / ga for t, v in att.items()}
        dfn = {t: v / gd for t, v in dfn.items()}
        eh = sum(w * att[h] * dfn[a] for h, a, _, _, w in obs)
        ea = sum(w * att[a] * dfn[h] for h, a, _, _, w in obs)
        bh = sum(o[2] * o[4] for o in obs) / eh
        ba = sum(o[3] * o[4] for o in obs) / ea
    ratings = Ratings(bh, ba, att, dfn, games)
    # nadmierna zmienność (dla kartek i rożnych zwykle > 1)
    num = den = 0.0
    for h, a, vh, va, w in obs:
        eh, ea = ratings.expected(h, a)
        num += w * ((vh - eh) ** 2 + (va - ea) ** 2)
        den += w * (eh + ea)
    ratings.dispersion = max(1.0, num / den) if den else 1.0
    return ratings


def _weight(d: date, ref: date, half_life: float) -> float:
    return 0.5 ** (max(0, (ref - d).days) / half_life)


def fit_league(matches: list[Match], ref: date) -> "LeagueModel":
    past = [m for m in matches if m.date < ref]
    goals_obs, cards_obs, corner_obs, ref_rows = [], [], [], []
    xw = config.XG_WEIGHT
    for m in past:
        w = _weight(m.date, ref, config.GOALS_HALF_LIFE_DAYS)
        if w < 0.02:
            continue
        if m.hxg is not None and m.axg is not None:
            vh, va = (1 - xw) * m.hg + xw * m.hxg, (1 - xw) * m.ag + xw * m.axg
        else:
            vh, va = m.hg, m.ag
        goals_obs.append((m.home, m.away, vh, va, w))
        wc = _weight(m.date, ref, config.COUNTS_HALF_LIFE_DAYS)
        if m.hcards is not None and m.acards is not None:
            cards_obs.append((m.home, m.away, m.hcards, m.acards, wc))
            if m.referee:
                ref_rows.append((m.referee, m.home, m.away, m.hcards + m.acards, wc))
        if m.hc is not None and m.ac is not None:
            corner_obs.append((m.home, m.away, m.hc, m.ac, wc))
    model = LeagueModel(
        goals=fit_ratings(goals_obs),
        cards=fit_ratings(cards_obs, prior_games=6.0),
        corners=fit_ratings(corner_obs, prior_games=6.0),
        matches=past,
    )
    if model.cards and ref_rows:
        model.cards.referee = _referee_factors(model.cards, ref_rows)
    return model


def _referee_factors(r: Ratings, rows, prior_games: float = 8.0) -> dict[str, float]:
    actual: dict[str, float] = {}
    expected: dict[str, float] = {}
    for name, h, a, total, w in rows:
        eh, ea = r.expected(h, a)
        actual[name] = actual.get(name, 0.0) + w * total
        expected[name] = expected.get(name, 0.0) + w * (eh + ea)
    avg = r.base_home + r.base_away
    return {n: (actual[n] + prior_games * avg) / (expected[n] + prior_games * avg) for n in actual}


# ---------------------------------------------------------------- tabela i motywacja

@dataclass
class TableRow:
    team: str
    played: int = 0
    points: int = 0
    gf: int = 0
    ga: int = 0
    position: int = 0


def league_table(matches: list[Match], ref: date) -> tuple[list[TableRow], int]:
    """Tabela bieżącego sezonu (mecze od ostatniej „dużej przerwy” w terminarzu)."""
    past = sorted((m for m in matches if m.date < ref), key=lambda m: m.date)
    start = 0
    for i in range(1, len(past)):
        if (past[i].date - past[i - 1].date).days > 45:
            start = i
    season = past[start:]
    rows: dict[str, TableRow] = {}
    for m in season:
        h = rows.setdefault(m.home, TableRow(m.home))
        a = rows.setdefault(m.away, TableRow(m.away))
        h.played += 1
        a.played += 1
        h.gf += m.hg
        h.ga += m.ag
        a.gf += m.ag
        a.ga += m.hg
        if m.hg > m.ag:
            h.points += 3
        elif m.hg < m.ag:
            a.points += 3
        else:
            h.points += 1
            a.points += 1
    table = sorted(rows.values(), key=lambda r: (-r.points, -(r.gf - r.ga), -r.gf))
    for i, r in enumerate(table, 1):
        r.position = i
    return table, len(season)


@dataclass
class Motivation:
    position: int
    teams: int
    points: int
    label: str
    factor: float  # mnożnik ataku (1.0 = bez zmian)


def motivation(table: list[TableRow], team: str) -> Motivation | None:
    by_team = {r.team: r for r in table}
    if team not in by_team or len(table) < 8:
        return None
    n = len(table)
    row = by_team[team]
    total_rounds = 2 * (n - 1)
    remaining = max(0, total_rounds - row.played)
    max_gain = 3 * remaining
    europe_spots = 4 if n >= 16 else 2
    releg_spots = 3 if n >= 18 else 2 if n >= 12 else 1
    leader = table[0].points
    europe_line = table[europe_spots - 1].points
    safe_line = table[n - releg_spots - 1].points
    releg_top = table[n - releg_spots].points
    pos = row.position
    late = remaining <= total_rounds * 0.3
    if row.played < total_rounds * 0.4:
        return Motivation(pos, n, row.points, "początek sezonu", 1.0)
    if pos <= 2 and leader - row.points <= max_gain:
        label = "walka o mistrzostwo"
    elif pos >= n - releg_spots + 1 or row.points - releg_top <= 4:
        label = "walka o utrzymanie"
    elif pos <= europe_spots + 1 or europe_line - row.points <= 4:
        label = "walka o puchary"
    else:
        label = "środek tabeli"
    factor = 1.0
    if late and label == "środek tabeli":
        far_from_top = europe_line - row.points > max_gain * 0.6
        far_from_bottom = row.points - safe_line > max_gain * 0.6
        if far_from_top and far_from_bottom:
            label = "nie gra już o nic"
            factor = 0.95
    return Motivation(pos, n, row.points, label, factor)


# ---------------------------------------------------------------- forma

@dataclass
class Form:
    results: str          # np. "ZZRPZ" (najnowszy po prawej)
    scored: int
    conceded: int
    xg_for: float | None
    xg_against: float | None
    cards_avg: float | None
    corners_avg: float | None


def team_form(matches: list[Match], team: str, ref: date, n: int = 5) -> Form | None:
    games = [m for m in matches if m.date < ref and team in (m.home, m.away)][-n:]
    if not games:
        return None
    res, gf, ga, xf, xa, cards, corners = [], 0, 0, 0.0, 0.0, [], []
    have_xg = all(m.hxg is not None for m in games)
    for m in games:
        home = m.home == team
        f, a = (m.hg, m.ag) if home else (m.ag, m.hg)
        gf += f
        ga += a
        res.append("Z" if f > a else "P" if f < a else "R")
        if have_xg:
            xf += m.hxg if home else m.axg
            xa += m.axg if home else m.hxg
        c = m.hcards if home else m.acards
        if c is not None:
            cards.append(c)
        k = m.hc if home else m.ac
        if k is not None:
            corners.append(k)
    return Form("".join(res), gf, ga, xf if have_xg else None, xa if have_xg else None,
                sum(cards) / len(cards) if cards else None,
                sum(corners) / len(corners) if corners else None)


def head_to_head(matches: list[Match], home: str, away: str, ref: date, n: int = 5) -> list[Match]:
    return [m for m in matches if m.date < ref and {m.home, m.away} == {home, away}][-n:]


# ---------------------------------------------------------------- kalibracja do rynku

def devig(odds: list[float]) -> list[float]:
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


_GRID = np.arange(0.15, 4.01, 0.05)


def _grid_probs(grid_h: np.ndarray, grid_a: np.ndarray, rho: float):
    ph = np.array([poisson_pmf(l, MAX_GOALS) for l in grid_h])
    pa = np.array([poisson_pmf(l, MAX_GOALS) for l in grid_a])
    i, j = np.meshgrid(np.arange(MAX_GOALS + 1), np.arange(MAX_GOALS + 1), indexing="ij")
    hw = ph @ (i > j).astype(float) @ pa.T
    dr = ph @ (i == j).astype(float) @ pa.T
    ov = ph @ (i + j >= 3).astype(float) @ pa.T
    lh, la = np.meshgrid(grid_h, grid_a, indexing="ij")
    p00 = np.outer(ph[:, 0], pa[:, 0])
    p10 = np.outer(ph[:, 1], pa[:, 0])
    p11 = np.outer(ph[:, 1], pa[:, 1])
    dr = dr - lh * la * rho * p00 - rho * p11
    hw = hw + la * rho * p10
    aw = 1 - hw - dr
    return lh, la, hw, dr, aw, ov


def market_lambdas(odds: dict[str, float], model_total: float | None = None,
                   rho: float = config.DIXON_COLES_RHO) -> tuple[float, float] | None:
    """Oczekiwane gole, które „widzi” rynek — dopasowane do kursów 1X2 i over/under 2.5."""
    if not all(k in odds for k in ("1", "X", "2")):
        return None
    p1, px, p2 = devig([odds["1"], odds["X"], odds["2"]])
    po = devig([odds["O2.5"], odds["U2.5"]])[0] if "O2.5" in odds and "U2.5" in odds else None
    grid_h, grid_a = _GRID, _GRID
    best = None
    for _ in range(2):
        lh, la, hw, dr, aw, ov = _grid_probs(grid_h, grid_a, rho)
        err = (hw - p1) ** 2 + (dr - px) ** 2 + (aw - p2) ** 2
        if po is not None:
            err = err + (ov - po) ** 2
        elif model_total:
            err = err + 0.002 * (lh + la - model_total) ** 2
        idx = np.unravel_index(np.argmin(err), err.shape)
        best = (float(lh[idx]), float(la[idx]))
        grid_h = np.clip(np.arange(best[0] - 0.05, best[0] + 0.0501, 0.005), 0.05, None)
        grid_a = np.clip(np.arange(best[1] - 0.05, best[1] + 0.0501, 0.005), 0.05, None)
    return best


# ---------------------------------------------------------------- prognoza meczu

@dataclass
class LeagueModel:
    goals: Ratings | None
    cards: Ratings | None
    corners: Ratings | None
    matches: list[Match]


@dataclass
class Prediction:
    fixture: Fixture
    lam_model: tuple[float, float] | None
    lam_market: tuple[float, float] | None
    lam: tuple[float, float]
    cards: tuple[float, float] | None = None
    cards_dispersion: float = 1.0
    cards_league_avg: float | None = None
    referee_factor: float | None = None
    corners: tuple[float, float] | None = None
    corners_dispersion: float = 1.0
    corners_league_avg: float | None = None
    form_home: Form | None = None
    form_away: Form | None = None
    h2h: list[Match] = field(default_factory=list)
    mot_home: Motivation | None = None
    mot_away: Motivation | None = None
    enough_data: bool = True

    @property
    def matrix(self) -> np.ndarray:
        return score_matrix(*self.lam)

    @property
    def matrix_model(self) -> np.ndarray | None:
        return score_matrix(*self.lam_model) if self.lam_model else None

    @property
    def matrix_market(self) -> np.ndarray | None:
        return score_matrix(*self.lam_market) if self.lam_market else None


def predict(model: LeagueModel, fx: Fixture) -> Prediction | None:
    ref = fx.date
    matches = model.matches
    table, _ = league_table(matches, ref)
    mh, ma = motivation(table, fx.home), motivation(table, fx.away)

    lam_model = None
    enough = False
    g = model.goals
    if g and fx.home in g.attack and fx.away in g.attack:
        lh, la = g.expected(fx.home, fx.away)
        if mh:
            lh *= mh.factor
        if ma:
            la *= ma.factor
        lam_model = (lh, la)
        enough = min(g.games.get(fx.home, 0), g.games.get(fx.away, 0)) >= config.MIN_TEAM_MATCHES * 0.5
        enough = enough and _count_recent(matches, fx.home, ref) >= config.MIN_TEAM_MATCHES \
            and _count_recent(matches, fx.away, ref) >= config.MIN_TEAM_MATCHES

    lam_market = market_lambdas(fx.odds, sum(lam_model) if lam_model else None)
    if lam_model and lam_market:
        w = config.MODEL_WEIGHT
        lam = tuple(math.exp(w * math.log(a) + (1 - w) * math.log(b))
                    for a, b in zip(lam_model, lam_market))
    elif lam_model or lam_market:
        lam = lam_model or lam_market
    else:
        return None

    pred = Prediction(fixture=fx, lam_model=lam_model, lam_market=lam_market, lam=lam,
                      form_home=team_form(matches, fx.home, ref),
                      form_away=team_form(matches, fx.away, ref),
                      h2h=head_to_head(matches, fx.home, fx.away, ref),
                      mot_home=mh, mot_away=ma, enough_data=enough)

    c = model.cards
    if c and fx.home in c.attack and fx.away in c.attack:
        ch, ca = c.expected(fx.home, fx.away)
        if fx.referee and fx.referee in c.referee:
            pred.referee_factor = c.referee[fx.referee]
            ch, ca = ch * pred.referee_factor, ca * pred.referee_factor
        pred.cards = (ch, ca)
        pred.cards_dispersion = c.dispersion
        pred.cards_league_avg = c.base_home + c.base_away
    k = model.corners
    if k and fx.home in k.attack and fx.away in k.attack:
        pred.corners = k.expected(fx.home, fx.away)
        pred.corners_dispersion = k.dispersion
        pred.corners_league_avg = k.base_home + k.base_away
    return pred


def _count_recent(matches: list[Match], team: str, ref: date) -> int:
    return sum(1 for m in matches if team in (m.home, m.away) and 0 < (ref - m.date).days <= 365)
