"""Teksty wiadomości po polsku (format HTML Telegrama)."""
from __future__ import annotations

from html import escape

from . import config
from .data import Fixture
from .engine import Analysis
from .picks import Pick

DAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"]
KIND_ICON = {"value": "💰", "model": "⚽", "kartki": "🟨", "rożne": "🚩"}

DISCLAIMER = ("ℹ️ Typy to prawdopodobieństwa, nie pewniaki. Graj tylko u legalnych "
              "bukmacherów, tylko 18+ i tylko za kwoty, które możesz stracić.")


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
    k = fx.kickoff
    return f"{DAYS[k.weekday()]} {k:%d.%m %H:%M}"


def stars(n: int) -> str:
    return "★" * n + "☆" * (3 - n)


def pick_line(p: Pick, with_match: bool = True) -> str:
    fx = p.pred.fixture
    head = ""
    if with_match:
        head = (f"<b>{escape(fx.home)} – {escape(fx.away)}</b>\n"
                f"<i>{escape(config.league_name(fx.div))} · {when(fx)}</i>\n")
    line = f"{KIND_ICON.get(p.kind, '•')} <b>{escape(p.ev.label)}</b>\n"
    line += f"   szansa {p.ev.prob:.0%} · graj przy kursie ≥ <b>{p.min_odds:.2f}</b> · {stars(p.stars)}\n"
    line += f"   <i>{escape(p.reason)}</i>"
    return head + line


def picks_text(picks: list[Pick], title: str, locked: int = 0) -> str:
    if not picks:
        return (f"<b>{title}</b>\n\nNa najbliższe dni model nie znalazł typów, w które wierzy. "
                "Lepiej nie grać niż grać na siłę.")
    parts = [f"<b>{title}</b>"]
    for i, p in enumerate(picks, 1):
        parts.append(f"{i}. " + pick_line(p))
    if locked:
        parts.append(f"🔒 Jeszcze {locked} typów dostępnych w wersji premium — /premium")
    parts.append("<i>„Graj przy kursie ≥” to najniższy kurs, przy którym typ się opłaca. "
                 "Jeśli Twój bukmacher daje mniej — odpuść.</i>")
    parts.append(DISCLAIMER)
    return "\n\n".join(parts)


def _form_line(name: str, f) -> str:
    if not f:
        return f"{escape(name)}: brak danych"
    s = f"{escape(name)}: {' '.join(f.results)} · gole {f.scored}:{f.conceded}"
    if f.xg_for is not None:
        s += f" · xG {f.xg_for:.1f}:{f.xg_against:.1f}"
    extra = []
    if f.cards_avg is not None:
        extra.append(f"kartki {f.cards_avg:.1f}/mecz")
    if f.corners_avg is not None:
        extra.append(f"rożne {f.corners_avg:.1f}/mecz")
    if extra:
        s += "\n   " + " · ".join(extra)
    return s


def analysis_text(a: Analysis, show_picks: bool = True) -> str:
    pred = a.pred
    fx = pred.fixture
    ev = {e.market.key: e for e in a.evals}
    lh, la = pred.lam
    out = [f"⚽ <b>{escape(fx.home)} – {escape(fx.away)}</b>",
           f"🏆 {escape(config.league_name(fx.div))} · {when(fx)}"]
    if fx.referee:
        ref = f"👨‍⚖️ Sędzia: {escape(fx.referee)}"
        if pred.referee_factor:
            ref += f" (kartki ×{pred.referee_factor:.2f} vs przeciętny)"
        out.append(ref)

    p = ["\n📊 <b>Prawdopodobieństwa</b>",
         f"1: {ev['1'].prob:.0%} · X: {ev['X'].prob:.0%} · 2: {ev['2'].prob:.0%}",
         f"Powyżej 2.5 gola: {ev['O2.5'].prob:.0%} · Obie strzelą: {ev['BTTS_Y'].prob:.0%}",
         f"Oczekiwane gole: {lh:.2f} – {la:.2f}"]
    m = pred.matrix
    top = sorted(((m[i, j], i, j) for i in range(5) for j in range(5)), reverse=True)[:3]
    p.append("Najczęstsze wyniki: " + ", ".join(f"{i}:{j} ({v:.0%})" for v, i, j in top))
    if pred.cards:
        p.append(f"Kartki: średnio {sum(pred.cards):.1f} ({pred.cards[0]:.1f} – {pred.cards[1]:.1f}), "
                 f"liga {pred.cards_league_avg:.1f}")
    if pred.corners:
        p.append(f"Rożne: średnio {sum(pred.corners):.1f} ({pred.corners[0]:.1f} – {pred.corners[1]:.1f}), "
                 f"liga {pred.corners_league_avg:.1f}")
    if fx.odds.get("1"):
        p.append(f"Kursy (średnia rynku): {fx.odds['1']:.2f} / {fx.odds['X']:.2f} / {fx.odds['2']:.2f}")
    out += p

    out.append("\n📈 <b>Forma (ostatnie 5, najnowszy z prawej)</b>")
    out.append(_form_line(fx.home, pred.form_home))
    out.append(_form_line(fx.away, pred.form_away))
    if pred.h2h:
        out.append("🔁 Bezpośrednie: " + ", ".join(
            f"{escape(h.home)} {h.hg}:{h.ag} {escape(h.away)}" for h in reversed(pred.h2h[-3:])))
    mot = []
    for name, mo in ((fx.home, pred.mot_home), (fx.away, pred.mot_away)):
        if mo:
            mot.append(f"{escape(name)} {mo.position}. miejsce ({mo.points} pkt) – {mo.label}")
    if mot:
        out.append("🎯 <b>Tabela i motywacja</b>\n" + "\n".join(mot))

    if show_picks:
        if a.picks:
            out.append("\n✅ <b>TYPY</b>")
            out += [pick_line(pk, with_match=False) for pk in a.picks]
        elif not pred.enough_data:
            out.append("\n⏸ Za mało danych o jednej z drużyn — bez typów.")
        else:
            out.append("\n⏸ Brak typu — nic tu nie odstaje na tyle, żeby grać.")
    else:
        out.append(f"\n🔒 Typy do tego meczu: {len(a.picks)} — dostępne w premium (/premium)")

    if fx.div in config.CUPS:
        out.append("\n🏆 Mecz pucharowy: siła drużyn z kursów bukmacherów, kartki i rożne ze statystyk "
                   "z ich lig (sędziowie UEFA bywają inni) — traktuj te typy ostrożniej.")
    out.append("\n⚠️ Darmowe dane nie zawierają kontuzji ani składów — sprawdź je przed meczem "
               "(np. na stronie klubu), bo brak kluczowego gracza zmienia wszystko.")
    return "\n".join(out)


LIVE_STEPS = [
    "Pobieram wyniki z 3 sezonów…",
    "Sprawdzam formę z ostatnich meczów…",
    "Liczę siłę ataku i obrony…",
    "Sprawdzam tabelę i motywację…",
    "Analizuję kartki, sędziego i rzuty rożne…",
    "Przeliczam wszystkie rynki…",
    "Wybieram typy, w które model wierzy…",
]


def live_text(fx: Fixture, done: list[str]) -> str:
    """Wiadomość „analiza na żywo”: pasek postępu, gotowe kroki i to, co liczy się teraz."""
    n, total = len(done), len(LIVE_STEPS)
    bar = "▰" * n + "▱" * (total - n)
    out = [f"🔍 <b>Analizuję na żywo: {escape(fx.home)} – {escape(fx.away)}</b>",
           f"<i>{escape(config.league_name(fx.div))} · {when(fx)}</i>",
           f"\n{bar} {round(100 * n / total)}%\n"]
    out += done
    if n < total:
        out.append(f"⏳ <i>{LIVE_STEPS[n]}</i>")
    return "\n".join(out)


def live_form_line(pred) -> str:
    def res(f):
        return " ".join(f.results) if f else "brak danych"
    fx = pred.fixture
    return (f"📈 Forma: {escape(fx.home)} <b>{res(pred.form_home)}</b> · "
            f"{escape(fx.away)} <b>{res(pred.form_away)}</b>")


def live_strength_line(pred) -> str:
    lh, la = pred.lam
    line = f"⚔️ Oczekiwane gole: <b>{lh:.2f} – {la:.2f}</b>"
    if pred.lam_model and pred.lam_market:
        line += (f" (model {pred.lam_model[0]:.2f}–{pred.lam_model[1]:.2f}, "
                 f"kursy {pred.lam_market[0]:.2f}–{pred.lam_market[1]:.2f})")
    return line


def live_table_line(pred) -> str:
    fx = pred.fixture
    if fx.div in config.CUPS:
        return "🏆 Puchar: siła drużyn z kursów bukmacherów (drużyny z różnych lig)"
    parts = [f"{escape(name)} {mo.position}. ({mo.label})"
             for name, mo in ((fx.home, pred.mot_home), (fx.away, pred.mot_away)) if mo]
    return "🎯 Tabela: " + (" · ".join(parts) if parts else "brak tabeli dla tej ligi")


def live_counts_line(pred) -> str:
    parts = []
    if pred.cards:
        s = f"🟨 kartki {sum(pred.cards):.1f} (liga {pred.cards_league_avg:.1f})"
        if pred.referee_factor:
            s += f", sędzia ×{pred.referee_factor:.2f}"
        parts.append(s)
    if pred.corners:
        parts.append(f"🚩 rożne {sum(pred.corners):.1f} (liga {pred.corners_league_avg:.1f})")
    return " · ".join(parts) if parts else "🟨 Kartki i rożne: brak danych dla tej ligi"


def all_markets_text(a: Analysis) -> str:
    """Pełna lista rynków z naszą wyceną — dla dociekliwych."""
    fx = a.pred.fixture
    out = [f"📋 <b>Wszystkie rynki: {escape(fx.home)} – {escape(fx.away)}</b>",
           "<i>szansa · minimalny opłacalny kurs</i>"]
    group = None
    for e in a.evals:
        if e.market.group != group:
            group = e.market.group
            out.append(f"\n<b>{escape(group)}</b>")
        if e.prob < 0.05 or e.prob > 0.97:
            continue
        out.append(f"{escape(e.label)}: {e.prob:.0%} · {config.SAFETY_MARGIN * e.fair_odds:.2f}")
    return "\n".join(out)


def stats_text(stats: dict) -> str:
    if not stats["settled"]:
        return ("📈 <b>Skuteczność</b>\n\nJeszcze żaden typ nie został rozliczony. "
                "Wyniki pojawią się po pierwszych meczach.")
    out = ["📈 <b>Skuteczność typów</b>",
           f"Rozliczone: {stats['settled']} · trafione: {stats['won']} · "
           f"przegrane: {stats['lost']} · zwroty: {stats['push']}",
           f"Trafność: {stats['hit_rate']:.1%} (model zakładał średnio {stats['avg_prob']:.1%})",
           f"Wynik przy grze po minimalnym kursie: {stats['roi']:+.1%} na typ"]
    if stats.get("by_kind"):
        out.append("")
        for kind, s in stats["by_kind"].items():
            out.append(f"{KIND_ICON.get(kind, '•')} {kind}: {s['won']}/{s['n']} ({s['won'] / s['n']:.0%})")
    if stats.get("recent"):
        out.append("\n<b>Ostatnie:</b>")
        for r in stats["recent"]:
            icon = {"won": "✅", "lost": "❌", "push": "↩️"}.get(r["result"], "⏳")
            out.append(f"{icon} {escape(r['home'])} – {escape(r['away'])}: {escape(r['label'])}")
    return "\n".join(out)

