"""Teksty wiadomości po polsku (format HTML Telegrama). Zasada: krótko, najważniejsze na górze,
szczegóły pod przyciskami („👤 Zawodnicy”, „📋 Wszystkie rynki”)."""
from __future__ import annotations

from datetime import datetime, timedelta
from html import escape

from . import config
from .data import PL, Fixture
from .engine import Analysis
from .markets import COUNT_KINDS
from .picks import Pick

DAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
KIND_ICON = {"value": "💰", "model": "⚽", "zawodnik": "👤", **{name: icon for name, icon, _ in COUNT_KINDS.values()}}
FORM_ICON = {"Z": "🟢", "R": "🟡", "P": "🔴"}

DISCLAIMER = "<i>18+ · graj odpowiedzialnie, tylko u legalnych bukmacherów.</i>"
ODDS_HINT = "<i>„kurs od” = najniższy kurs, przy którym warto grać. Niższy u bukmachera? Odpuść.</i>"


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Telegram przyjmuje maks. 4096 znaków — dzielimy po pustych liniach (tagi HTML nie
    przechodzą przez puste linie, więc każda część jest poprawna)."""
    parts, current = [], ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > limit:
            cut = block.rfind("\n", 0, limit)
            cut = cut if cut > 0 else limit
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        current = block
    if current:
        parts.append(current)
    return parts


def when(fx: Fixture) -> str:
    """„dziś 21:00”, „jutro 18:30” albo „sob 24.10 15:00”."""
    k = fx.kickoff
    today = datetime.now(PL).date()
    if k.date() == today:
        day = "dziś"
    elif k.date() == today + timedelta(days=1):
        day = "jutro"
    else:
        day = f"{DAYS[k.weekday()]} {k:%d.%m}"
    return f"{day} {k:%H:%M}"


def plural(n: int, one: str, few: str, many: str) -> str:
    """Polska odmiana: 1 rynek, 3 rynki, 5 rynków."""
    if n == 1:
        return f"{n} {one}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {few}"
    return f"{n} {many}"


def stars(n: int) -> str:
    return "★" * n + "☆" * (3 - n)


def form_icons(results: str) -> str:
    return "".join(FORM_ICON.get(r, "⚪") for r in results)


def match_title(fx: Fixture) -> str:
    return f"<b>{escape(fx.home)} – {escape(fx.away)}</b>"


def pick_body(p: Pick) -> str:
    """Dwie linijki: co grać, i ile to warte."""
    return (f"{KIND_ICON.get(p.kind, '•')} {escape(p.ev.label)}\n"
            f"<b>{p.ev.prob:.0%}</b> · kurs od <b>{p.min_odds:.2f}</b> · {stars(p.stars)}")


def picks_text(picks: list[Pick], title: str, locked: int = 0) -> str:
    if not picks:
        return (f"<b>{title}</b>\n\nNa razie brak typów, w które model wierzy. "
                "Lepiej nie grać niż grać na siłę.")
    parts = [f"<b>{title}</b>"]
    for i, p in enumerate(picks, 1):
        fx = p.pred.fixture
        parts.append(f"{i}. {match_title(fx)}\n{escape(config.league_name(fx.div))} · {when(fx)}\n{pick_body(p)}")
    if locked:
        parts.append(f"🔒 +{locked} typów w premium → /premium")
    parts.append(f"{ODDS_HINT}\n{DISCLAIMER}")
    return "\n\n".join(parts)


def multi_picks_text(analyses: list[Analysis], show_picks: bool = True) -> str:
    """Typy na kilka zaznaczonych meczów w jednej wiadomości + kupon z najmocniejszych typów."""
    parts = [f"📨 <b>Typy na wybrane mecze ({len(analyses)})</b>"]
    best = []
    for i, a in enumerate(analyses, 1):
        fx = a.pred.fixture
        head = f"{i}. {match_title(fx)}\n{escape(config.league_name(fx.div))} · {when(fx)}"
        if not show_picks:
            parts.append(f"{head}\n🔒 typy: {len(a.picks)} — premium → /premium")
        elif a.picks:
            picks = sorted(a.picks, key=lambda p: (-p.stars, -p.score))
            best.append(picks[0])
            parts.append(head + "\n" + "\n".join(pick_body(p) for p in picks))
        else:
            parts.append(f"{head}\n⏸ bez typu — nic nie odstaje na tyle, żeby grać")
    if show_picks and len(best) >= 2:
        prob = 1.0
        for p in best:
            prob *= p.ev.prob
        parts.append(f"🧾 <b>Kupon z najmocniejszych typów ({len(best)})</b>\n"
                     f"szansa, że wejdą wszystkie: <b>{prob:.0%}</b> · kurs łączny od <b>"
                     f"{config.SAFETY_MARGIN / prob:.2f}</b>\n"
                     "<i>Im więcej meczów na kuponie, tym mniejsza szansa — jeden błąd przegrywa całość.</i>")
    parts.append(f"{ODDS_HINT}\n{DISCLAIMER}")
    return "\n\n".join(parts)


def _counts_line(pred) -> str | None:
    parts = []
    for kind, name in (("cards", "kartki"), ("corners", "rożne"), ("sot", "celne"), ("fouls", "faule")):
        c = pred.counts.get(kind)
        if c:
            parts.append(f"{COUNT_KINDS[kind][1]} {name} ~{sum(c.lam):.1f}")
    if not parts:
        return None
    line = " · ".join(parts)
    cards = pred.counts.get("cards")
    if cards and cards.referee_factor:
        if cards.referee_factor >= 1.1:
            line += "\n👨‍⚖️ sędzia surowy (więcej kartek niż zwykle)"
        elif cards.referee_factor <= 0.9:
            line += "\n👨‍⚖️ sędzia łagodny (mniej kartek niż zwykle)"
    return line


def _top_scorers(a: Analysis, n: int = 3) -> str | None:
    goals = sorted((pm for pm in a.players if pm.stat == "goals" and pm.player.p_play >= 0.5),
                   key=lambda pm: -pm.prob)[:n]
    if not goals:
        return None
    return "⚽ Strzelcy: " + " · ".join(f"{escape(_short(pm.player.name))} {pm.prob:.0%}" for pm in goals)


def _short(name: str) -> str:
    """„Harry Kane” → „Kane” (pełne nazwiska są w sekcji Zawodnicy)."""
    parts = name.split()
    return parts[-1] if len(parts) > 1 else name


def analysis_text(a: Analysis, show_picks: bool = True) -> str:
    pred = a.pred
    fx = pred.fixture
    ev = {e.market.key: e for e in a.evals}
    lh, la = pred.lam
    m = pred.matrix
    _, i, j = max((m[i, j], i, j) for i in range(6) for j in range(6))

    out = [f"⚽ {match_title(fx)}", f"{escape(config.league_name(fx.div))} · {when(fx)}"]

    out.append(f"\n📊 <b>{escape(fx.home)}</b> {ev['1'].prob:.0%} · remis {ev['X'].prob:.0%} · "
               f"<b>{escape(fx.away)}</b> {ev['2'].prob:.0%}\n"
               f"Gole ~{lh + la:.1f} · ponad 2.5: {ev['O2.5'].prob:.0%} · obie strzelą: {ev['BTTS_Y'].prob:.0%}\n"
               f"Najbardziej prawdopodobny wynik: {i}:{j}")
    counts = _counts_line(pred)
    if counts:
        out.append(counts)

    form = []
    for name, f, mo in ((fx.home, pred.form_home, pred.mot_home), (fx.away, pred.form_away, pred.mot_away)):
        if f:
            line = f"{form_icons(f.results)} {escape(name)} ({f.scored}:{f.conceded})"
            if mo and mo.label not in ("początek sezonu", "środek tabeli"):
                line += f" · {mo.position}. miejsce, {mo.label}"
            form.append(line)
    if form:
        out.append("\n📈 <b>Forma</b> (ostatnie 5)\n" + "\n".join(form))

    scorers = _top_scorers(a)
    if scorers:
        out.append(scorers)

    if show_picks:
        if a.picks:
            out.append("\n✅ <b>Typy</b>\n" + "\n\n".join(pick_body(pk) for pk in a.picks))
        elif not pred.enough_data:
            out.append("\n⏸ Za mało danych — bez typów.")
        else:
            out.append("\n⏸ Bez typu — nic nie odstaje na tyle, żeby grać.")
    else:
        out.append(f"\n🔒 Typy do tego meczu ({len(a.picks)}) w premium → /premium")

    notes = []
    if not a.lineups_known:
        notes.append("Składy jeszcze nieznane — sprawdź przed grą.")
    if fx.div in config.CUPS:
        notes.append("Puchar — typy mniej pewne niż w lidze.")
    if notes:
        out.append("\n<i>" + " ".join(notes) + "</i>")
    return "\n".join(out)


def players_text(a: Analysis, per_team: int = 5) -> str:
    """Szczegóły zawodników (przycisk „👤 Zawodnicy”)."""
    fx = a.pred.fixture
    rows: dict = {}
    for pm in a.players:
        rows.setdefault(pm.player.id, {"p": pm.player})[f"{pm.stat}:{pm.key.rsplit(':', 1)[1]}"] = pm
    out = [f"👤 <b>Zawodnicy: {escape(fx.home)} – {escape(fx.away)}</b>",
           "<i>szanse, jeśli zagra · ✅ w składzie</i>" if a.lineups_known else "<i>szanse, jeśli zagra</i>"]
    for team_id, team in ((fx.espn_home_id, fx.home), (fx.espn_away_id, fx.away)):
        team_rows = [r for r in rows.values() if r["p"].team_id == team_id]
        team_rows.sort(key=lambda r: -(r["goals:0.5"].prob if "goals:0.5" in r else 0))
        if not team_rows:
            continue
        lines = [f"\n<b>{escape(team)}</b>"]
        for r in team_rows[:per_team]:
            p = r["p"]
            stats = []
            if "goals:0.5" in r:
                stats.append(f"gol {r['goals:0.5'].prob:.0%}")
            if "shots:1.5" in r:
                stats.append(f"2+ strzały {r['shots:1.5'].prob:.0%}")
            if "sot:0.5" in r:
                stats.append(f"celny {r['sot:0.5'].prob:.0%}")
            mark = " ✅" if p.lineup == "start" else " 🪑" if p.lineup == "ławka" else ""
            lines.append(f"{escape(p.name)}{mark}: " + " · ".join(stats)
                         + (f"\n   forma: {escape(' '.join(p.last5))}" if p.last5 else ""))
        out.append("\n".join(lines))
    out.append("\n<i>forma: ⚽ gol · 3s = 3 strzały · – nie grał (najnowszy z prawej).\n"
               "Gdy zawodnik nie zagra, bukmacher zwraca stawkę.</i>")
    return "\n".join(out)


LIVE_STEPS = [
    "Pobieram dane…",
    "Sprawdzam formę…",
    "Liczę siłę drużyn…",
    "Sprawdzam tabelę…",
    "Kartki, rożne, strzały…",
    "Analizuję zawodników…",
    "Liczę wszystkie rynki…",
    "Wybieram typy…",
]


def live_text(fx: Fixture, done: list[str]) -> str:
    """Wiadomość „analiza na żywo”: pasek postępu, gotowe kroki i to, co liczy się teraz."""
    n, total = len(done), len(LIVE_STEPS)
    bar = "▰" * n + "▱" * (total - n)
    out = [f"🔍 {match_title(fx)}", f"{bar} {round(100 * n / total)}%\n", *done]
    if n < total:
        out.append(f"⏳ <i>{LIVE_STEPS[n]}</i>")
    return "\n".join(out)


def live_form_line(pred) -> str:
    fx = pred.fixture

    def res(f):
        return form_icons(f.results) if f else "brak danych"
    return f"📈 {escape(fx.home)} {res(pred.form_home)}\n📈 {escape(fx.away)} {res(pred.form_away)}"


def live_strength_line(pred) -> str:
    lh, la = pred.lam
    return f"⚔️ Oczekiwane gole: <b>{lh:.1f} – {la:.1f}</b>"


def live_table_line(pred) -> str:
    fx = pred.fixture
    if fx.div in config.CUPS:
        return "🏆 Mecz pucharowy"
    parts = [f"{escape(name)} {mo.position}." for name, mo in ((fx.home, pred.mot_home), (fx.away, pred.mot_away))
             if mo]
    return "🎯 Tabela: " + (" · ".join(parts) if parts else "brak")


def live_counts_line(pred) -> str:
    return _counts_line(pred) or "🟨 Brak statystyk dla tej ligi"


def all_markets_text(a: Analysis) -> str:
    """Pełna lista rynków z naszą wyceną — dla dociekliwych."""
    fx = a.pred.fixture
    out = [f"📋 <b>Wszystkie rynki: {escape(fx.home)} – {escape(fx.away)}</b>",
           "<i>szansa · kurs od</i>"]
    group = None
    for e in a.evals:
        if e.prob < 0.05 or e.prob > 0.97:
            continue
        if e.market.group != group:
            group = e.market.group
            out.append(f"\n<b>{escape(group)}</b>")
        out.append(f"{escape(e.label)}: {e.prob:.0%} · {config.SAFETY_MARGIN * e.fair_odds:.2f}")
    if a.players:
        out.append("\n<b>Zawodnicy</b> <i>(jeśli zagra)</i>")
        for pm in sorted(a.players, key=lambda pm: (pm.player.name, pm.stat, pm.key)):
            if 0.05 <= pm.prob <= 0.97:
                out.append(f"{escape(pm.label)}: {pm.prob:.0%} · {config.SAFETY_MARGIN / pm.prob:.2f}")
    return "\n".join(out)


def stats_text(stats: dict) -> str:
    if not stats["settled"]:
        return "📈 <b>Skuteczność</b>\n\nJeszcze nic nie rozliczone — wyniki po pierwszych meczach."
    out = ["📈 <b>Skuteczność</b>",
           f"✅ {stats['won']} · ❌ {stats['lost']} · ↩️ {stats['push']}  →  <b>{stats['hit_rate']:.0%}</b> trafień",
           f"<i>model zakładał {stats['avg_prob']:.0%} · wynik przy kursie minimalnym: {stats['roi']:+.1%}</i>"]
    if stats.get("by_kind"):
        out.append("\n" + "\n".join(f"{KIND_ICON.get(k, '•')} {k}: {s['won']}/{s['n']}"
                                    for k, s in stats["by_kind"].items()))
    if stats.get("recent"):
        out.append("\n<b>Ostatnie</b>")
        for r in stats["recent"]:
            icon = {"won": "✅", "lost": "❌", "push": "↩️"}.get(r["result"], "⏳")
            out.append(f"{icon} {escape(r['label'])}")
    return "\n".join(out)
