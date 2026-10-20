"""Wybór typów: z dziesiątek rynków zostawiamy tylko te, w które model naprawdę wierzy."""
from __future__ import annotations

from dataclasses import dataclass

from . import config
from .markets import COUNT_KINDS, MarketDef, MarketEval
from .model import Prediction

# Korekty z historii trafień bota: o ile punktów procentowych model przecenia dany rodzaj typów.
# Klucz: "rodzaj|liga" albo "rodzaj|puchar". Uzupełnia je bot z bazy rozliczonych typów (store.calibration).
CALIBRATION: dict[str, float] = {}


def calibration_key(kind: str, div: str) -> str:
    return f"{kind}|{'puchar' if div in config.CUPS else 'liga'}"


@dataclass
class Pick:
    pred: Prediction
    ev: MarketEval
    kind: str      # "value" (lepszy kurs niż rynek), "model", "zawodnik", "kartki", "rożne"...
    score: float   # do sortowania: im wyżej, tym mocniejszy typ
    reason: str

    @property
    def gap(self) -> float:
        return CALIBRATION.get(calibration_key(self.kind, self.pred.fixture.div), 0.0)

    @property
    def prob(self) -> float:
        """Szansa po korekcie z historii trafień (to pokazujemy użytkownikowi)."""
        return max(0.01, self.ev.prob - self.gap)

    @property
    def min_odds(self) -> float:
        """Poniżej tego kursu nie warto grać."""
        return round(max(1.01, config.SAFETY_MARGIN * self.ev.fair_odds * self.ev.prob / self.prob), 2)

    def value_at(self, odds: float) -> float:
        """Oczekiwany zysk na 1 zł stawki przy danym kursie (zwroty stawki pominięte)."""
        return self.prob * (odds - 1) - (1 - self.prob)

    @property
    def stars(self) -> int:
        """Siła sygnału: ★ słaby, ★★ wyraźny, ★★★ mocny."""
        if self.kind == "value":
            edge = self.ev.ev(self.ev.odds)
            return 3 if edge >= 0.10 else 2 if edge >= 0.06 else 1
        if self.kind == "model":
            return 3 if self.score >= 0.10 else 2 if self.score >= 0.07 else 1
        if self.kind == "zawodnik":
            return 3 if self.score >= 0.12 else 2 if self.score >= 0.06 else 1
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


def _player_candidates(pred: Prediction, markets: list) -> list[Pick]:
    """Typy na zawodników: tylko pewniacy do składu i tylko rynki sprawdzone na historii
    (strzały, strzały celne, faule; strzelec gola od 38%)."""
    out = []
    for pm in markets:
        p = pm.player
        # Test LM: model przeceniał, czy zawodnik zagra (91% vs 82%) — typujemy dopiero po składach.
        if p.lineup != "start" and (config.PLAYER_PICKS_NEED_LINEUP or p.p_play < 0.8):
            continue
        if pm.stat == "goals":
            if pm.prob < config.PLAYER_GOAL_MIN_PROB:
                continue
            score = pm.prob - config.PLAYER_GOAL_MIN_PROB
        elif pm.stat in ("shots", "sot", "fouls"):
            if not (config.PLAYER_MIN_PROB <= pm.prob <= config.PLAYER_MAX_PROB):
                continue
            score = pm.prob - config.PLAYER_MIN_PROB
        else:
            continue
        team = pred.fixture.home if p.team_id == pred.fixture.espn_home_id else pred.fixture.away
        market = MarketDef(pm.key, pm.label, "Zawodnicy", "player", settle=lambda *a: (0.0, 0.0))
        ev = MarketEval(market, f"{pm.label} ({team})", win=pm.prob, lose=1 - pm.prob)
        form = " ".join(p.last5) if p.last5 else "brak"
        lineup = "w składzie" if p.lineup == "start" else "regularnie gra"
        reason = f"forma (⚽ gol, 3s = 3 strzały): {form} · {lineup} · oczekiwane: {pm.expected:.2f}"
        out.append(Pick(pred, ev, "zawodnik", score, reason))
    return out


def _min_prob(p: Pick) -> float:
    """Próg po korekcie z historii — gdy rodzaj typów trafia gorzej, niż obiecywał, odpada więcej typów."""
    if p.ev.market.key.endswith(":goals:0.5"):
        return config.PLAYER_GOAL_MIN_PROB
    return min(config.MODEL_MIN_PROB, config.COUNT_MIN_PROB, config.PLAYER_MIN_PROB)


def select_picks(pred: Prediction, evals: list[MarketEval], player_markets: list | None = None) -> list[Pick]:
    if not pred.enough_data:
        return []
    chosen: list[Pick] = []
    cup = pred.fixture.div in config.CUPS
    for cands in (
        _player_candidates(pred, player_markets or []),
        _value_candidates(pred, evals) if config.VALUE_PICKS_ENABLED else [],
        *(_count_candidates(pred, evals, kind) for kind in COUNT_KINDS),
        _model_candidates(pred, evals),
    ):
        cands = [c for c in cands
                 if not (cup and c.kind in config.CUP_DISABLED_KINDS) and c.prob >= _min_prob(c)]
        if cands:
            # z każdej grupy tylko najlepszy typ, żeby nie dublować tej samej myśli
            chosen.append(max(cands, key=lambda c: (c.score, -abs(c.ev.prob - 0.7))))
    chosen.sort(key=lambda c: (c.kind != "value", -c.score))
    return chosen[: config.MAX_PICKS_PER_MATCH]
