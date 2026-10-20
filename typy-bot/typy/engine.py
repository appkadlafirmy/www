"""Łączy dane, model i wybór typów w jedną całość (z pamięcią podręczną)."""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import config, data
from .markets import MarketEval, evaluate
from .model import LeagueModel, Prediction, fit_league, predict
from .picks import Pick, select_picks


@dataclass
class Analysis:
    pred: Prediction
    evals: list[MarketEval]
    picks: list[Pick]


class Engine:
    def __init__(self, refresh_s: float = 3 * 3600):
        self.refresh_s = refresh_s
        self._loaded_at = 0.0
        self.matches: dict[str, list[data.Match]] = {}
        self.fixtures: list[data.Fixture] = []
        self._models: dict[tuple[str, date], LeagueModel] = {}
        self._analyses: dict[str, Analysis | None] = {}
        self._lock = threading.RLock()

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            if not force and time.time() - self._loaded_at < self.refresh_s:
                return
            fixtures = data.load_fixtures(max_age_s=0 if force else 2 * 3600)
            unique = {f.id: f for f in fixtures}
            self.fixtures = sorted(unique.values(), key=lambda f: f.kickoff)
            divs = sorted({f.div for f in self.fixtures})
            self.matches = data.load_matches(divs=divs)
            self._models.clear()
            self._analyses.clear()
            self._loaded_at = time.time()

    @staticmethod
    def short_id(fx: data.Fixture) -> str:
        return hashlib.sha1(fx.id.encode()).hexdigest()[:10]

    def by_short_id(self, sid: str) -> data.Fixture | None:
        return next((f for f in self.fixtures if self.short_id(f) == sid), None)

    def upcoming(self, hours: float = 72) -> list[data.Fixture]:
        self.refresh()
        limit = datetime.now(data.PL) + timedelta(hours=hours)
        return [f for f in self.fixtures if f.kickoff <= limit]

    def model_for(self, div: str, ref: date) -> LeagueModel | None:
        key = (div, ref)
        if key not in self._models:
            matches = self.matches.get(div)
            if not matches:
                return None
            self._models[key] = fit_league(matches, ref)
        return self._models[key]

    def analyse(self, fx: data.Fixture) -> Analysis | None:
        with self._lock:
            if fx.id in self._analyses:
                return self._analyses[fx.id]
            result = None
            model = self.model_for(fx.div, fx.date)
            if model:
                pred = predict(model, fx)
                if pred:
                    evals = evaluate(pred)
                    result = Analysis(pred, evals, select_picks(pred, evals))
            self._analyses[fx.id] = result
            return result

    def best_picks(self, hours: float = 36, limit: int = config.DAILY_MAX_PICKS) -> list[Pick]:
        """Najmocniejsze typy na najbliższe godziny — maks. 1 typ z meczu, różne mecze."""
        now = datetime.now(data.PL)
        best: list[Pick] = []
        for fx in self.upcoming(hours):
            if fx.kickoff < now:
                continue
            a = self.analyse(fx)
            if a and a.picks:
                best.append(max(a.picks, key=lambda p: (p.stars, p.score)))
        best.sort(key=lambda p: (-p.stars, -p.score))
        return best[:limit]

    def find(self, text: str) -> list[data.Fixture]:
        self.refresh()
        t = text.lower().strip()
        return [f for f in self.fixtures if t in f.home.lower() or t in f.away.lower()]
