"""Pełny terminarz (ligi + puchary europejskie) i kursy z publicznego API ESPN.

football-data.co.uk aktualizuje terminarz tylko we wtorki i piątki i nie ma pucharów,
więc w środku tygodnia brakowało dużych meczów. ESPN ma wszystko na kilka dni do przodu.
Uwaga: to nieoficjalne (nieudokumentowane) API — bierzemy z niego tylko terminarz i kursy.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher

from . import config
from .data import PL, Fixture

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={day}"

# slug ESPN -> nasz kod ligi
LEAGUES = {
    "uefa.champions": "UCL", "uefa.europa": "UEL", "uefa.europa.conf": "UECL",
    "eng.1": "E0", "eng.2": "E1", "eng.3": "E2", "eng.4": "E3",
    "esp.1": "SP1", "esp.2": "SP2", "ger.1": "D1", "ger.2": "D2",
    "ita.1": "I1", "ita.2": "I2", "fra.1": "F1", "fra.2": "F2",
    "ned.1": "N1", "por.1": "P1", "sco.1": "SC0", "bel.1": "B1", "tur.1": "T1", "gre.1": "G1",
    "aut.1": "AUT", "sui.1": "SWZ", "den.1": "DNK", "nor.1": "NOR", "swe.1": "SWE",
    "usa.1": "USA", "mex.1": "MEX", "bra.1": "BRA", "arg.1": "ARG", "jpn.1": "JPN",
    "chn.1": "CHN", "rus.1": "RUS", "rou.1": "ROU", "irl.1": "IRL", "fin.1": "FIN",
}

# Nazwy, których nie da się dopasować automatycznie (ESPN -> football-data).
ALIASES = {
    "paris saint germain": "Paris SG", "manchester city": "Man City", "manchester united": "Man United",
    "newcastle united": "Newcastle", "tottenham hotspur": "Tottenham", "wolverhampton wanderers": "Wolves",
    "nottingham forest": "Nott'm Forest", "brighton hove albion": "Brighton", "west ham united": "West Ham",
    "leeds united": "Leeds", "sheffield wednesday": "Sheffield Weds", "sheffield united": "Sheffield United",
    "atletico madrid": "Ath Madrid", "athletic club": "Ath Bilbao", "celta vigo": "Celta",
    "espanyol": "Espanol", "real sociedad": "Sociedad", "rayo vallecano": "Vallecano",
    "real betis": "Betis", "deportivo alaves": "Alaves", "borussia monchengladbach": "M'gladbach",
    "bayern munich": "Bayern Munich", "bayer leverkusen": "Leverkusen", "eintracht frankfurt": "Ein Frankfurt",
    "internazionale": "Inter", "ac milan": "Milan", "as roma": "Roma", "hellas verona": "Verona",
    "sporting cp": "Sp Lisbon", "sporting braga": "Sp Braga", "fc porto": "Porto",
    "psv eindhoven": "PSV Eindhoven", "feyenoord rotterdam": "Feyenoord", "az alkmaar": "AZ Alkmaar",
    "club brugge": "Club Brugge", "royal antwerp": "Antwerp", "union st gilloise": "St. Gilloise",
    "olympique marseille": "Marseille", "olympique lyonnais": "Lyon", "as monaco": "Monaco",
    "stade rennais": "Rennes", "rb leipzig": "RB Leipzig", "fc koln": "FC Koln",
    "1 fc union berlin": "Union Berlin", "fenerbahce": "Fenerbahce", "besiktas": "Besiktas",
    "olympiacos": "Olympiakos", "paok salonika": "PAOK", "celtic": "Celtic", "rangers": "Rangers",
    "peterborough united": "Peterboro", "urawa red diamonds": "Urawa Reds", "f c kobenhavn": "FC Copenhagen",
    "fc kobenhavn": "FC Copenhagen", "borussia dortmund": "Dortmund", "sporting lisbon": "Sp Lisbon",
    "braga": "Sp Braga", "heart of midlothian": "Hearts", "sint truidense": "St Truiden",
    "kaa gent": "Gent", "rb salzburg": "Salzburg", "lask linz": "LASK", "aek athens": "AEK",
    "nec nijmegen": "Nijmegen", "mjallby aif": "Mjallby", "jagiellonia bialystok": "Jagiellonia",
    "legia warsaw": "Legia", "lech poznan": "Lech Poznan", "rakow czestochowa": "Rakow",
}

# Słowa, które ESPN dodaje do nazwy, a football-data pomija (np. „Borussia Dortmund” = „Dortmund”).
# Tylko takie różnice akceptujemy w pucharach — inaczej „Inter Club d'Escaldes” stałby się Interem.
SAFE_EXTRA = {"borussia", "olympique", "real", "sporting", "bayer", "stade", "athletic", "united", "city",
              "calcio", "hotspur", "albion", "wanderers", "rotterdam", "eindhoven", "amsterdam", "lisbon",
              "salonika", "prague", "praha", "zagreb", "glasgow"}

# W pucharach grają kluby z najwyższych lig — nie szukamy ich w niższych (np. Red Star z Francji
# to nie Crvena Zvezda).
TOP_DIVS = {"E0", "SP1", "D1", "I1", "F1", "N1", "P1", "B1", "T1", "G1", "SC0", "POL", "AUT", "SWZ",
            "DNK", "NOR", "SWE", "ROU", "RUS", "IRL", "FIN"}

STOP = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "us", "cd", "ud", "sd", "rc", "rcd", "fk", "sk",
        "club", "de", "vfb", "vfl", "tsg", "1", "sv", "bk", "if", "ca", "cr", "ec", "se", "the", "and"}


_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "Æ": "AE", "ß": "ss", "ł": "l", "Ł": "L",
                           "đ": "d", "Đ": "D", "ı": "i"})


def _plain(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.translate(_TRANSLIT)).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.replace("&", " ")).split())


def normalize(name: str) -> str:
    return " ".join(w for w in _plain(name).split() if w not in STOP)


def american_to_decimal(ml) -> float | None:
    try:
        v = float(ml)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1 + v / 100, 3) if v > 0 else round(1 + 100 / abs(v), 3)


class TeamMatcher:
    """Dopasowuje nazwy z ESPN do nazw w danych historycznych (football-data)."""

    def __init__(self, teams_by_div: dict[str, set[str]]):
        self.teams_by_div = teams_by_div
        self.all = {t: d for d, ts in teams_by_div.items() for t in ts}
        self.norm = {t: normalize(t) for t in self.all}

    def match(self, espn_name: str, div: str | None) -> tuple[str, str] | None:
        """Zwraca (nazwa w danych, liga) albo None. div=None oznacza puchar."""
        cup = div is None
        if cup:
            candidates = {t for d in TOP_DIVS for t in self.teams_by_div.get(d, ())}
        else:
            candidates = self.teams_by_div.get(div) or set()
        n = normalize(espn_name)
        for key in (_plain(espn_name), n):
            alias = ALIASES.get(key)
            if alias and alias in candidates:
                return alias, self.all[alias]
        best, best_score = None, 0.0
        for t in candidates:
            tn = self.norm[t]
            if not tn:
                continue
            if tn == n:
                return t, self.all[t]
            words_t, words_n = set(tn.split()), set(n.split())
            if cup:
                # tylko: nazwa z danych + „bezpieczne” słowa (Borussia, Real...)
                if words_t < words_n and words_n - words_t <= SAFE_EXTRA:
                    return t, self.all[t]
                continue
            score = SequenceMatcher(None, tn, n).ratio()
            if words_t <= words_n or words_n <= words_t:
                score = max(score, 0.9)
            if score > best_score:
                best, best_score = t, score
        return (best, self.all[best]) if best and best_score >= 0.8 else None


def _get(slug: str, day: date) -> dict:
    url = URL.format(slug=slug, day=day.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return json.loads(body)
    except Exception:
        return {}


def _odds(comp: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for o in comp.get("odds") or []:
        if not isinstance(o, dict):
            continue
        ml = o.get("moneyline") or {}

        def close(side: str):
            return ((ml.get(side) or {}).get("close") or {}).get("odds")

        h = american_to_decimal(close("home") or (o.get("homeTeamOdds") or {}).get("moneyLine"))
        a = american_to_decimal(close("away") or (o.get("awayTeamOdds") or {}).get("moneyLine"))
        d = american_to_decimal(close("draw") or (o.get("drawOdds") or {}).get("moneyLine"))
        if h and a and d and 0.99 <= 1 / h + 1 / a + 1 / d <= 1.16:
            out.update({"1": h, "X": d, "2": a})
        total = o.get("total") or {}
        line = o.get("overUnder")
        ov = american_to_decimal(((total.get("over") or {}).get("close") or {}).get("odds"))
        un = american_to_decimal(((total.get("under") or {}).get("close") or {}).get("odds"))
        if line and ov and un and 0.99 <= 1 / ov + 1 / un <= 1.12:
            out.update({f"O{float(line)}": ov, f"U{float(line)}": un})
        if out:
            break
    return out


def load_fixtures(matcher: TeamMatcher, days: int = 4) -> list[Fixture]:
    today = datetime.now(PL).date()
    jobs = [(slug, today + timedelta(days=i)) for slug in LEAGUES for i in range(days)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = list(pool.map(lambda j: (j[0], _get(*j)), jobs))
    fixtures = []
    now = datetime.now(PL) - timedelta(hours=2)
    for slug, page in pages:
        div = LEAGUES[slug]
        cup = div in config.CUPS
        for ev in page.get("events", []):
            try:
                fx = _fixture(ev, div, cup, matcher, now)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue  # niekompletne dane jednego meczu nie mogą zepsuć całego terminarza
            if fx:
                fixtures.append(fx)
    return fixtures


def _fixture(ev: dict, div: str, cup: bool, matcher: TeamMatcher, now: datetime) -> Fixture | None:
    comp = (ev.get("competitions") or [{}])[0]
    state = ((comp.get("status") or {}).get("type") or {}).get("state")
    if state not in (None, "pre"):  # trwa albo się skończył
        return None
    teams = {c.get("homeAway"): c.get("team") or {} for c in comp.get("competitors", [])}
    if "home" not in teams or "away" not in teams:
        return None
    kickoff = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).astimezone(PL)
    if kickoff < now:
        return None
    names, divs, aliases = [], [], []
    for side in ("home", "away"):
        t = teams[side]
        shown = t.get("displayName") or t.get("name") or "?"
        m = matcher.match(shown, None if cup else div)
        names.append(m[0] if m else shown)
        divs.append(m[1] if m else None)
        aliases += [shown, t.get("shortDisplayName") or "", t.get("abbreviation") or ""]
    return Fixture(div=div, kickoff=kickoff, home=names[0], away=names[1], referee=None,
                   odds=_odds(comp), aliases=tuple(a for a in aliases if a),
                   home_div=divs[0], away_div=divs[1], espn_id=str(ev.get("id") or "") or None,
                   espn_home_id=teams["home"].get("id"), espn_away_id=teams["away"].get("id"))


_cache: tuple[float, list[Fixture]] | None = None


def cached_fixtures(matcher: TeamMatcher, max_age_s: float = 2 * 3600) -> list[Fixture]:
    global _cache
    if _cache and time.time() - _cache[0] < max_age_s:
        return _cache[1]
    fixtures = load_fixtures(matcher)
    if fixtures or not _cache:
        _cache = (time.time(), fixtures)
    return _cache[1]
