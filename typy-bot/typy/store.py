"""Baza SQLite: użytkownicy (premium, powiadomienia) i historia wysłanych typów."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

from . import config
from .data import Match
from .markets import settle
from .picks import Pick

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    name TEXT,
    premium_until TEXT,
    notify INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    div TEXT NOT NULL,
    match_date TEXT NOT NULL,
    kickoff TEXT NOT NULL,
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    market TEXT NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL,
    prob REAL NOT NULL,
    min_odds REAL NOT NULL,
    result TEXT,
    UNIQUE (div, match_date, home, away, market)
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    charge_id TEXT,
    created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path=config.DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------ użytkownicy

    def touch_user(self, user_id: int, chat_id: int, name: str) -> None:
        self.db.execute(
            "INSERT INTO users (user_id, chat_id, name, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id, name = excluded.name",
            (user_id, chat_id, name, datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def is_premium(self, user_id: int) -> bool:
        if config.FREE_MODE or user_id in config.ADMIN_IDS:
            return True
        row = self.db.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and row["premium_until"] and row["premium_until"] >= date.today().isoformat())

    def premium_until(self, user_id: int) -> str | None:
        row = self.db.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row["premium_until"] if row else None

    def add_premium(self, user_id: int, days: int) -> str:
        current = self.premium_until(user_id)
        start = max(date.today(), date.fromisoformat(current)) if current else date.today()
        until = (start + timedelta(days=days)).isoformat()
        self.db.execute("INSERT INTO users (user_id, chat_id, created_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(user_id) DO NOTHING",
                        (user_id, user_id, datetime.now().isoformat(timespec="seconds")))
        self.db.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (until, user_id))
        self.db.commit()
        return until

    def record_payment(self, user_id: int, stars: int, charge_id: str) -> None:
        self.db.execute("INSERT INTO payments (user_id, stars, charge_id, created_at) VALUES (?, ?, ?, ?)",
                        (user_id, stars, charge_id, datetime.now().isoformat(timespec="seconds")))
        self.db.commit()

    def set_notify(self, user_id: int, on: bool) -> None:
        self.db.execute("UPDATE users SET notify = ? WHERE user_id = ?", (int(on), user_id))
        self.db.commit()

    def notify_enabled(self, user_id: int) -> bool:
        row = self.db.execute("SELECT notify FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return bool(row and row["notify"])

    def subscribers(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM users WHERE notify = 1").fetchall()

    def user_count(self) -> tuple[int, int]:
        total = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        prem = self.db.execute("SELECT COUNT(*) FROM users WHERE premium_until >= ?",
                               (date.today().isoformat(),)).fetchone()[0]
        return total, prem

    # ------------------------------------------------------------ typy

    def save_picks(self, picks: list[Pick]) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        for p in picks:
            fx = p.pred.fixture
            self.db.execute(
                "INSERT OR IGNORE INTO picks (created_at, div, match_date, kickoff, home, away, market, "
                "label, kind, prob, min_odds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (now, fx.div, fx.date.isoformat(), fx.kickoff.isoformat(), fx.home, fx.away,
                 p.ev.market.key, p.ev.label, p.kind, p.ev.prob, p.min_odds))
        self.db.commit()

    def settle_open(self, results: dict[str, list[Match]]) -> int:
        """Rozlicza typy, których mecze już się odbyły. Zwraca liczbę rozliczonych."""
        index = {m.key: m for ms in results.values() for m in ms}
        done = 0
        for row in self.db.execute("SELECT * FROM picks WHERE result IS NULL").fetchall():
            m = index.get((row["div"], date.fromisoformat(row["match_date"]), row["home"], row["away"]))
            if not m:
                continue
            res = settle(row["market"], m.hg, m.ag, m.hthg, m.htag, m.hcards, m.acards, m.hc, m.ac)
            if res is None:
                result = "void"
            else:
                w, l = res
                result = "push" if w == l else "won" if w > l else "lost"
            self.db.execute("UPDATE picks SET result = ? WHERE id = ?", (result, row["id"]))
            done += 1
        self.db.commit()
        return done

    def stats(self) -> dict:
        rows = self.db.execute(
            "SELECT * FROM picks WHERE result IN ('won', 'lost', 'push') ORDER BY kickoff").fetchall()
        won = sum(r["result"] == "won" for r in rows)
        lost = sum(r["result"] == "lost" for r in rows)
        push = sum(r["result"] == "push" for r in rows)
        decided = [r for r in rows if r["result"] != "push"]
        profit = sum((r["min_odds"] - 1) if r["result"] == "won" else -1 for r in decided)
        by_kind: dict[str, dict] = {}
        for r in decided:
            k = by_kind.setdefault(r["kind"], {"n": 0, "won": 0})
            k["n"] += 1
            k["won"] += r["result"] == "won"
        return {
            "settled": len(rows), "won": won, "lost": lost, "push": push,
            "hit_rate": won / len(decided) if decided else 0.0,
            "avg_prob": sum(r["prob"] for r in decided) / len(decided) if decided else 0.0,
            "roi": profit / len(decided) if decided else 0.0,
            "by_kind": by_kind,
            "recent": [dict(r) for r in rows[-10:]],
        }
