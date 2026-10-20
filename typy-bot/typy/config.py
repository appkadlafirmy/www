"""Ustawienia bota: ligi, progi wyboru typów, zmienne środowiskowe."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "typy.sqlite3"


def _load_env_file() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
FREE_MODE = os.environ.get("FREE_MODE", "1") == "1"
PREMIUM_PRICE_STARS = int(os.environ.get("PREMIUM_PRICE_STARS", "250"))
PREMIUM_DAYS = int(os.environ.get("PREMIUM_DAYS", "30"))
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "10"))

BASE_URL = "https://football-data.co.uk"

# Ligi z pełnymi statystykami (wyniki, xG, strzały, kartki, rożne, sędzia, kursy).
MAIN_LEAGUES = {
    "E0": ("Anglia", "Premier League"),
    "E1": ("Anglia", "Championship"),
    "E2": ("Anglia", "League One"),
    "E3": ("Anglia", "League Two"),
    "EC": ("Anglia", "National League"),
    "SC0": ("Szkocja", "Premiership"),
    "SC1": ("Szkocja", "Championship"),
    "SC2": ("Szkocja", "League One"),
    "SC3": ("Szkocja", "League Two"),
    "D1": ("Niemcy", "Bundesliga"),
    "D2": ("Niemcy", "2. Bundesliga"),
    "I1": ("Włochy", "Serie A"),
    "I2": ("Włochy", "Serie B"),
    "SP1": ("Hiszpania", "LaLiga"),
    "SP2": ("Hiszpania", "LaLiga 2"),
    "F1": ("Francja", "Ligue 1"),
    "F2": ("Francja", "Ligue 2"),
    "N1": ("Holandia", "Eredivisie"),
    "B1": ("Belgia", "Pro League"),
    "P1": ("Portugalia", "Liga Portugal"),
    "T1": ("Turcja", "Süper Lig"),
    "G1": ("Grecja", "Super League"),
}

# Ligi z samymi wynikami i kursami 1X2 (bez kartek i rożnych).
EXTRA_LEAGUES = {
    "POL": ("Polska", "Ekstraklasa", "Poland"),
    "ARG": ("Argentyna", "Liga Profesional", "Argentina"),
    "AUT": ("Austria", "Bundesliga", "Austria"),
    "BRA": ("Brazylia", "Serie A", "Brazil"),
    "CHN": ("Chiny", "Super League", "China"),
    "DNK": ("Dania", "Superliga", "Denmark"),
    "FIN": ("Finlandia", "Veikkausliiga", "Finland"),
    "IRL": ("Irlandia", "Premier Division", "Ireland"),
    "JPN": ("Japonia", "J1 League", "Japan"),
    "MEX": ("Meksyk", "Liga MX", "Mexico"),
    "NOR": ("Norwegia", "Eliteserien", "Norway"),
    "ROU": ("Rumunia", "Liga I", "Romania"),
    "RUS": ("Rosja", "Premier Liga", "Russia"),
    "SWE": ("Szwecja", "Allsvenskan", "Sweden"),
    "SWZ": ("Szwajcaria", "Super League", "Switzerland"),
    "USA": ("USA", "MLS", "USA"),
}

COUNTRY_TO_EXTRA = {v[2]: k for k, v in EXTRA_LEAGUES.items()}


def league_name(div: str) -> str:
    if div in MAIN_LEAGUES:
        country, name = MAIN_LEAGUES[div]
    elif div in EXTRA_LEAGUES:
        country, name, _ = EXTRA_LEAGUES[div]
    else:
        return div
    return f"{country} · {name}"


# --- Model ---
GOALS_HALF_LIFE_DAYS = 365     # jak szybko „starzeją się” stare mecze
COUNTS_HALF_LIFE_DAYS = 365    # to samo dla kartek i rożnych
XG_WEIGHT = 0.5                # ile xG (vs. prawdziwe gole) przy ocenie siły drużyny
MODEL_WEIGHT = 0.2             # ile naszego modelu vs. kursów rynku (test: rynek jest trafniejszy)
DIXON_COLES_RHO = -0.08        # korekta częstości niskich wyników (0:0, 1:1)
MIN_TEAM_MATCHES = 5           # minimum meczów drużyny w danych, by dawać typy

# --- Wybór typów ---
# Test na sezonach 2024/25 i 2025/26 (12 lig): typy „value” na 1X2, handicap i over/under 2.5
# traciły 11–17%, bo te rynki bukmacherzy wyceniają lepiej niż model. Domyślnie wyłączone.
VALUE_PICKS_ENABLED = False
# Kartki i rożne: dodatkowa niepewność. Bez niej model był o 1–4 pkt. proc. zbyt pewny siebie;
# z 1.25 przewidywania zgadzają się z rzeczywistością (np. 76% vs 77% trafień).
COUNT_DISPERSION_BOOST = 1.25
VALUE_MIN_EDGE = 0.04          # min. przewaga nad kursem bukmachera (4%)
VALUE_MIN_PROB = 0.30
VALUE_ODDS_RANGE = (1.30, 4.50)
MODEL_MIN_PROB = 0.62          # typy bez kursu w danych: min. prawdopodobieństwo
MODEL_MAX_PROB = 0.85
MODEL_MIN_DISAGREEMENT = 0.04  # o ile nasz model musi „wierzyć bardziej” niż rynek
MODEL_MAX_DISAGREEMENT = 0.12  # większa różnica = podejrzane dane, pomijamy
COUNT_MIN_PROB = 0.62          # kartki / rożne
COUNT_MAX_PROB = 0.85
COUNT_MIN_SIGNAL = 0.15        # mecz musi odbiegać od średniej ligi o min. 15%
SAFETY_MARGIN = 1.05           # minimalny kurs = 1.05 / prawdopodobieństwo
MAX_PICKS_PER_MATCH = 3
DAILY_MAX_PICKS = 10           # ile typów dnia wysyłamy (najmocniejsze)
FREE_DAILY_PICKS = 1           # ile z nich widzi użytkownik bez premium
