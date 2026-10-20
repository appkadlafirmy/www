"""Pobieranie i wczytywanie darmowych danych z football-data.co.uk."""
from __future__ import annotations

import csv
import io
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config

UK = ZoneInfo("Europe/London")
PL = ZoneInfo("Europe/Warsaw")


@dataclass
class Match:
    div: str
    date: date
    home: str
    away: str
    hg: int
    ag: int
    hthg: int | None = None
    htag: int | None = None
    hxg: float | None = None
    axg: float | None = None
    hs: int | None = None
    as_: int | None = None
    hcards: int | None = None
    acards: int | None = None
    hc: int | None = None
    ac: int | None = None
    hst: int | None = None
    ast: int | None = None
    hf: int | None = None
    af: int | None = None
    hr: int | None = None
    ar: int | None = None
    referee: str | None = None
    odds: dict[str, float] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, date, str, str]:
        return (self.div, self.date, self.home, self.away)

    def stat(self, kind: str) -> tuple[int, int] | None:
        """Statystyka meczu (gospodarze, goście), np. stat("corners"); None, gdy brak danych."""
        h, a = (getattr(self, f) for f in COUNT_FIELDS[kind])
        return None if h is None or a is None else (h, a)


# Statystyki liczone tak samo jak kartki: (pole gospodarzy, pole gości)
COUNT_FIELDS = {
    "cards": ("hcards", "acards"),
    "reds": ("hr", "ar"),
    "corners": ("hc", "ac"),
    "sot": ("hst", "ast"),
    "shots": ("hs", "as_"),
    "fouls": ("hf", "af"),
}


@dataclass
class Fixture:
    div: str
    kickoff: datetime  # czas polski
    home: str
    away: str
    referee: str | None
    odds: dict[str, float]
    aliases: tuple[str, ...] = ()   # inne nazwy do wyszukiwania (np. „PSG”)
    home_div: str | None = None     # w pucharach: liga, w której gra gospodarz
    away_div: str | None = None

    @property
    def date(self) -> date:
        return self.kickoff.astimezone(UK).date()

    @property
    def key(self) -> tuple[str, date, str, str]:
        return (self.div, self.date, self.home, self.away)

    @property
    def id(self) -> str:
        return f"{self.div}|{self.date.isoformat()}|{self.home}|{self.away}"


# ---------------------------------------------------------------- pobieranie

def _fetch(url: str, path: Path, max_age_s: float | None) -> Path:
    if path.exists() and (max_age_s is None or time.time() - path.stat().st_mtime < max_age_s):
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (typy-bot)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read()
    except Exception:
        if path.exists():  # brak sieci: użyj starej kopii
            return path
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def season_code(d: date) -> str:
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def previous_seasons(d: date, n: int) -> list[str]:
    start = d.year if d.month >= 7 else d.year - 1
    return [f"{(start - i) % 100:02d}{(start - i + 1) % 100:02d}" for i in range(n)]


def _read_csv(path: Path) -> list[dict[str, str]]:
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    return [row for row in csv.DictReader(io.StringIO(text)) if any(row.values())]


def _int(v: str | None) -> int | None:
    try:
        return int(float(v)) if v not in (None, "") else None
    except ValueError:
        return None


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def _parse_date(s: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _odds_from_row(row: dict[str, str], closing: bool = False) -> dict[str, float]:
    """Średnie kursy rynku (Avg), a gdy ich brak lub są błędne — Bet365 albo Pinnacle.

    W danych źródłowych zdarzają się pomyłki (np. 1.97 i 4.32 na dwie strony
    handicapu), więc każdy zestaw kursów musi mieć realną marżę bukmachera.
    """
    c = "C" if closing else ""
    out: dict[str, float] = {}
    markets = [
        (("1", "X", "2"), [(f"{s}{c}H", f"{s}{c}D", f"{s}{c}A") for s in ("Avg", "B365", "PS")]),
        (("O2.5", "U2.5"), [(f"{s}{c}>2.5", f"{s}{c}<2.5") for s in ("Avg", "B365", "P")]),
        (("AHH", "AHA"), [(f"{s}{c}AHH", f"{s}{c}AHA") for s in ("Avg", "B365", "P")]),
    ]
    for keys, sources in markets:
        for cols in sources:
            vals = [_float(row.get(col)) for col in cols]
            if not all(v and v > 1.0 for v in vals):
                continue
            overround = sum(1 / v for v in vals)
            if 0.99 <= overround <= (1.16 if len(vals) == 3 else 1.12):
                out.update(zip(keys, vals))
                break
    ah = _float(row.get("AHCh" if closing else "AHh"))
    if ah is not None and "AHH" in out:
        out["AH_LINE"] = ah
    else:
        out.pop("AHH", None), out.pop("AHA", None)
    return out


def _kickoff(d: date, t: str | None) -> datetime:
    hh, mm = 15, 0
    if t and ":" in t:
        try:
            hh, mm = (int(x) for x in t.strip().split(":")[:2])
        except ValueError:
            pass
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=UK).astimezone(PL)


# ---------------------------------------------------------------- wyniki

def _main_matches(div: str, path: Path) -> list[Match]:
    out = []
    for row in _read_csv(path):
        d = _parse_date(row.get("Date", ""))
        hg, ag = _int(row.get("FTHG")), _int(row.get("FTAG"))
        if not d or hg is None or ag is None or not row.get("HomeTeam"):
            continue
        hy, ay, hr, ar = (_int(row.get(k)) for k in ("HY", "AY", "HR", "AR"))
        out.append(Match(
            div=div, date=d, home=row["HomeTeam"].strip(), away=row["AwayTeam"].strip(),
            hg=hg, ag=ag, hthg=_int(row.get("HTHG")), htag=_int(row.get("HTAG")),
            hxg=_float(row.get("HxG")), axg=_float(row.get("AxG")),
            hs=_int(row.get("HS")), as_=_int(row.get("AS")),
            hcards=None if hy is None else hy + (hr or 0),
            acards=None if ay is None else ay + (ar or 0),
            hc=_int(row.get("HC")), ac=_int(row.get("AC")),
            hst=_int(row.get("HST")), ast=_int(row.get("AST")),
            hf=_int(row.get("HF")), af=_int(row.get("AF")), hr=hr, ar=ar,
            referee=(row.get("Referee") or "").strip() or None,
            odds=_odds_from_row(row) or _odds_from_row(row, closing=True),
        ))
    return out


def _extra_matches(div: str, path: Path, since: date) -> list[Match]:
    out = []
    for row in _read_csv(path):
        d = _parse_date(row.get("Date", ""))
        hg, ag = _int(row.get("HG")), _int(row.get("AG"))
        if not d or d < since or hg is None or ag is None:
            continue
        out.append(Match(div=div, date=d, home=row["Home"].strip(), away=row["Away"].strip(),
                         hg=hg, ag=ag, odds=_odds_from_row(row, closing=True)))
    return out


def load_matches(today: date | None = None, seasons: int = 3,
                 divs: list[str] | None = None) -> dict[str, list[Match]]:
    """Wyniki z ostatnich sezonów, pogrupowane po lidze."""
    today = today or date.today()
    current = season_code(today)
    result: dict[str, list[Match]] = {}
    for div in divs or list(config.MAIN_LEAGUES) + list(config.EXTRA_LEAGUES):
        matches: list[Match] = []
        try:
            if div in config.MAIN_LEAGUES:
                for s in previous_seasons(today, seasons):
                    path = config.DATA_DIR / "seasons" / s / f"{div}.csv"
                    age = 6 * 3600 if s == current else None
                    try:
                        _fetch(f"{config.BASE_URL}/mmz4281/{s}/{div}.csv", path, age)
                    except Exception:
                        continue
                    matches += _main_matches(div, path)
            else:
                path = config.DATA_DIR / "extra" / f"{div}.csv"
                _fetch(f"{config.BASE_URL}/new/{div}.csv", path, 6 * 3600)
                matches = _extra_matches(div, path, today - timedelta(days=365 * seasons))
        except Exception:
            continue
        if matches:
            result[div] = sorted(matches, key=lambda m: m.date)
    return result


# ---------------------------------------------------------------- terminarz

def load_fixtures(max_age_s: float = 2 * 3600) -> list[Fixture]:
    """Nadchodzące mecze z kursami (football-data aktualizuje je kilka razy w tygodniu)."""
    fixtures: list[Fixture] = []
    main = _fetch(f"{config.BASE_URL}/fixtures.csv", config.DATA_DIR / "fixtures.csv", max_age_s)
    for row in _read_csv(main):
        div = (row.get("Div") or "").strip()
        d = _parse_date(row.get("Date", ""))
        if div not in config.MAIN_LEAGUES or not d:
            continue
        fixtures.append(Fixture(div=div, kickoff=_kickoff(d, row.get("Time")),
                                home=row["HomeTeam"].strip(), away=row["AwayTeam"].strip(),
                                referee=(row.get("Referee") or "").strip() or None,
                                odds=_odds_from_row(row)))
    try:
        extra = _fetch(f"{config.BASE_URL}/new_league_fixtures.csv",
                       config.DATA_DIR / "new_league_fixtures.csv", max_age_s)
        for row in _read_csv(extra):
            div = config.COUNTRY_TO_EXTRA.get((row.get("Country") or "").strip())
            d = _parse_date(row.get("Date", ""))
            if not div or not d:
                continue
            fixtures.append(Fixture(div=div, kickoff=_kickoff(d, row.get("Time")),
                                    home=row["Home"].strip(), away=row["Away"].strip(),
                                    referee=None, odds=_odds_from_row(row)))
    except Exception:
        pass
    now = datetime.now(PL) - timedelta(hours=2)
    return sorted((f for f in fixtures if f.kickoff >= now), key=lambda f: f.kickoff)
