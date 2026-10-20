"""Wybór typów: z dziesiątek rynków zostawiamy tylko te, w które model naprawdę wierzy."""
from __future__ import annotations

from dataclasses import dataclass

from . import config
from .markets import COUNT_KINDS, MarketEval
from .model import Prediction


@dataclass
class Pick:
    pred: Prediction
    ev: MarketEval
    kind: str      # "value" (lepszy kurs niż rynek), "model", "kartki", "rożne"
    score: float   # do sortowania: im wyżej, tym mocniejszy typ
    reason: str

    @property
    def min_odds(self) -> float:
        """Poniżej tego kursu nie warto grać."""
        return round(max(1.01, config.SAFETY_MARGIN * self.ev.fair_odds), 2)

    @property
    def stars(self) -> int:
        """Siła sygnału: ★ słaby, ★★ wyraźny, ★★★ mocny."""
        if self.kind == "value":
            edge = self.ev.ev(self.ev.odds)
            return 3 if edge >= 0.10 else 2 if edge >= 0.06 else 1
        if self.kind == "model":
            return 3 if self.score >= 0.10 else 2 if self.score >= 0.07 else 1
        return 3 if self.score >= 0.30 else 2 if self.score >= 0.20 else 1


def _value_candidates(pred: Prediction, evals: list[MarketEval]) -> list[Pick]:
    out = []
    lo, hi = config.VALUE_ODDS_RANGE
    for e in evals:
        if not e.odds or not (lo <= e.odds <= hi) or e.prob_model is None:
            continue
        edge = e.ev(e.odds)
        if edge < config.VALUE_MIN_EDGE or e.prob < config.VALUE_MIN_PROB:
            continue
        # sam model też musi widzieć przewagę, nie tylko mieszanka z rynkiem
        if e.prob_model * e.odds - 1 < config.VALUE_MIN_EDGE * 2:
            continue
        out.append(Pick(pred, e, "value", edge,
                        f"kurs {e.odds:.2f} vs nasza wycena {e.fair_odds:.2f} (przewaga {edge:+.0%})"))
    return out


def _model_candidates(pred: Prediction, evals: list[MarketEval]) -> list[Pick]:
    """Rynki bez kursu w danych (BTTS, handicapy, gole drużyn, 1. połowa...).

    Bierzemy je tylko, gdy nasz model daje im wyraźnie większą szansę niż wynika
    z kursów głównych rynków — wtedy jest szansa, że bukmacher je niedoszacował.
    """
    out = []
    for e in evals:
        if e.market.group not in config.MODEL_PICK_GROUPS or e.odds or e.prob_model is None:
            continue
        p = e.prob
        if not (config.MODEL_MIN_PROB <= p <= config.MODEL_MAX_PROB):
            continue
        if e.prob_model < config.MODEL_MIN_PROB:
            continue
        if e.prob_market is not None:
            gap = e.prob_model - e.prob_market
            # zbyt duża różnica to zwykle dziura w danych (np. beniaminek), a nie okazja
            if not (config.MODEL_MIN_DISAGREEMENT <= gap <= config.MODEL_MAX_DISAGREEMENT):
                continue
            reason = f"model {e.prob_model:.0%} vs rynek {e.prob_market:.0%}"
        else:
            gap = p - config.MODEL_MIN_PROB
            reason = f"model {e.prob_model:.0%} (brak kursów do porównania)"
        out.append(Pick(pred, e, "model", gap, reason))
    return out


def _count_candidates(pred: Prediction, evals: list[MarketEval], kind: str) -> list[Pick]:
    """Kartki, rożne, strzały, faule: typujemy, gdy mecz wyraźnie odstaje od średniej ligi
    w kierunku zgodnym z typem (np. „powyżej” tylko przy wyraźnie wyższej oczekiwanej liczbie)."""
    c = pred.counts.get(kind)
    if not c:
        return []
    h, a = c.lam
    name = COUNT_KINDS[kind][0]
    out = []
    for e in evals:
        m = e.market
        if m.kind != kind or not (config.COUNT_MIN_PROB <= e.prob <= config.COUNT_MAX_PROB):
            continue
        if m.side == "cmp":
            gap = (h - a) / ((h + a) / 2) if h + a else 0.0
            if m.favours not in ("h", "a") or abs(gap) < 0.25 or (m.favours == "h") != (gap > 0):
                continue
            strength = abs(gap) / 2
        else:
            exp = h + a if m.side == "t" else h if m.side == "h" else a
            avg = c.league_avg if m.side == "t" else c.league_home if m.side == "h" else c.league_away
            signal = exp / avg - 1 if avg else 0.0
            if abs(signal) < config.COUNT_MIN_SIGNAL or (m.direction == "over") != (signal > 0):
                continue
            strength = abs(signal)
        reason = f"oczekiwane {name}: {h + a:.1f} ({h:.1f} – {a:.1f}) vs średnia ligi {c.league_avg:.1f}"
        if c.referee_factor:
            reason += f", sędzia ×{c.referee_factor:.2f}"
        out.append(Pick(pred, e, name, strength, reason))
    return out


def select_picks(pred: Prediction, evals: list[MarketEval]) -> list[Pick]:
    if not pred.enough_data:
        return []
    chosen: list[Pick] = []
    for cands in (
        _value_candidates(pred, evals) if config.VALUE_PICKS_ENABLED else [],
        *(_count_candidates(pred, evals, kind) for kind in COUNT_KINDS),
        _model_candidates(pred, evals),
    ):
        if cands:
            # z każdej grupy tylko najlepszy typ, żeby nie dublować tej samej myśli
            chosen.append(max(cands, key=lambda c: (c.score, -abs(c.ev.prob - 0.7))))
    chosen.sort(key=lambda c: (c.kind != "value", -c.score))
    return chosen[: config.MAX_PICKS_PER_MATCH]
