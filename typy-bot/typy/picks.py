"""Wybór typów: z dziesiątek rynków zostawiamy tylko te, w które model naprawdę wierzy."""
from __future__ import annotations

from dataclasses import dataclass

from . import config
from .markets import MarketEval
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
        if e.market.kind not in ("ft", "ht") or e.odds or e.prob_model is None:
            continue
        if e.market.group == "1X2":
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
    lam = pred.cards if kind == "cards" else pred.corners
    avg = pred.cards_league_avg if kind == "cards" else pred.corners_league_avg
    if not lam or not avg:
        return []
    total = sum(lam)
    signal = total / avg - 1
    out = []
    for e in evals:
        if e.market.kind != kind:
            continue
        p = e.prob
        if not (config.COUNT_MIN_PROB <= p <= config.COUNT_MAX_PROB):
            continue
        key = e.market.key
        if key in ("C_1", "C_2", "K_1", "K_2"):
            h, a = lam
            side_gap = (h - a) / ((h + a) / 2)
            if abs(side_gap) < 0.25 or (key.endswith("1") != (side_gap > 0)):
                continue
            strength = abs(side_gap) / 2
        else:
            team_market = key[1] in "HA"
            if team_market:
                side_lam = lam[0] if key[1] == "H" else lam[1]
                side_sig = side_lam / (avg / 2) - 1
            else:
                side_sig = signal
            over = "_O" in key
            if abs(side_sig) < config.COUNT_MIN_SIGNAL or (over != (side_sig > 0)):
                continue
            strength = abs(side_sig)
        name = "kartek" if kind == "cards" else "rożnych"
        reason = f"oczekiwane {total:.1f} {name} vs średnia ligi {avg:.1f}"
        if kind == "cards" and pred.referee_factor:
            reason += f", sędzia ×{pred.referee_factor:.2f}"
        out.append(Pick(pred, e, "kartki" if kind == "cards" else "rożne", strength, reason))
    return out


def select_picks(pred: Prediction, evals: list[MarketEval]) -> list[Pick]:
    if not pred.enough_data:
        return []
    chosen: list[Pick] = []
    for cands in (
        _value_candidates(pred, evals) if config.VALUE_PICKS_ENABLED else [],
        _count_candidates(pred, evals, "cards"),
        _count_candidates(pred, evals, "corners"),
        _model_candidates(pred, evals),
    ):
        if cands:
            # z każdej grupy tylko najlepszy typ, żeby nie dublować tej samej myśli
            chosen.append(max(cands, key=lambda c: (c.score, -abs(c.ev.prob - 0.7))))
    chosen.sort(key=lambda c: (c.kind != "value", -c.score))
    return chosen[: config.MAX_PICKS_PER_MATCH]
