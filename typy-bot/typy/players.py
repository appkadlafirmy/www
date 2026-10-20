"""Forma zawodników i typy na zawodników (strzeli gola, strzały, strzały celne, kartka, faule).

Dane: statystyki każdego zawodnika z ostatnich meczów jego drużyny (liga + puchary) z publicznego
API ESPN. Dla każdego zawodnika liczymy:
  • czy gra (ile ostatnich meczów zagrał, ile od początku, ile minut średnio),
  • ile strzałów / strzałów celnych / goli / fauli / kartek na 90 minut (ze ściągnięciem do średniej
    dla jego pozycji, żeby 1 dobry mecz nie robił z obrońcy snajpera),
  • a potem dopasowujemy to do konkretnego meczu: ile strzałów i goli ma oddać jego drużyna
    według modelu meczu (słaby rywal = więcej strzałów).
Gdy ESPN poda już składy (ok. godzinę przed meczem), bierzemy prawdziwy skład.
"""
from __future__ import annotations

import gzip
import json
import math
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import config
from .data import Match
from .model import negbin_pmf

API = "https://site.api.espn.com/apis/site/v2/sports/soccer/all"
EVENTS_DIR = config.DATA_DIR / "espn_events"
SCHED_DIR = config.DATA_DIR / "espn_schedules"
RECENT_MATCHES = 8
STAT_KEYS = ("goals", "shots", "sot", "fouls", "yellows", "assists")

# Średnie na 90 minut dla pozycji — punkt odniesienia przy małej liczbie minut.
POSITION_PRIOR = {
    "F": {"goals": 0.33, "shots": 2.4, "sot": 0.95, "fouls": 1.1, "yellows": 0.13, "assists": 0.12},
    "M": {"goals": 0.10, "shots": 1.1, "sot": 0.38, "fouls": 1.2, "yellows": 0.18, "assists": 0.10},
    "D": {"goals": 0.04, "shots": 0.55, "sot": 0.15, "fouls": 1.0, "yellows": 0.17, "assists": 0.05},
    "G": {"goals": 0.0, "shots": 0.0, "sot": 0.0, "fouls": 0.05, "yellows": 0.04, "assists": 0.0},
}
# Ile minut „przeciętnego zawodnika na tej pozycji” dokładamy do danych każdego gracza. Dobrane testem na
# Premier League i LaLiga (styczeń–maj 2026): przy mniejszych wartościach model przeceniał zawodników
# w świetnej formie (typy 62–85% wchodziły o 4 pkt. proc. rzadziej, strzelec gola o 8 pkt.).
PRIOR_MINUTES = {"goals": 1200, "assists": 1200}
PRIOR_MINUTES_DEFAULT = 700
SHOTS_DISPERSION = 1.6


# ---------------------------------------------------------------- pobieranie

def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return json.loads(body)
    except Exception:
        return {}


def _position_group(abbr: str) -> str:
    a = (abbr or "").upper()
    if a.startswith("G"):
        return "G"
    if a in ("F", "CF", "ST", "LF", "RF", "CF-L", "CF-R", "LW", "RW", "SS") or a.startswith(("CF", "F")):
        return "F"
    if a.startswith(("CD", "CB", "LB", "RB", "D", "LWB", "RWB", "SW")):
        return "D"
    return "M"


def _parse_summary(d: dict) -> dict | None:
    """Z pełnej odpowiedzi ESPN zostawiamy tylko to, co potrzebne (mały plik w pamięci podręcznej)."""
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    status = ((comp.get("status") or {}).get("type") or {})
    rosters = d.get("rosters") or []
    if not rosters:
        return None
    sub_out: dict[str, float] = {}
    sub_in: dict[str, float] = {}
    sent_off: dict[str, float] = {}
    for k in d.get("keyEvents") or []:
        text = (k.get("type") or {}).get("text", "")
        minute = ((k.get("clock") or {}).get("value") or 0) / 60
        parts = [((p.get("athlete") or {}).get("id")) for p in k.get("participants") or []]
        if "Substitution" in text and len(parts) >= 2:
            sub_in[parts[0]] = minute
            sub_out[parts[1]] = minute
        elif "Red Card" in text and parts:
            sent_off[parts[0]] = minute
    teams = {}
    for t in rosters:
        team_id = (t.get("team") or {}).get("id")
        players = []
        for p in t.get("roster") or []:
            ath = p.get("athlete") or {}
            st = {s.get("name"): s.get("value") or 0 for s in p.get("stats") or []}
            pid = ath.get("id")
            played = bool(st.get("appearances")) or p.get("starter")
            if p.get("starter"):
                minutes = min(sub_out.get(pid, 90), sent_off.get(pid, 90))
            elif played:
                minutes = max(5.0, min(sent_off.get(pid, 90), 90) - sub_in.get(pid, 75))
            else:
                minutes = 0.0
            players.append({
                "id": pid, "name": ath.get("displayName") or ath.get("fullName") or "?",
                "pos": _position_group((p.get("position") or {}).get("abbreviation", "")),
                "starter": bool(p.get("starter")), "minutes": round(minutes, 1),
                "goals": st.get("totalGoals", 0), "shots": st.get("totalShots", 0),
                "sot": st.get("shotsOnTarget", 0), "fouls": st.get("foulsCommitted", 0),
                "yellows": st.get("yellowCards", 0), "assists": st.get("goalAssists", 0),
            })
        teams[team_id] = players
    # wynik i statystyki drużyn — do rozliczania meczów, których nie ma w football-data (puchary)
    score, side = {}, {}
    for c in comp.get("competitors") or []:
        tid = (c.get("team") or {}).get("id")
        side[c.get("homeAway")] = tid
        halves = [int(float(l.get("displayValue") or 0)) for l in c.get("linescores") or []]
        try:
            score[tid] = [int(float(c.get("score") or 0)), halves[0] if halves else None]
        except ValueError:
            pass
    team_stats = {}
    for t in (d.get("boxscore") or {}).get("teams") or []:
        st = {x.get("name"): x.get("displayValue") for x in t.get("statistics") or []}
        team_stats[(t.get("team") or {}).get("id")] = {
            k: _int(st.get(name)) for k, name in (("cards", "yellowCards"), ("reds", "redCards"),
                                                  ("corners", "wonCorners"), ("shots", "totalShots"),
                                                  ("sot", "shotsOnTarget"), ("fouls", "foulsCommitted"))}
    return {"completed": bool(status.get("completed")), "date": comp.get("date"), "teams": teams,
            "home_id": side.get("home"), "away_id": side.get("away"), "score": score, "team_stats": team_stats}


def _int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def match_from_event(event_id: str, div: str, home: str, away: str) -> Match | None:
    """Zakończony mecz z ESPN w formie, jakiej używa rozliczanie (wynik, połowy, statystyki)."""
    ev = event(event_id, max_age_s=600)
    if not ev or not ev.get("completed") or not ev.get("home_id"):
        return None
    h, a = ev["home_id"], ev["away_id"]
    (hg, hthg), (ag, htag) = ev["score"].get(h, [None, None]), ev["score"].get(a, [None, None])
    if hg is None or ag is None:
        return None
    hs, as_ = ev["team_stats"].get(h, {}), ev["team_stats"].get(a, {})

    def both(k):
        return hs.get(k), as_.get(k)

    hy, ay = both("cards")
    hr, ar = both("reds")
    return Match(div=div, date=datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).date(), home=home,
                 away=away, hg=hg, ag=ag, hthg=hthg, htag=htag, hs=hs.get("shots"), as_=as_.get("shots"),
                 hcards=None if hy is None else hy + (hr or 0), acards=None if ay is None else ay + (ar or 0),
                 hc=hs.get("corners"), ac=as_.get("corners"), hst=hs.get("sot"), ast=as_.get("sot"),
                 hf=hs.get("fouls"), af=as_.get("fouls"), hr=hr, ar=ar)


def event(event_id: str, max_age_s: float | None = None) -> dict | None:
    """Statystyki zawodników z meczu. Zakończone mecze trzymamy na dysku na zawsze."""
    path = EVENTS_DIR / f"{event_id}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        if (cached.get("completed") and "home_id" in cached) or (max_age_s and time.time() - path.stat().st_mtime < max_age_s):
            return cached
    parsed = _parse_summary(_get(f"{API}/summary?event={event_id}"))
    if parsed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(parsed))
    return parsed


def team_schedule(team_id: str, season: int | None = None) -> list[dict]:
    """Zakończone mecze drużyny (bez sparingów), od najstarszego."""
    path = SCHED_DIR / f"{team_id}_{season or 'now'}.json"
    if path.exists() and (season or time.time() - path.stat().st_mtime < 6 * 3600):
        return json.loads(path.read_text())
    url = f"{API}/teams/{team_id}/schedule" + (f"?season={season}" if season else "")
    out = []
    for e in _get(url).get("events") or []:
        league = (e.get("league") or {}).get("slug", "") if isinstance(e.get("league"), dict) else ""
        comp = (e.get("competitions") or [{}])[0]
        if "friendly" in league or not ((comp.get("status") or {}).get("type") or {}).get("completed"):
            continue
        out.append({"id": e["id"], "date": e["date"], "league": league})
    out.sort(key=lambda e: e["date"])
    if out or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
    return out


def recent_events(team_id: str, before: datetime, n: int = RECENT_MATCHES) -> list[str]:
    iso = before.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    start = before.year if before.month >= 7 else before.year - 1
    seen: dict[str, dict] = {}
    for season in (None, start, start - 1):
        for e in team_schedule(team_id, season):
            if e["date"] < iso:
                seen[e["id"]] = e
        if len(seen) >= n:
            break
    events = sorted(seen.values(), key=lambda e: e["date"])
    return [e["id"] for e in events[-n:]]


# ---------------------------------------------------------------- forma zawodnika

@dataclass
class PlayerForm:
    id: str
    name: str
    pos: str
    team_id: str
    apps: int = 0                  # mecze z ostatnich RECENT_MATCHES, w których zagrał
    starts: int = 0
    minutes: float = 0.0
    totals: dict[str, float] = field(default_factory=lambda: {k: 0.0 for k in STAT_KEYS})
    last5: list[str] = field(default_factory=list)  # np. „⚽ 2 strz.” w każdym z ostatnich 5 meczów
    p_play: float = 0.0            # szansa, że zagra
    exp_minutes: float = 0.0       # ile minut zagra, jeśli zagra
    lineup: str | None = None      # "start" / "ławka", gdy znany skład

    def rate90(self, stat: str) -> float:
        prior = POSITION_PRIOR[self.pos][stat]
        k = PRIOR_MINUTES.get(stat, PRIOR_MINUTES_DEFAULT)
        return (self.totals[stat] + prior * k / 90) / ((self.minutes + k) / 90)


@dataclass
class TeamForm:
    team_id: str
    matches: int
    per_match: dict[str, float]    # średnio na mecz: gole, strzały... całej drużyny
    players: list[PlayerForm]


def team_form(team_id: str, before: datetime, lineup: list[dict] | None = None) -> TeamForm | None:
    ids = recent_events(team_id, before)
    with ThreadPoolExecutor(max_workers=8) as pool:
        events = [e for e in pool.map(event, ids) if e and team_id in e["teams"]]
    if len(events) < 3:
        return None
    forms: dict[str, PlayerForm] = {}
    team_tot = {k: 0.0 for k in STAT_KEYS}
    for i, ev in enumerate(events):
        recent = i >= len(events) - 5
        for p in ev["teams"][team_id]:
            for k in STAT_KEYS:
                team_tot[k] += p[k]
            if not p["id"]:
                continue
            f = forms.setdefault(p["id"], PlayerForm(p["id"], p["name"], p["pos"], team_id))
            f.name, f.pos = p["name"], p["pos"]
            if p["minutes"] <= 0:
                if recent:
                    f.last5.append("–")
                continue
            f.apps += 1
            f.starts += p["starter"]
            f.minutes += p["minutes"]
            for k in STAT_KEYS:
                f.totals[k] += p[k]
            if recent:
                tag = "⚽" * int(p["goals"]) or f"{int(p['shots'])}s"
                f.last5.append(tag)
    n = len(events)
    last = events[-5:]
    for f in forms.values():
        played_recent = [p for ev in last for p in ev["teams"][team_id] if p["id"] == f.id and p["minutes"] > 0]
        f.p_play = len(played_recent) / len(last)
        f.exp_minutes = sum(p["minutes"] for p in played_recent) / len(played_recent) if played_recent else 0.0
    if lineup:
        _apply_lineup(forms, lineup, team_id)
    return TeamForm(team_id, n, {k: v / n for k, v in team_tot.items()}, list(forms.values()))


def _apply_lineup(forms: dict[str, PlayerForm], lineup: list[dict], team_id: str) -> None:
    """Znany skład: wyjściowa jedenastka gra na pewno, rezerwowi może wejdą, reszty nie ma."""
    in_squad = set()
    for p in lineup:
        pid = p["id"]
        in_squad.add(pid)
        f = forms.setdefault(pid, PlayerForm(pid, p["name"], p["pos"], team_id))
        if p["starter"]:
            f.lineup, f.p_play = "start", 1.0
            f.exp_minutes = max(f.exp_minutes, 75.0) if f.starts else 75.0
        else:
            f.lineup = "ławka"
            f.p_play = min(0.6, max(f.p_play, 0.2))
            f.exp_minutes = 22.0
    for pid, f in forms.items():
        if pid not in in_squad:
            f.p_play = 0.0


def lineups(event_id: str) -> dict[str, list[dict]]:
    """Składy na nadchodzący mecz, jeśli ESPN już je podał (inaczej pusto)."""
    ev = event(event_id, max_age_s=15 * 60)
    if not ev:
        return {}
    return {tid: ps for tid, ps in ev["teams"].items() if sum(p["starter"] for p in ps) >= 11}


# ---------------------------------------------------------------- rynki na zawodników

@dataclass
class PlayerMarket:
    key: str          # np. "P:12345:goals:0.5"
    label: str
    player: PlayerForm
    stat: str
    prob: float       # szansa, JEŚLI zagra (gdy nie zagra, bukmacher zwraca stawkę)
    expected: float   # oczekiwana liczba (gole/strzały...) w tym meczu

    @property
    def fair_odds(self) -> float:
        return 1 / self.prob if self.prob > 0 else float("inf")


PLAYER_LINES = {
    "goals": [(0.5, "strzeli gola")],
    "shots": [(0.5, "min. 1 strzał"), (1.5, "min. 2 strzały"), (2.5, "min. 3 strzały"), (3.5, "min. 4 strzały")],
    "sot": [(0.5, "min. 1 strzał celny"), (1.5, "min. 2 strzały celne"), (2.5, "min. 3 strzały celne")],
    "yellows": [(0.5, "dostanie kartkę")],
    "fouls": [(0.5, "min. 1 faul"), (1.5, "min. 2 faule")],
    "assists": [(0.5, "asysta")],
}


def _p_over(mean: float, line: float, dispersion: float) -> float:
    k = int(line)  # P(X > line) = 1 - P(X <= k)
    pmf = negbin_pmf(mean, dispersion, max(10, k + 1))
    return float(1 - pmf[: k + 1].sum())


def player_markets(tf: TeamForm, team_goals: float | None, team_shots: float | None,
                   team_fouls: float | None = None, referee_factor: float | None = None,
                   max_players: int = 14) -> list[PlayerMarket]:
    """Rynki na zawodników jednej drużyny w tym meczu."""
    factors = {
        "goals": _factor(team_goals, tf.per_match["goals"]),
        "assists": _factor(team_goals, tf.per_match["goals"]),
        "shots": _factor(team_shots, tf.per_match["shots"]),
        "sot": _factor(team_shots, tf.per_match["shots"]),
        "fouls": _factor(team_fouls, tf.per_match["fouls"]),
        "yellows": referee_factor or 1.0,
    }
    likely = sorted((p for p in tf.players if p.p_play > 0 and p.pos != "G"),
                    key=lambda p: (-p.p_play * p.exp_minutes, p.name))[:max_players]
    out = []
    for p in likely:
        for stat, lines in PLAYER_LINES.items():
            mean = p.rate90(stat) * p.exp_minutes / 90 * factors[stat]
            for line, text in lines:
                if stat in ("goals", "yellows", "assists"):
                    p_if_plays = 1 - math.exp(-mean)
                else:
                    p_if_plays = _p_over(mean, line, SHOTS_DISPERSION)
                if p_if_plays < 0.03:
                    continue
                out.append(PlayerMarket(f"P:{p.id}:{stat}:{line}", f"{p.name} – {text}", p, stat,
                                        p_if_plays, mean))
    return out


def _factor(expected: float | None, average: float) -> float:
    """O ile w tym meczu drużyna ma oddać więcej/mniej (strzałów, goli) niż zwykle."""
    if not expected or average <= 0:
        return 1.0
    return min(1.6, max(0.6, expected / average))


def settle_player(key: str, event_id: str) -> tuple[float, float] | None:
    """Rozlicza typ na zawodnika po meczu. None = mecz się nie skończył albo brak danych."""
    try:
        _, pid, stat, line = key.split(":")
    except ValueError:
        return None
    ev = event(event_id, max_age_s=600)
    if not ev or not ev.get("completed"):
        return None
    for players in ev["teams"].values():
        for p in players:
            if p["id"] == pid:
                if p["minutes"] <= 0:
                    return (0.0, 0.0)  # nie zagrał — u większości bukmacherów zwrot stawki
                return (1.0, 0.0) if p[stat] > float(line) else (0.0, 1.0)
    return (0.0, 0.0)
