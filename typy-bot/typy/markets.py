"""Wszystkie rynki zakładów (oferta jak u polskich bukmacherów, np. Betclic): jak liczyć
ich prawdopodobieństwo i jak je rozliczyć.

Każdy rynek to funkcja wyniku -> (część stawki wygrana, część stawki przegrana).
Ta sama definicja służy do liczenia szans z rozkładu i do rozliczania po meczu
(łącznie z handicapami azjatyckimi, gdzie bywa zwrot albo pół wygranej).

Rodzaje (kind):
  ft      gole w meczu (a, b)
  ht      gole w 1. połowie (a, b)
  2h      gole w 2. połowie (a, b)
  halves  obie połowy naraz (gosp. 1. poł., goście 1. poł., gosp. 2. poł., goście 2. poł.)
  cards / reds / corners / sot / shots / fouls   statystyki (gospodarze, goście)

Rynków na zawodników (strzelcy, asysty) nie ma — darmowe dane nie mają statystyk graczy.
Nie ma też rynków, których nie da się rozliczyć z danych (np. kto pierwszy strzeli, rzut karny).
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable

import numpy as np

from . import config
from .data import Match
from .model import Prediction, negbin_pmf, poisson_pmf, score_matrix

Settle = Callable[..., tuple[float, float]]

HALF_TIME_SHARE = 0.45  # ok. 45% goli pada przed przerwą
HALVES_MAX = 6

# Dopełniacz do etykiet („więcej rożnych”)
GENITIVE = {"cards": "kartek", "reds": "czerwonych kartek", "corners": "rożnych", "sot": "strzałów celnych",
            "shots": "strzałów", "fouls": "fauli"}

# Statystyki: nazwa w tekstach, ikona, maks. liczba na drużynę w rozkładzie
COUNT_KINDS = {
    "cards": ("kartki", "🟨", 12),
    "reds": ("czerwone kartki", "🟥", 4),
    "corners": ("rożne", "🚩", 22),
    "sot": ("strzały celne", "🎯", 20),
    "shots": ("strzały", "👟", 45),
    "fouls": ("faule", "🦵", 40),
}


@dataclass
class MarketDef:
    key: str
    label: str        # z {h} i {a} w miejscu nazw drużyn
    group: str
    kind: str
    settle: Settle
    odds_key: str | None = None
    side: str = "t"               # t = łącznie, h / a = jedna drużyna, cmp = porównanie drużyn
    direction: str | None = None  # "over" / "under" dla rynków powyżej/poniżej
    favours: str | None = None    # przy porównaniach: na którą drużynę stawiamy (h / a / x)


def _win(cond: bool) -> tuple[float, float]:
    return (1.0, 0.0) if cond else (0.0, 1.0)


def _value(a: int, b: int, side: str) -> int:
    return a + b if side == "t" else a if side == "h" else b


def _over(line: float, side: str = "t") -> Settle:
    return lambda a, b: _win(_value(a, b, side) > line)


def _under(line: float, side: str = "t") -> Settle:
    return lambda a, b: _win(_value(a, b, side) < line)


def _asian(line: float, home: bool) -> Settle:
    """Handicap azjatycki dla gospodarzy (home=True) lub gości, linia np. -0.75."""
    def single(diff: float, l: float) -> tuple[float, float]:
        x = diff + l
        return (1.0, 0.0) if x > 0 else (0.0, 1.0) if x < 0 else (0.0, 0.0)

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


def _num(x: float) -> str:
    return f"{x:g}"


_RES = {"1": lambda a, b: a > b, "X": lambda a, b: a == b, "2": lambda a, b: a < b}
_RES_NAME = {"1": "Wygrana {h}", "X": "Remis", "2": "Wygrana {a}"}
_DC = {"1X": lambda a, b: a >= b, "X2": lambda a, b: a <= b, "12": lambda a, b: a != b}
_DC_LABEL = {"1X": "{h} lub remis", "X2": "{a} lub remis", "12": "ktoś wygra"}


def _goal_markets() -> list[MarketDef]:
    m: list[MarketDef] = []
    add = m.append
    # --- wynik meczu
    for r in "1X2":
        add(MarketDef(r, _RES_NAME[r], "Wynik meczu (1X2)", "ft", lambda a, b, r=r: _win(_RES[r](a, b)), r))
    for k, f in _DC.items():
        add(MarketDef(k, f"Podwójna szansa: {_DC_LABEL[k]} ({k})", "Podwójna szansa", "ft",
                      lambda a, b, f=f: _win(f(a, b))))
    add(MarketDef("DNB1", "Zakład bez remisu: {h}", "Zakład bez remisu", "ft",
                  lambda a, b: (1.0, 0.0) if a > b else (0.0, 0.0) if a == b else (0.0, 1.0)))
    add(MarketDef("DNB2", "Zakład bez remisu: {a}", "Zakład bez remisu", "ft",
                  lambda a, b: (1.0, 0.0) if b > a else (0.0, 0.0) if a == b else (0.0, 1.0)))
    # --- liczba goli
    for line in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5):
        ok = "O2.5" if line == 2.5 else None
        uk = "U2.5" if line == 2.5 else None
        add(MarketDef(f"O{line}", f"Powyżej {line} gola w meczu", "Liczba goli", "ft", _over(line), ok,
                      direction="over"))
        add(MarketDef(f"U{line}", f"Poniżej {line} gola w meczu", "Liczba goli", "ft", _under(line), uk,
                      direction="under"))
    for n in range(6):
        lab = "5+" if n == 5 else str(n)
        add(MarketDef(f"G={lab}", f"Dokładna liczba goli: {lab}", "Dokładna liczba goli", "ft",
                      lambda a, b, n=n: _win(a + b >= 5 if n == 5 else a + b == n)))
    for lo, hi in ((0, 1), (2, 3), (4, 6), (7, 99)):
        lab = f"{lo}+" if hi == 99 else f"{lo}-{hi}"
        add(MarketDef(f"G{lab}", f"Liczba goli w przedziale: {lab}", "Dokładna liczba goli", "ft",
                      lambda a, b, lo=lo, hi=hi: _win(lo <= a + b <= hi)))
    add(MarketDef("ODD", "Liczba goli nieparzysta", "Parzyste / nieparzyste", "ft",
                  lambda a, b: _win((a + b) % 2 == 1)))
    add(MarketDef("EVEN", "Liczba goli parzysta", "Parzyste / nieparzyste", "ft",
                  lambda a, b: _win((a + b) % 2 == 0)))
    # --- obie drużyny strzelą, gole drużyn, czyste konto
    add(MarketDef("BTTS_Y", "Obie drużyny strzelą: TAK", "Obie drużyny strzelą", "ft",
                  lambda a, b: _win(a > 0 and b > 0)))
    add(MarketDef("BTTS_N", "Obie drużyny strzelą: NIE", "Obie drużyny strzelą", "ft",
                  lambda a, b: _win(a == 0 or b == 0)))
    for side, name in (("h", "{h}"), ("a", "{a}")):
        S = side.upper()
        for line in (0.5, 1.5, 2.5, 3.5):
            add(MarketDef(f"{S}O{line}", f"{name}: powyżej {line} gola", "Gole drużyny", "ft",
                          _over(line, side), side=side, direction="over"))
            add(MarketDef(f"{S}U{line}", f"{name}: poniżej {line} gola", "Gole drużyny", "ft",
                          _under(line, side), side=side, direction="under"))
        add(MarketDef(f"CLEAN{S}", f"{name} zachowa czyste konto", "Czyste konto", "ft",
                      lambda a, b, s=side: _win((b if s == "h" else a) == 0)))
        add(MarketDef(f"WTN{S}", f"{name} wygra do zera", "Czyste konto", "ft",
                      lambda a, b, s=side: _win(a > b and b == 0) if s == "h" else _win(b > a and a == 0)))
    # --- różnica zwycięstwa
    for side, name in (("h", "{h}"), ("a", "{a}")):
        for d in (1, 2, 3):
            lab = "3+" if d == 3 else str(d)
            add(MarketDef(f"MARGIN{side.upper()}{lab}", f"{name} wygra różnicą {lab} gol{'a' if d == 1 else 'i'}",
                          "Różnica zwycięstwa", "ft",
                          lambda a, b, s=side, d=d: _win(((a - b) if s == "h" else (b - a)) >= d) if d == 3
                          else _win(((a - b) if s == "h" else (b - a)) == d)))
    # --- dokładny wynik
    for i, j in product(range(5), range(5)):
        add(MarketDef(f"CS{i}:{j}", f"Dokładny wynik {i}:{j}", "Dokładny wynik", "ft",
                      lambda a, b, i=i, j=j: _win(a == i and b == j)))
    add(MarketDef("CS_INNY", "Dokładny wynik: inny", "Dokładny wynik", "ft", lambda a, b: _win(a > 4 or b > 4)))
    # --- kombinacje
    for r in "1X2":
        for bt in ("TAK", "NIE"):
            add(MarketDef(f"{r}&BTTS_{bt[0]}", f"{_RES_NAME[r]} i obie strzelą: {bt}", "Wynik + obie strzelą", "ft",
                          lambda a, b, r=r, bt=bt: _win(_RES[r](a, b) and ((a > 0 and b > 0) == (bt == "TAK")))))
        for line in (1.5, 2.5, 3.5):
            for ou in ("O", "U"):
                word = "powyżej" if ou == "O" else "poniżej"
                add(MarketDef(f"{r}&{ou}{line}", f"{_RES_NAME[r]} i {word} {line} gola", "Wynik + liczba goli", "ft",
                              lambda a, b, r=r, line=line, ou=ou: _win(_RES[r](a, b) and ((a + b > line) == (ou == "O")))))
    for k, f in _DC.items():
        for line in (1.5, 2.5, 3.5):
            for ou in ("O", "U"):
                word = "powyżej" if ou == "O" else "poniżej"
                add(MarketDef(f"{k}&{ou}{line}", f"Podwójna szansa {_DC_LABEL[k]} ({k}) i {word} {line} gola",
                              "Podwójna szansa + liczba goli", "ft",
                              lambda a, b, f=f, line=line, ou=ou: _win(f(a, b) and ((a + b > line) == (ou == "O")))))
    for bt in ("TAK", "NIE"):
        for line in (2.5, 3.5):
            for ou in ("O", "U"):
                word = "powyżej" if ou == "O" else "poniżej"
                add(MarketDef(f"BTTS_{bt[0]}&{ou}{line}", f"Obie strzelą: {bt} i {word} {line} gola",
                              "Obie strzelą + liczba goli", "ft",
                              lambda a, b, bt=bt, line=line, ou=ou: _win(((a > 0 and b > 0) == (bt == "TAK"))
                                                                         and ((a + b > line) == (ou == "O")))))
    # --- handicapy
    for q in range(-10, 11):
        line = q / 4
        if line == 0:
            continue
        add(MarketDef(f"AH1{_fmt(line)}", f"Handicap azjatycki {{h}} ({_fmt(line)})", "Handicap azjatycki", "ft",
                      _asian(line, True)))
        add(MarketDef(f"AH2{_fmt(line)}", f"Handicap azjatycki {{a}} ({_fmt(line)})", "Handicap azjatycki", "ft",
                      _asian(line, False)))
    for n in (-3, -2, -1, 1, 2, 3):
        h = f"{n:+d}"
        add(MarketDef(f"EH{h}_1", f"Handicap {{h}} ({h}): wygrana {{h}}", "Handicap europejski", "ft",
                      lambda a, b, n=n: _win(a + n > b)))
        add(MarketDef(f"EH{h}_X", f"Handicap {{h}} ({h}): remis", "Handicap europejski", "ft",
                      lambda a, b, n=n: _win(a + n == b)))
        add(MarketDef(f"EH{h}_2", f"Handicap {{h}} ({h}): wygrana {{a}}", "Handicap europejski", "ft",
                      lambda a, b, n=n: _win(a + n < b)))
    # --- 1. i 2. połowa
    for kind, half, name in (("ht", "HT", "1. połowa"), ("2h", "2H", "2. połowa")):
        for r in "1X2":
            add(MarketDef(f"{half}_{r}", f"{name}: {_RES_NAME[r].lower()}", f"{name}: wynik", kind,
                          lambda a, b, r=r: _win(_RES[r](a, b))))
        for k, f in _DC.items():
            add(MarketDef(f"{half}_{k}", f"{name}: podwójna szansa {_DC_LABEL[k]} ({k})", f"{name}: wynik", kind,
                          lambda a, b, f=f: _win(f(a, b))))
        for line in (0.5, 1.5, 2.5):
            add(MarketDef(f"{half}_O{line}", f"{name}: powyżej {line} gola", f"{name}: gole", kind,
                          _over(line), direction="over"))
            add(MarketDef(f"{half}_U{line}", f"{name}: poniżej {line} gola", f"{name}: gole", kind,
                          _under(line), direction="under"))
        add(MarketDef(f"{half}_BTTS_Y", f"{name}: obie strzelą TAK", f"{name}: gole", kind,
                      lambda a, b: _win(a > 0 and b > 0)))
        add(MarketDef(f"{half}_BTTS_N", f"{name}: obie strzelą NIE", f"{name}: gole", kind,
                      lambda a, b: _win(a == 0 or b == 0)))
        for side, nm in (("h", "{h}"), ("a", "{a}")):
            add(MarketDef(f"{half}_{side.upper()}O0.5", f"{name}: {nm} strzeli gola", f"{name}: gole", kind,
                          _over(0.5, side), side=side, direction="over"))
            add(MarketDef(f"{half}_{side.upper()}U0.5", f"{name}: {nm} nie strzeli", f"{name}: gole", kind,
                          _under(0.5, side), side=side, direction="under"))
    # --- obie połowy naraz
    short = {"1": "{h}", "X": "remis", "2": "{a}"}
    for r1, r2 in product("1X2", "1X2"):
        add(MarketDef(f"HTFT_{r1}/{r2}", f"Do przerwy / koniec: {short[r1]} / {short[r2]}",
                      "Do przerwy / koniec meczu", "halves",
                      lambda h1, a1, h2, a2, r1=r1, r2=r2: _win(_RES[r1](h1, a1) and _RES[r2](h1 + h2, a1 + a2))))
    add(MarketDef("HSH_1", "Więcej goli w 1. połowie", "Połowa z większą liczbą goli", "halves",
                  lambda h1, a1, h2, a2: _win(h1 + a1 > h2 + a2)))
    add(MarketDef("HSH_X", "Tyle samo goli w obu połowach", "Połowa z większą liczbą goli", "halves",
                  lambda h1, a1, h2, a2: _win(h1 + a1 == h2 + a2)))
    add(MarketDef("HSH_2", "Więcej goli w 2. połowie", "Połowa z większą liczbą goli", "halves",
                  lambda h1, a1, h2, a2: _win(h1 + a1 < h2 + a2)))
    add(MarketDef("BH_O0.5", "Gol w obu połowach", "Obie połowy", "halves",
                  lambda h1, a1, h2, a2: _win(h1 + a1 > 0 and h2 + a2 > 0)))
    add(MarketDef("BH_O1.5", "Powyżej 1.5 gola w obu połowach", "Obie połowy", "halves",
                  lambda h1, a1, h2, a2: _win(h1 + a1 > 1 and h2 + a2 > 1)))
    add(MarketDef("BH_U1.5", "Poniżej 1.5 gola w obu połowach", "Obie połowy", "halves",
                  lambda h1, a1, h2, a2: _win(h1 + a1 < 2 and h2 + a2 < 2)))
    for side, nm in (("h", "{h}"), ("a", "{a}")):
        S = side.upper()
        home = side == "h"

        def split(h1, a1, h2, a2, home=home):
            return ((h1, h2), (a1, a2)) if home else ((a1, a2), (h1, h2))

        add(MarketDef(f"WBH{S}", f"{nm} wygra obie połowy", "Obie połowy", "halves",
                      lambda *g, split=split: _win(all(o > x for o, x in zip(*split(*g))))))
        add(MarketDef(f"WEH{S}", f"{nm} wygra którąkolwiek połowę", "Obie połowy", "halves",
                      lambda *g, split=split: _win(any(o > x for o, x in zip(*split(*g))))))
        add(MarketDef(f"SBH{S}", f"{nm} strzeli w obu połowach", "Obie połowy", "halves",
                      lambda *g, split=split: _win(all(o > 0 for o in split(*g)[0]))))
    return m


def _count_markets(kind: str, P: str, totals, team_lines, handicaps=(), result=True) -> list[MarketDef]:
    name = COUNT_KINDS[kind][0]
    gen = GENITIVE[kind]
    title = name.capitalize()
    m: list[MarketDef] = []
    for line in totals:
        m.append(MarketDef(f"{P}_O{_num(line)}", f"{title} w meczu: powyżej {_num(line)}", title, kind,
                           _over(line), direction="over"))
        m.append(MarketDef(f"{P}_U{_num(line)}", f"{title} w meczu: poniżej {_num(line)}", title, kind,
                           _under(line), direction="under"))
    for side, nm in (("h", "{h}"), ("a", "{a}")):
        for line in team_lines:
            m.append(MarketDef(f"{P}{side.upper()}_O{_num(line)}", f"{nm}: {name} powyżej {_num(line)}",
                               f"{title} drużyny", kind, _over(line, side), side=side, direction="over"))
            m.append(MarketDef(f"{P}{side.upper()}_U{_num(line)}", f"{nm}: {name} poniżej {_num(line)}",
                               f"{title} drużyny", kind, _under(line, side), side=side, direction="under"))
    if result:
        m.append(MarketDef(f"{P}_1", f"{{h}}: więcej {gen}", f"{title}: kto więcej", kind,
                           lambda a, b: _win(a > b), side="cmp", favours="h"))
        m.append(MarketDef(f"{P}_X", f"Tyle samo {gen}", f"{title}: kto więcej", kind,
                           lambda a, b: _win(a == b), side="cmp", favours="x"))
        m.append(MarketDef(f"{P}_2", f"{{a}}: więcej {gen}", f"{title}: kto więcej", kind,
                           lambda a, b: _win(a < b), side="cmp", favours="a"))
    for line in handicaps:
        m.append(MarketDef(f"{P}_AH1{_fmt(line)}", f"{{h}}: {name} handicap {_fmt(line)}", f"{title}: handicap",
                           kind, _asian(line, True), side="cmp", favours="h"))
        m.append(MarketDef(f"{P}_AH2{_fmt(-line)}", f"{{a}}: {name} handicap {_fmt(-line)}", f"{title}: handicap",
                           kind, _asian(-line, False), side="cmp", favours="a"))
    return m


def _build() -> list[MarketDef]:
    m = _goal_markets()
    m += _count_markets("cards", "C", (1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5), (0.5, 1.5, 2.5, 3.5, 4.5), (-1.5, 1.5))
    m.append(MarketDef("R_Y", "Czerwona kartka w meczu: TAK", "Czerwone kartki", "reds", _over(0.5), direction="over"))
    m.append(MarketDef("R_N", "Czerwona kartka w meczu: NIE", "Czerwone kartki", "reds", _under(0.5),
                       direction="under"))
    m += _count_markets("corners", "K", (6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5),
                        (1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5), (-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5))
    m += _count_markets("sot", "S", (5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5), (1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5))
    m += _count_markets("shots", "T", (18.5, 20.5, 22.5, 24.5, 26.5, 28.5, 30.5), (7.5, 9.5, 11.5, 13.5, 15.5, 17.5))
    m += _count_markets("fouls", "F", (18.5, 20.5, 22.5, 24.5, 26.5, 28.5), (8.5, 10.5, 12.5, 14.5))
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
    odds: float | None = None        # kurs bukmacherów, jeśli znany

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


_PAYOFFS: dict[tuple[str, tuple[int, ...]], tuple[np.ndarray, np.ndarray]] = {}


def _payoff(m: MarketDef, shape: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray]:
    """Tabela wypłat rynku dla każdego możliwego wyniku — liczona raz, potem z pamięci."""
    key = (m.key, shape)
    if key not in _PAYOFFS:
        w, l = np.zeros(shape), np.zeros(shape)
        for idx in np.ndindex(*shape):
            w[idx], l[idx] = m.settle(*idx)
        _PAYOFFS[key] = (w, l)
    return _PAYOFFS[key]


def _expect(dist: np.ndarray, m: MarketDef) -> tuple[float, float]:
    w, l = _payoff(m, dist.shape)
    return float((dist * w).sum()), float((dist * l).sum())


def _count_dist(lam: tuple[float, float], dispersion: float, kind: str) -> np.ndarray:
    n = COUNT_KINDS[kind][2]
    d = max(dispersion, 1.0) * config.COUNT_DISPERSION_BOOST.get(kind, 1.0)
    return np.outer(negbin_pmf(lam[0], d, n), negbin_pmf(lam[1], d, n))


def _half(lam: tuple[float, float] | None, share: float) -> np.ndarray | None:
    return score_matrix(*(x * share for x in lam), rho=0.0) if lam else None


def _halves(lam: tuple[float, float] | None) -> np.ndarray | None:
    if not lam:
        return None
    n = HALVES_MAX
    ph1, pa1 = poisson_pmf(lam[0] * HALF_TIME_SHARE, n), poisson_pmf(lam[1] * HALF_TIME_SHARE, n)
    ph2, pa2 = poisson_pmf(lam[0] * (1 - HALF_TIME_SHARE), n), poisson_pmf(lam[1] * (1 - HALF_TIME_SHARE), n)
    return np.einsum("i,j,k,l->ijkl", ph1, pa1, ph2, pa2)


def evaluate(pred: Prediction) -> list[MarketEval]:
    fx = pred.fixture
    lams = (pred.lam, pred.lam_model, pred.lam_market)
    dists: dict[str, tuple] = {
        "ft": (pred.matrix, pred.matrix_model, pred.matrix_market),
        "ht": tuple(_half(l, HALF_TIME_SHARE) for l in lams),
        "2h": tuple(_half(l, 1 - HALF_TIME_SHARE) for l in lams),
        "halves": tuple(_halves(l) for l in lams),
    }
    for kind, c in pred.counts.items():
        dists[kind] = (_count_dist(c.lam, c.dispersion, kind), None, None)

    out = []
    for m in MARKETS:
        if m.kind not in dists:
            continue
        main, mod, mkt = dists[m.kind]
        w, l = _expect(main, m)
        ev = MarketEval(m, m.label.format(h=fx.home, a=fx.away), w, l)
        if mod is not None:
            ev.win_model, ev.lose_model = _expect(mod, m)
        if mkt is not None:
            ev.win_market, ev.lose_market = _expect(mkt, m)
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


def outcome(kind: str, m: Match) -> tuple[int, ...] | None:
    """Wynik meczu w formie, jakiej oczekuje dany rodzaj rynku (None, gdy brak danych)."""
    if kind == "ft":
        return m.hg, m.ag
    if kind in ("ht", "2h", "halves"):
        if m.hthg is None or m.htag is None:
            return None
        if kind == "ht":
            return m.hthg, m.htag
        if kind == "2h":
            return m.hg - m.hthg, m.ag - m.htag
        return m.hthg, m.htag, m.hg - m.hthg, m.ag - m.htag
    return m.stat(kind)


def settle(key: str, m: Match) -> tuple[float, float] | None:
    """Rozlicz typ po meczu. Zwraca (część wygrana, część przegrana) albo None, gdy brak danych."""
    market = BY_KEY.get(key)
    if not market:
        return None
    res = outcome(market.kind, m)
    return None if res is None else market.settle(*res)
