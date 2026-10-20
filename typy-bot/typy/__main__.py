"""Uruchamianie z terminala:

    python -m typy bot              uruchom bota Telegrama
    python -m typy typy             pokaż typy dnia w terminalu
    python -m typy mecz Arsenal     analiza meczu drużyny
    python -m typy test 2025 E0     test na historii (sezon 2025/26, Premier League)
    python -m typy test-zawodnicy   test typów na zawodników (Premier League + LaLiga)
"""
import re
import sys

from . import backtest


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def main() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "pomoc"
    if cmd == "bot":
        from .bot import main as bot_main
        bot_main()
    elif cmd == "typy":
        from .engine import Engine
        from .report import picks_text
        print(_plain(picks_text(Engine().best_picks(), "Typy dnia")))
    elif cmd == "mecz" and len(args) > 1:
        from .engine import Engine
        from .report import analysis_text
        e = Engine()
        found = e.find(" ".join(args[1:]))
        if not found:
            print("Nie znaleziono meczu.")
        for fx in found[:3]:
            a = e.analyse(fx)
            print(_plain(analysis_text(a)) if a else f"{fx.home} – {fx.away}: za mało danych")
            print("-" * 60)
    elif cmd == "test":
        backtest.main(args[1:])
    elif cmd == "test-zawodnicy":
        from . import player_backtest
        player_backtest.main(args[1:])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
