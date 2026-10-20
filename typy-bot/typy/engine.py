"""Łączy dane, model i wybór typów w jedną całość (z pamięcią podręczną)."""
from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import logging

from . import config, data, espn, players
from .markets import MarketEval, evaluate
from .model import LeagueModel, Prediction, fit_league, predict, predict_cup
from .picks import Pick, select_picks


log = logging.getLogger("typy")


@dataclass
class Analysis:
    pred: Prediction
    evals: list[MarketEval]
    picks: list[Pick]
    players: list[players.PlayerMarket] = field(default_factory=list)
    lineups_known: bool = False


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
            # dane wszystkich lig: potrzebne też do meczów pucharowych
            self.matches = data.load_matches()
            try:
                fixtures = data.load_fixtures(max_age_s=0 if force else 2 * 3600)
            except Exception:
                fixtures = []
            if config.ESPN_FIXTURES:
                teams = {div: {t for m in ms for t in (m.home, m.away)} for div, ms in self.matches.items()}
                fixtures = _merge(fixtures, espn.cached_fixtures(espn.TeamMatcher(teams),
                                                                 max_age_s=0 if force else 2 * 3600))
            self.fixtures = sorted(fixtures, key=lambda f: f.kickoff)
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
        with self._lock:
            key = (div, ref)
            if key not in self._models:
                matches = self.matches.get(div)
                if not matches:
                    return None
                self._models[key] = fit_league(matches, ref)
            return self._models[key]

    def team_models(self, fx: data.Fixture) -> tuple[LeagueModel | None, LeagueModel | None]:
        """Modele lig obu drużyn (w lidze to ten sam model, w pucharze zwykle dwa różne)."""
        if fx.div in config.CUPS:
            return (self.model_for(fx.home_div, fx.date) if fx.home_div else None,
                    self.model_for(fx.away_div, fx.date) if fx.away_div else None)
        model = self.model_for(fx.div, fx.date)
        return model, model

    def predict(self, fx: data.Fixture) -> Prediction | None:
        home_model, away_model = self.team_models(fx)
        if fx.div in config.CUPS:
            return predict_cup(home_model, away_model, fx)
        return predict(home_model, fx) if home_model else None

    def remember(self, fx: data.Fixture, analysis: Analysis) -> None:
        with self._lock:
            self._analyses[fx.id] = analysis

    def analyse(self, fx: data.Fixture) -> Analysis | None:
        # bez blokady na czas liczenia: statystyki zawodników idą z sieci i mogą chwilę potrwać
        if fx.id in self._analyses:
            return self._analyses[fx.id]
        result = None
        pred = self.predict(fx)
        if pred:
            evals = evaluate(pred)
            player_markets, known = self.player_markets(fx, pred)
            result = Analysis(pred, evals, select_picks(pred, evals, player_markets), player_markets, known)
        self._analyses[fx.id] = result
        return result

    def player_markets(self, fx: data.Fixture, pred: Prediction,
                       use_lineups: bool = True) -> tuple[list[players.PlayerMarket], bool]:
        """Rynki na zawodników obu drużyn (pusto, gdy ESPN nie ma tego meczu)."""
        if not (fx.espn_id and fx.espn_home_id and fx.espn_away_id):
            return [], False
        try:
            squads = players.lineups(fx.espn_id) if use_lineups else {}
            out = []
            for i, team_id in enumerate((fx.espn_home_id, fx.espn_away_id)):
                tf = players.team_form(team_id, fx.kickoff, squads.get(team_id))
                if not tf:
                    continue
                shots, fouls, cards = (pred.counts.get(k) for k in ("shots", "fouls", "cards"))
                out += players.player_markets(
                    tf, team_goals=pred.lam[i], team_shots=shots.lam[i] if shots else None,
                    team_fouls=fouls.lam[i] if fouls else None,
                    referee_factor=cards.referee_factor if cards else None)
            return out, bool(squads)
        except Exception:  # brak statystyk zawodników nie może zepsuć analizy meczu
            log.exception("Statystyki zawodników: %s", fx.id)
            return [], False

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
        t = espn.normalize(text)
        if not t:
            return []

        def names(f: data.Fixture) -> list[str]:
            return [f.home, f.away, *f.aliases]

        exact = [f for f in self.fixtures if any(espn.normalize(n) == t for n in names(f))]
        if exact:
            return exact
        return [f for f in self.fixtures if any(t in espn.normalize(n) for n in names(f))]


def _merge(main: list[data.Fixture], extra: list[data.Fixture]) -> list[data.Fixture]:
    """Łączy terminarz football-data (dokładniejsze średnie kursy, sędziowie) z ESPN (pełny)."""
    by_key = {f.id: f for f in main}
    for f in extra:
        same = by_key.get(f.id) or next(
            (g for g in main if g.div == f.div and g.date == f.date and (g.home == f.home or g.away == f.away)),
            None)
        if same:
            same.aliases = same.aliases + f.aliases
            same.espn_id, same.espn_home_id, same.espn_away_id = f.espn_id, f.espn_home_id, f.espn_away_id
            for k, v in f.odds.items():
                same.odds.setdefault(k, v)
        else:
            by_key[f.id] = f
    return list(by_key.values())
