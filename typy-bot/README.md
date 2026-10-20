# Typy Bot — bot z typami piłkarskimi na Telegramie

Bot co dzień analizuje mecze z ok. 38 lig i wysyła tylko te typy, w które model naprawdę wierzy.
Działa za 0 zł: dane są z darmowego serwisu [football-data.co.uk](https://www.football-data.co.uk),
a obliczenia robi własny model statystyczny (bez płatnego AI).

## Co bierze pod uwagę

| Czynnik | Skąd |
|---|---|
| Siła ataku i obrony każdej drużyny (gole + xG), z naciskiem na ostatnie mecze | wyniki z 3 sezonów |
| Przewaga własnego boiska | osobno dla każdej ligi |
| Forma: ostatnie 5 meczów, gole, xG, kartki, rożne | wyniki |
| Mecze bezpośrednie | wyniki |
| Tabela i motywacja (mistrzostwo / puchary / utrzymanie / „nie gra o nic”) | liczona z wyników |
| Kartki: skłonność drużyny do kartek + jak „prowokuje” rywali + **sędzia** | 22 ligi europejskie |
| Rzuty rożne: ile drużyna wywalcza i ile oddaje rywalom | 22 ligi europejskie |
| Kursy bukmacherów (1X2, over/under 2.5, handicap) | do kalibracji modelu |

**Czego nie ma w darmowych danych:** kontuzji, składów, zawieszeń z ostatniej chwili.
Bot o tym przypomina przy każdej analizie.

## Rynki

1X2 · podwójna szansa · zakład bez remisu · BTTS · gole 0.5–4.5 · gole drużyny · handicap azjatycki
(-2.5 do +2.5, także ćwiartki) · handicap europejski · 1. połowa · kombinacje (np. 1 + over 1.5) ·
kartki łącznie i drużyny · więcej kartek · rożne łącznie i drużyny · więcej rożnych.

Pełną wycenę wszystkich rynków widać w bocie pod przyciskiem **📋 Wszystkie rynki**.

## Analiza na żywo

Po wybraniu meczu bot pokazuje jedną wiadomość, która aktualizuje się krok po kroku (ok. 7 s):
pasek postępu ▰▰▰▱▱▱▱, a pod nim prawdziwe wyniki każdego etapu — liczba meczów w danych, forma,
oczekiwane gole (model vs kursy), tabela, kartki/sędzia/rożne, liczba przeliczonych rynków i wybrane typy.
Na końcu ta sama wiadomość zamienia się w pełną analizę. Tempo zmienisz w `LIVE_STEP_DELAY` (`typy/bot.py`).

## Jak bot wybiera typy (i dlaczego tak)

Model sprawdziliśmy na historii: typował mecze sezonów 2024/25 i 2025/26, znając tylko wcześniejsze wyniki
(ok. 11 300 meczów w 18 ligach). Wnioski:

- **Na 1X2, handicapie z kursem i over/under 2.5 bukmacherzy są lepsi niż model.** Typy „value” na tych rynkach
  traciły 11–17%, więc są wyłączone (`VALUE_PICKS_ENABLED = False` w `typy/config.py`).
- **Prawdopodobieństwa kartek, rożnych, BTTS, goli drużyn i handicapów są trafne:** np. kartki — model mówił 72%,
  wchodziło 72%; gole — 73–74% vs 73–75%. To główna siła bota.
- Dlatego każdy typ ma **„graj przy kursie ≥ X”**: jeśli Twój bukmacher daje co najmniej tyle, zakład się opłaca.
  Jeśli mniej — odpuść. Rynki poboczne (kartki, rożne, gole drużyny) bukmacherzy wyceniają zwykle mniej
  starannie niż 1X2 — tam najłatwiej o kurs wyższy niż nasz minimalny.

Typ trafia na listę tylko, gdy:
- 🟨/🚩 **kartki/rożne**: mecz odstaje od średniej ligi o min. 15% (np. ostry sędzia, drużyny faulujące), szansa 62–85%;
- ⚽ **gole/BTTS/handicapy**: nasz model daje min. 4 pkt. proc. więcej niż wynika z kursów (ale nie więcej niż 12 — większa różnica to zwykle dziura w danych), szansa 62–85%;
- drużyny mają dość meczów w danych.

Z jednego meczu maks. 3 typy, a w „Typach dnia” maks. 10 najmocniejszych (po 1 z meczu).
Wszystkie progi są w `typy/config.py`.

Każdy pokazany typ zapisuje się w bazie i rozlicza automatycznie po meczu — komenda **📈 Skuteczność**
pokazuje uczciwą historię. To najlepszy argument sprzedażowy.

## Uruchomienie (Windows / Mac / Linux)

1. Zainstaluj [Pythona 3.11+](https://www.python.org/downloads/) (na Windows zaznacz „Add Python to PATH”).
2. Utwórz bota: na Telegramie napisz do **@BotFather** → `/newbot` → podaj nazwę → dostaniesz **token**.
3. W folderze `typy-bot`:
   ```
   pip install -r requirements.txt
   ```
4. Skopiuj `.env.example` jako `.env` i wpisz token (`TELEGRAM_TOKEN=...`).
   Swój numer ID (do komend admina) sprawdzisz u **@userinfobot** → wpisz w `ADMIN_IDS`.
5. Start:
   ```
   python -m typy bot
   ```
   Napisz do swojego bota `/start`.

Bez Telegrama (podgląd w terminalu):
```
python -m typy typy             # typy dnia
python -m typy mecz Arsenal     # analiza meczu
python -m typy test 2025 E0 SP1 # test na historii (sezon 2025/26)
python -m unittest              # testy
```

## Sprzedaż

- `FREE_MODE=1` — wszyscy widzą wszystko (na start, żeby zebrać historię skuteczności).
- `FREE_MODE=0` — bez premium: 1 typ dnia + analizy bez typów. Premium: wszystko.
- Płatność przez **Telegram Stars** (`/premium`) — bez firmy płatniczej, cena w `PREMIUM_PRICE_STARS`.
  Kupujący płaci za 250 gwiazdek ok. 20 zł, Ty po prowizjach dostajesz mniej (orientacyjnie ok. 60%).
  Gwiazdki wypłacisz przez Fragment (w kryptowalucie TON) albo wydasz na reklamę w Telegramie.
  Aktualne stawki sprawdź w dokumentacji Telegrama.
- Ręczne nadanie premium: `/admin_premium ID 30`. Statystyki: `/admin_staty`. Wysłanie typów teraz: `/admin_wyslij`.
- Codziennie o `DAILY_HOUR` (domyślnie 10:00) bot sam wysyła typy wszystkim, którzy mają włączone `/powiadomienia`.

**Bot musi działać 24/7**, więc zamiast własnego komputera użyj serwera: darmowy Oracle Cloud Free Tier
albo tani VPS (ok. 15–20 zł/mies.).

**Prawo:** w Polsce reklama zakładów jest mocno ograniczona (ustawa o grach hazardowych), nie wolno
promować nielegalnych bukmacherów ani obiecywać pewnych wygranych. Przed sprzedażą skonsultuj
regulamin i sposób promocji z prawnikiem.

## Ligi

Pełne dane (gole, xG, kartki, rożne, sędzia, kursy): Anglia 1–5, Szkocja 1–4, Niemcy 1–2, Włochy 1–2,
Hiszpania 1–2, Francja 1–2, Holandia, Belgia, Portugalia, Turcja, Grecja.

Gole + kursy 1X2: **Polska (Ekstraklasa)**, Argentyna, Austria, Brazylia, Chiny, Dania, Finlandia,
Irlandia, Japonia, Meksyk, Norwegia, Rumunia, Rosja, Szwecja, Szwajcaria, USA.

Brak: Ligi Mistrzów i innych pucharów (nie ma ich w darmowych danych). Gdy bot zacznie zarabiać,
można podpiąć płatne API (np. API-Football) z kontuzjami, składami i pucharami — źródło danych
jest w jednym pliku `typy/data.py`.

## Struktura

```
typy/
  config.py    ustawienia, ligi, progi
  data.py      pobieranie danych (cache w data/)
  model.py     model siły drużyn, kartek, rożnych, sędziów, tabela, forma
  markets.py   definicje wszystkich rynków + rozliczanie
  picks.py     wybór typów
  engine.py    łączy wszystko
  report.py    teksty wiadomości
  store.py     baza SQLite (użytkownicy, typy, płatności)
  bot.py       bot Telegrama
  backtest.py  test na historii
```
