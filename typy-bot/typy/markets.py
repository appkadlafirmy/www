"""Wszystkie rynki zakładów: jak liczyć ich prawdopodobieństwo i jak je rozliczyć.

Każdy rynek to funkcja (a, b) -> (część stawki wygrana, część stawki przegrana),
gdzie (a, b) to gole / kartki / rożne gospodarzy i gości. Dzięki temu ta sama
definicja służy do liczenia szans z rozkładu i do rozliczania po meczu
(łącznie z handicapami azjatyckimi, gdzie bywa zwrot lub pół wygranej).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import config
from .model import Prediction, negbin_pmf, score_matrix

Settle = Callable[[int, int], tuple[float, float]]

HALF_TIME_SHARE = 0.45  # ok. 45% goli pada przed przerwą


@dataclass
class MarketDef:
    key: str
    label: str        # z {h} i {a} w miejscu nazw drużyn
    group: str
    kind: str         # "ft" (gole w meczu), "ht" (1. połowa), "cards", "corners"
    settle: Settle
    odds_key: str | None = None  # klucz kursu w danych, jeśli jest


def _win(cond: bool) -> tuple[float, float]:
    return (1.0, 0.0) if cond else (0.0, 1.0)


def _over(line: float, side: str = "t") -> Settle:
    def f(a: int, b: int) -> tuple[float, float]:
        v = a + b if side == "t" else a if side == "h" else b
        return _win(v > line)
    return f


def _under(line: float, side: str = "t") -> Settle:
    def f(a: int, b: int) -> tuple[float, float]:
        v = a + b if side == "t" else a if side == "h" else b
        return _win(v < line)
    return f


def _asian(line: float, home: bool) -> Settle:
    """Handicap azjatycki dla gospodarzy (home=True) lub gości, linia np. -0.75."""
    def single(diff: float, l: float) -> tuple[float, float]:
        x = diff + l
        if x > 0:
            return 1.0, 0.0
        if x < 0:
            return 0.0, 1.0
        return 0.0, 0.0  # zwrot

    def f(a: int, b: int) -> tuple[float, float]:
        diff = (a - b) if home else (b - a)
        if abs(line * 4) % 2 == 1:  # linia ćwiartkowa: pół stawki na każdą z sąsiednich
            w1, l1 = single(diff, line - 0.25)
            w2, l2 = single(diff, line + 0.25)
            return (w1 + w2) / 2, (l1 + l2) / 2
        return single(diff, line)
    return f


def _fmt(line: float) -> str:
    s = f"{line:+.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("+0", "-0") else s


def _build() -> list[MarketDef]:
    m: list[MarketDef] = [
        MarketDef("1", "Wygrana {h}", "1X2", "ft", lambda a, b: _win(a > b), "1"),
        MarketDef("X", "Remis", "1X2", "ft", lambda a, b: _win(a == b), "X"),
        MarketDef("2", "Wygrana {a}", "1X2", "ft", lambda a, b: _win(a < b), "2"),
        MarketDef("1X", "Podwójna szansa: {h} lub remis (1X)", "Podwójna szansa", "ft",
                  lambda a, b: _win(a >= b)),
        MarketDef("X2", "Podwójna szansa: {a} lub remis (X2)", "Podwójna szansa", "ft",
                  lambda a, b: _win(a <= b)),
        MarketDef("12", "Podwójna szansa: ktoś wygra (12)", "Podwójna szansa", "ft",
                  lambda a, b: _win(a != b)),
        MarketDef("DNB1", "Zakład bez remisu: {h}", "Bez remisu", "ft",
                  lambda a, b: (1.0, 0.0) if a > b else (0.0, 0.0) if a == b else (0.0, 1.0)),
        MarketDef("DNB2", "Zakład bez remisu: {a}", "Bez remisu", "ft",
                  lambda a, b: (1.0, 0.0) if b > a else (0.0, 0.0) if a == b else (0.0, 1.0)),
        MarketDef("BTTS_Y", "Obie drużyny strzelą: TAK", "BTTS", "ft",
                  lambda a, b: _win(a > 0 and b > 0)),
        MarketDef("BTTS_N", "Obie drużyny strzelą: NIE", "BTTS", "ft",
                  lambda a, b: _win(a == 0 or b == 0)),
        MarketDef("1&O1.5", "Wygrana {h} i powyżej 1.5 gola", "Kombinacje", "ft",
                  lambda a, b: _win(a > b and a + b > 1.5)),
        MarketDef("2&O1.5", "Wygrana {a} i powyżej 1.5 gola", "Kombinacje", "ft",
                  lambda a, b: _win(b > a and a + b > 1.5)),
        MarketDef("BTTS&O2.5", "Obie strzelą i powyżej 2.5 gola", "Kombinacje", "ft",
                  lambda a, b: _win(a > 0 and b > 0 and a + b > 2.5)),
    ]
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        ok = "O2.5" if line == 2.5 else None
        uk = "U2.5" if line == 2.5 else None
        m.append(MarketDef(f"O{line}", f"Powyżej {line} gola", "Gole", "ft", _over(line), ok))
        m.append(MarketDef(f"U{line}", f"Poniżej {line} gola", "Gole", "ft", _under(line), uk))
    for line in (0.5, 1.5, 2.5):
        m.append(MarketDef(f"HO{line}", f"{{h}} powyżej {line} gola", "Gole drużyny", "ft", _over(line, "h")))
        m.append(MarketDef(f"HU{line}", f"{{h}} poniżej {line} gola", "Gole drużyny", "ft", _under(line, "h")))
        m.append(MarketDef(f"AO{line}", f"{{a}} powyżej {line} gola", "Gole drużyny", "ft", _over(line, "a")))
        m.append(MarketDef(f"AU{line}", f"{{a}} poniżej {line} gola", "Gole drużyny", "ft", _under(line, "a")))
    for q in range(-10, 11):
        line = q / 4
        if line == 0:
            continue
        m.append(MarketDef(f"AH1{_fmt(line)}", f"Handicap azjatycki {{h}} ({_fmt(line)})",
                           "Handicap azjatycki", "ft", _asian(line, True)))
        m.append(MarketDef(f"AH2{_fmt(line)}", f"Handicap azjatycki {{a}} ({_fmt(line)})",
                           "Handicap azjatycki", "ft", _asian(line, False)))
    for n in (1, 2):
        m.append(MarketDef(f"EH1-{n}", f"Handicap europejski {{h}} (-{n})", "Handicap europejski", "ft",
                           lambda a, b, n=n: _win(a - b > n)))
        m.append(MarketDef(f"EH2-{n}", f"Handicap europejski {{a}} (-{n})", "Handicap europejski", "ft",
                           lambda a, b, n=n: _win(b - a > n)))
    m.append(MarketDef("HT_O0.5", "1. połowa: powyżej 0.5 gola", "1. połowa", "ht", _over(0.5)))
    m.append(MarketDef("HT_U0.5", "1. połowa: poniżej 0.5 gola (0:0 do przerwy)", "1. połowa", "ht", _under(0.5)))
    m.append(MarketDef("HT_O1.5", "1. połowa: powyżej 1.5 gola", "1. połowa", "ht", _over(1.5)))
    m.append(MarketDef("HT_U1.5", "1. połowa: poniżej 1.5 gola", "1. połowa", "ht", _under(1.5)))
    m.append(MarketDef("HT_X", "1. połowa: remis", "1. połowa", "ht", lambda a, b: _win(a == b)))
    for line in (2.5, 3.5, 4.5, 5.5, 6.5):
        m.append(MarketDef(f"C_O{line}", f"Kartki: powyżej {line}", "Kartki", "cards", _over(line)))
        m.append(MarketDef(f"C_U{line}", f"Kartki: poniżej {line}", "Kartki", "cards", _under(line)))
    for line in (0.5, 1.5, 2.5, 3.5):
        m.append(MarketDef(f"CH_O{line}", f"Kartki {{h}}: powyżej {line}", "Kartki drużyny", "cards", _over(line, "h")))
        m.append(MarketDef(f"CH_U{line}", f"Kartki {{h}}: poniżej {line}", "Kartki drużyny", "cards", _under(line, "h")))
        m.append(MarketDef(f"CA_O{line}", f"Kartki {{a}}: powyżej {line}", "Kartki drużyny", "cards", _over(line, "a")))
        m.append(MarketDef(f"CA_U{line}", f"Kartki {{a}}: poniżej {line}", "Kartki drużyny", "cards", _under(line, "a")))
    m.append(MarketDef("C_1", "Więcej kartek: {h}", "Kartki drużyny", "cards", lambda a, b: _win(a > b)))
    m.append(MarketDef("C_2", "Więcej kartek: {a}", "Kartki drużyny", "cards", lambda a, b: _win(b > a)))
    for line in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
        m.append(MarketDef(f"K_O{line}", f"Rzuty rożne: powyżej {line}", "Rożne", "corners", _over(line)))
        m.append(MarketDef(f"K_U{line}", f"Rzuty rożne: poniżej {line}", "Rożne", "corners", _under(line)))
    for line in (2.5, 3.5, 4.5, 5.5, 6.5):
        m.append(MarketDef(f"KH_O{line}", f"Rożne {{h}}: powyżej {line}", "Rożne drużyny", "corners", _over(line, "h")))
        m.append(MarketDef(f"KH_U{line}", f"Rożne {{h}}: poniżej {line}", "Rożne drużyny", "corners", _under(line, "h")))
        m.append(MarketDef(f"KA_O{line}", f"Rożne {{a}}: powyżej {line}", "Rożne drużyny", "corners", _over(line, "a")))
        m.append(MarketDef(f"KA_U{line}", f"Rożne {{a}}: poniżej {line}", "Rożne drużyny", "corners", _under(line, "a")))
    m.append(MarketDef("K_1", "Więcej rożnych: {h}", "Rożne drużyny", "corners", lambda a, b: _win(a > b)))
    m.append(MarketDef("K_2", "Więcej rożnych: {a}", "Rożne drużyny", "corners", lambda a, b: _win(b > a)))
    return m


MARKETS = _build()
BY_KEY = {m.key: m for m in MARKETS}


@dataclass
class MarketEval:
    market: MarketDef
    label: str
    win: float                 # P(wygrana) w „ułamkach stawki”
    lose: float
    win_model: float | None = None   # sam nasz model (bez rynku)
    lose_model: float | None = None
    win_market: float | None = None  # to, co wynika z kursów rynku
    lose_market: float | None = None
    odds: float | None = None        # średni kurs bukmacherów, jeśli znany

    @property
    def prob(self) -> float:
        """Skuteczne prawdopodobieństwo (zwroty pominięte)."""
        return self.win / (self.win + self.lose) if self.win + self.lose else 0.0

    @property
    def prob_model(self) -> float | None:
        if self.win_model is None:
            return None
        s = self.win_model + self.lose_model
        return self.win_model / s if s else None

    @property
    def prob_market(self) -> float | None:
        if self.win_market is None:
            return None
        s = self.win_market + self.lose_market
        return self.win_market / s if s else None

    @property
    def fair_odds(self) -> float:
        return 1 + self.lose / self.win if self.win > 0 else float("inf")

    def ev(self, odds: float) -> float:
        """Oczekiwany zysk na 1 zł stawki przy danym kursie."""
        return self.win * (odds - 1) - self.lose


def _expect(dist: np.ndarray, f: Settle) -> tuple[float, float]:
    w = l = 0.0
    n_h, n_a = dist.shape
    for i in range(n_h):
        for j in range(n_a):
            p = dist[i, j]
            if p < 1e-9:
                continue
            a, b = f(i, j)
            w += p * a
            l += p * b
    return w, l


def _count_dist(lam: tuple[float, float], dispersion: float, n: int) -> np.ndarray:
    d = max(dispersion, 1.0) * config.COUNT_DISPERSION_BOOST
    return np.outer(negbin_pmf(lam[0], d, n), negbin_pmf(lam[1], d, n))


def evaluate(pred: Prediction) -> list[MarketEval]:
    fx = pred.fixture
    dists: dict[str, tuple[np.ndarray | None, np.ndarray | None, np.ndarray | None]] = {
        "ft": (pred.matrix, pred.matrix_model, pred.matrix_market),
        "ht": (score_matrix(*(x * HALF_TIME_SHARE for x in pred.lam), rho=0.0),
               score_matrix(*(x * HALF_TIME_SHARE for x in pred.lam_model), rho=0.0) if pred.lam_model else None,
               score_matrix(*(x * HALF_TIME_SHARE for x in pred.lam_market), rho=0.0) if pred.lam_market else None),
    }
    if pred.cards:
        dists["cards"] = (_count_dist(pred.cards, pred.cards_dispersion, 12), None, None)
    if pred.corners:
        dists["corners"] = (_count_dist(pred.corners, pred.corners_dispersion, 22), None, None)

    out = []
    for m in MARKETS:
        if m.kind not in dists:
            continue
        main, mod, mkt = dists[m.kind]
        w, l = _expect(main, m.settle)
        ev = MarketEval(m, m.label.format(h=fx.home, a=fx.away), w, l)
        if mod is not None:
            ev.win_model, ev.lose_model = _expect(mod, m.settle)
        if mkt is not None:
            ev.win_market, ev.lose_market = _expect(mkt, m.settle)
        ev.odds = _odds_for(m, fx.odds)
        out.append(ev)
    return out


def _odds_for(m: MarketDef, odds: dict[str, float]) -> float | None:
    if m.odds_key:
        return odds.get(m.odds_key)
    if m.kind == "ft" and m.key in odds:  # np. over/under 3.5 z ESPN
        return odds[m.key]
    line = odds.get("AH_LINE")
    if line is None:
        return None
    if m.key == f"AH1{_fmt(line)}":
        return odds.get("AHH")
    if m.key == f"AH2{_fmt(-line)}":
        return odds.get("AHA")
    return None


def settle(key: str, hg: int, ag: int, hthg: int | None = None, htag: int | None = None,
           hcards: int | None = None, acards: int | None = None,
           hc: int | None = None, ac: int | None = None) -> tuple[float, float] | None:
    """Rozlicz typ po meczu. Zwraca (część wygrana, część przegrana) albo None, gdy brak danych."""
    m = BY_KEY.get(key)
    if not m:
        return None
    vals = {"ft": (hg, ag), "ht": (hthg, htag), "cards": (hcards, acards), "corners": (hc, ac)}[m.kind]
    if vals[0] is None or vals[1] is None:
        return None
    return m.settle(*vals)

