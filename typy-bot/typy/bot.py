"""Bot Telegrama: typy dnia, analizy meczów, skuteczność, subskrypcja premium (Telegram Stars)."""
from __future__ import annotations

import asyncio
import logging
from datetime import time as dtime
from html import escape

from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                      LabeledPrice, ReplyKeyboardMarkup, Update)
from telegram.constants import ParseMode
from telegram.error import Forbidden, NetworkError, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, PreCheckoutQueryHandler, filters)

from . import config, data, report
from .engine import Analysis, Engine
from .markets import evaluate
from .picks import select_picks
from .store import Store

log = logging.getLogger("typy")

BTN_PICKS = "🔥 Typy dnia"
BTN_MATCHES = "📅 Mecze"
BTN_STATS = "📈 Skuteczność"
BTN_PREMIUM = "⭐ Premium"

MENU = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_PICKS), KeyboardButton(BTN_MATCHES)],
     [KeyboardButton(BTN_STATS), KeyboardButton(BTN_PREMIUM)]],
    resize_keyboard=True)

engine = Engine()
store = Store()


async def _run(fn, *args):
    """Model liczy kilka sekund — nie blokujemy w tym czasie bota."""
    return await asyncio.to_thread(fn, *args)


def _user(update: Update) -> int:
    u = update.effective_user
    store.touch_user(u.id, update.effective_chat.id, u.full_name)
    return u.id


async def _send(update: Update, text: str, markup=None) -> None:
    parts = report.split_message(text)
    for i, part in enumerate(parts):
        await update.effective_message.reply_text(
            part, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            reply_markup=markup if i == len(parts) - 1 else None)


# ------------------------------------------------------------------ komendy

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _user(update)
    text = (
        "👋 <b>Cześć! Jestem botem do typowania meczów piłkarskich.</b>\n\n"
        "Codziennie analizuję mecze z ok. 40 lig i europejskich pucharów: formę drużyn, siłę ataku i obrony, "
        "kartki, rzuty rożne, sędziów, tabelę i motywację oraz kursy bukmacherów. "
        "Wysyłam tylko typy, w które model naprawdę wierzy.\n\n"
        f"{BTN_PICKS} — najmocniejsze typy na najbliższe godziny\n"
        f"{BTN_MATCHES} — analiza dowolnego meczu\n"
        f"{BTN_STATS} — uczciwa historia trafień\n"
        "/mecz Legia — szukaj meczu po nazwie drużyny\n"
        "/powiadomienia — włącz/wyłącz codzienne typy\n\n"
        f"{report.DISCLAIMER}"
    )
    await _send(update, text, MENU)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "<b>Jak czytać typy?</b>\n\n"
        "• <b>szansa</b> — jak często taki typ powinien wchodzić. Sprawdziliśmy to na ok. 11 300 meczach "
        "z dwóch sezonów: gdy model mówił ~72%, typ wchodził w ~72% przypadków.\n"
        "• <b>graj przy kursie ≥</b> — najniższy kurs, przy którym zakład się opłaca. "
        "Jeśli Twój bukmacher daje mniej, odpuść ten typ.\n"
        "• <b>★☆☆ – ★★★</b> — jak mocno mecz odstaje od przeciętnej (siła sygnału).\n\n"
        "🟨 kartki (liczymy żółte + czerwone, każda za 1 — sprawdź zasady swojego bukmachera)\n"
        "🚩 rzuty rożne · ⚽ gole, BTTS, handicapy\n\n"
        "<b>Czego bot nie wie:</b> kontuzji, składów i zawieszeń z ostatniej chwili — "
        "sprawdź je przed meczem.\n\n" + report.DISCLAIMER
    )
    await _send(update, text)


async def cmd_picks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _user(update)
    await update.effective_chat.send_action("typing")
    picks = await _run(engine.best_picks)
    store.save_picks(picks)
    if store.is_premium(uid):
        text = report.picks_text(picks, "🔥 Typy dnia")
    else:
        free = picks[: config.FREE_DAILY_PICKS]
        text = report.picks_text(free, "🔥 Typ dnia (darmowy)", locked=len(picks) - len(free))
    await _send(update, text)


async def cmd_matches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _user(update)
    await update.effective_chat.send_action("typing")
    fixtures = await _run(engine.upcoming, 72)
    if not fixtures:
        await _send(update, "Brak meczów w najbliższych dniach w obsługiwanych ligach.")
        return
    counts: dict[str, int] = {}
    for f in fixtures:
        counts[f.div] = counts.get(f.div, 0) + 1
    rows = [[InlineKeyboardButton(f"{config.league_name(div)} ({n})", callback_data=f"L|{div}")]
            for div, n in sorted(counts.items(), key=lambda kv: (config.league_rank(kv[0]), -kv[1]))]
    await _send(update, "📅 <b>Wybierz ligę</b> (mecze w ciągu 3 dni):", InlineKeyboardMarkup(rows))


async def cmd_find(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _user(update)
    query = " ".join(context.args or [])
    if len(query) < 3:
        await _send(update, "Podaj nazwę drużyny, np. <code>/mecz Arsenal</code> (min. 3 litery).")
        return
    found = await _run(engine.find, query)
    if not found:
        await _send(update, f"Nie znalazłem nadchodzącego meczu dla „{escape(query)}”. "
                            "Spróbuj inaczej, np. <code>Legia</code>, <code>Bayern</code>, <code>PSG</code>.")
        return
    await _send(update, "Znalezione mecze:", _match_buttons(found[:15]))


def _match_buttons(fixtures: list[data.Fixture]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{report.when(f)} {f.home} – {f.away}",
                              callback_data=f"M|{engine.short_id(f)}")]
        for f in fixtures
    ])


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _user(update)
    await _send(update, report.stats_text(store.stats()))


async def cmd_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _user(update)
    on = not store.notify_enabled(uid)
    store.set_notify(uid, on)
    await _send(update, f"🔔 Codzienne typy o {config.DAILY_HOUR}:00 włączone." if on
                else "🔕 Codzienne typy wyłączone. Włączysz je ponownie komendą /powiadomienia.")


async def cmd_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _user(update)
    if config.FREE_MODE:
        await _send(update, "🎁 Bot działa teraz w trybie testowym — wszystkie typy są darmowe.")
        return
    until = store.premium_until(uid)
    if store.is_premium(uid) and until:
        await _send(update, f"⭐ Masz premium do <b>{until}</b>. Możesz przedłużyć poniżej.")
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title=f"Premium na {config.PREMIUM_DAYS} dni",
        description=(f"Wszystkie typy dnia (do {config.DAILY_MAX_PICKS} dziennie), typy do każdego meczu "
                     "i codzienne powiadomienia."),
        payload=f"premium:{config.PREMIUM_DAYS}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(f"Premium {config.PREMIUM_DAYS} dni", config.PREMIUM_PRICE_STARS)],
    )


async def on_precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.pre_checkout_query
    if q.invoice_payload.startswith("premium:"):
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="Nieznany produkt.")


async def on_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = _user(update)
    sp = update.message.successful_payment
    days = int(sp.invoice_payload.split(":")[1])
    store.record_payment(uid, sp.total_amount, sp.telegram_payment_charge_id)
    until = store.add_premium(uid, days)
    await _send(update, f"✅ Dziękuję! Premium aktywne do <b>{until}</b>.\n"
                        f"Typy dnia przyjdą codziennie o {config.DAILY_HOUR}:00.")


# ------------------------------------------------------------------ przyciski

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    uid = _user(update)
    await q.answer()
    kind, _, arg = q.data.partition("|")
    if kind == "L":
        fixtures = [f for f in await _run(engine.upcoming, 72) if f.div == arg]
        await _send(update, f"<b>{escape(config.league_name(arg))}</b>", _match_buttons(fixtures[:40]))
    elif kind in ("M", "A"):
        fx = engine.by_short_id(arg)
        if not fx:
            await _send(update, "Ten mecz już się zaczął albo zniknął z terminarza.")
            return
        if kind == "M":
            await live_analysis(update, fx, store.is_premium(uid), arg)
            return
        a = await _run(engine.analyse, fx)
        if a:
            await _send(update, report.all_markets_text(a))


LIVE_STEP_DELAY = 0.8  # sekundy między krokami — żeby dało się przeczytać, co bot liczy


async def live_analysis(update: Update, fx: data.Fixture, premium: bool, sid: str) -> None:
    """Analiza „na żywo”: jedna wiadomość, aktualizowana po każdym prawdziwym kroku obliczeń."""
    done: list[str] = []
    msg = await update.effective_message.reply_text(report.live_text(fx, done), parse_mode=ParseMode.HTML)

    async def show(line: str) -> None:
        done.append(line)
        await asyncio.sleep(LIVE_STEP_DELAY)
        try:
            await msg.edit_text(report.live_text(fx, done), parse_mode=ParseMode.HTML)
        except TelegramError as e:  # np. limit edycji — pomijamy klatkę, liczenie trwa dalej
            log.debug("Nie odświeżono analizy: %s", e)

    async def fail(text: str) -> None:
        await msg.edit_text(f"{report.live_text(fx, done)}\n\n❌ {text}", parse_mode=ParseMode.HTML)

    home_model, away_model = await _run(engine.team_models, fx)
    n_home = sum(fx.home in (m.home, m.away) for m in home_model.matches) if home_model else 0
    n_away = sum(fx.away in (m.home, m.away) for m in away_model.matches) if away_model else 0
    if not (n_home or n_away or fx.odds):
        await fail("Brak danych o tych drużynach.")
        return
    await show(f"📥 Dane: {n_home} meczów {escape(fx.home)}, {n_away} meczów {escape(fx.away)}")
    pred = await _run(engine.predict, fx)
    if not pred:
        await fail("Za mało danych o tych drużynach, żeby coś sensownego policzyć.")
        return
    await show(report.live_form_line(pred))
    await show(report.live_strength_line(pred))
    await show(report.live_table_line(pred))
    await show(report.live_counts_line(pred))
    evals = await _run(evaluate, pred)
    await show(f"🧮 Przeliczono {len(evals)} rynków")
    picks = select_picks(pred, evals)
    await show(f"✅ Typy wybrane: {len(picks)}" if picks else "⏸ Żaden rynek nie odstaje na tyle, żeby grać")
    a = Analysis(pred, evals, picks)
    engine.remember(fx, a)
    if premium:
        store.save_picks(picks)
    await asyncio.sleep(LIVE_STEP_DELAY)

    markup = InlineKeyboardMarkup([[InlineKeyboardButton(
        "📋 Wszystkie rynki", callback_data=f"A|{sid}")]]) if premium else None
    parts = report.split_message(report.analysis_text(a, show_picks=premium))
    await msg.edit_text(parts[0], parse_mode=ParseMode.HTML,
                        reply_markup=markup if len(parts) == 1 else None)
    for i, part in enumerate(parts[1:], 2):
        await update.effective_message.reply_text(part, parse_mode=ParseMode.HTML,
                                                  reply_markup=markup if i == len(parts) else None)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    handlers = {BTN_PICKS: cmd_picks, BTN_MATCHES: cmd_matches, BTN_STATS: cmd_stats,
                BTN_PREMIUM: cmd_premium}
    if text in handlers:
        await handlers[text](update, context)
    elif len(text) >= 3:
        context.args = text.split()
        await cmd_find(update, context)


# ------------------------------------------------------------------ admin

def _admin(update: Update) -> bool:
    return update.effective_user.id in config.ADMIN_IDS


async def cmd_admin_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _admin(update):
        return
    try:
        uid, days = int(context.args[0]), int(context.args[1])
    except (IndexError, ValueError):
        await _send(update, "Użycie: <code>/admin_premium ID_UŻYTKOWNIKA DNI</code>")
        return
    until = store.add_premium(uid, days)
    await _send(update, f"Premium dla {uid} do {until}.")


async def cmd_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _admin(update):
        return
    total, prem = store.user_count()
    await _send(update, f"Użytkownicy: {total}, premium: {prem}\nMeczów w terminarzu: {len(engine.fixtures)}")


async def cmd_admin_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _admin(update):
        return
    sent = await daily_broadcast(context)
    await _send(update, f"Wysłano do {sent} osób.")


# ------------------------------------------------------------------ zadania cykliczne

async def daily_broadcast(context: ContextTypes.DEFAULT_TYPE) -> int:
    await _run(engine.refresh, True)
    picks = await _run(engine.best_picks)
    store.save_picks(picks)
    full = report.picks_text(picks, "🔥 Typy dnia")
    free_picks = picks[: config.FREE_DAILY_PICKS]
    free = report.picks_text(free_picks, "🔥 Typ dnia (darmowy)", locked=len(picks) - len(free_picks))
    sent = 0
    for user in store.subscribers():
        text = full if store.is_premium(user["user_id"]) else free
        try:
            for part in report.split_message(text):
                await context.bot.send_message(user["chat_id"], part, parse_mode=ParseMode.HTML,
                                               disable_web_page_preview=True)
            sent += 1
        except Forbidden:
            store.set_notify(user["user_id"], False)  # użytkownik zablokował bota
        except TelegramError as e:
            log.warning("Nie wysłano do %s: %s", user["user_id"], e)
        await asyncio.sleep(0.05)  # limit Telegrama: ~30 wiadomości/s
    return sent


async def settle_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    divs = sorted({r["div"] for r in store.db.execute("SELECT div FROM picks WHERE result IS NULL")})
    if not divs:
        return
    results = await _run(lambda: data.load_matches(seasons=1, divs=divs))
    n = store.settle_open(results)
    if n:
        log.info("Rozliczono %d typów", n)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, NetworkError):  # chwilowe zerwanie połączenia — biblioteka ponawia sama
        log.warning("Problem z siecią: %s", context.error)
        return
    log.error("Błąd przy obsłudze wiadomości", exc_info=context.error)


async def warmup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run(engine.refresh, True)
    log.info("Dane gotowe: %d meczów w terminarzu", len(engine.fixtures))


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("typy", "Typy dnia"),
        BotCommand("mecze", "Analiza meczu"),
        BotCommand("mecz", "Szukaj meczu po drużynie"),
        BotCommand("skutecznosc", "Historia trafień"),
        BotCommand("premium", "Subskrypcja"),
        BotCommand("powiadomienia", "Codzienne typy: wł./wył."),
        BotCommand("pomoc", "Jak czytać typy"),
    ])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("Brak TELEGRAM_TOKEN w pliku .env — zobacz README.md.")
    app = Application.builder().token(config.TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["pomoc", "help"], cmd_help))
    app.add_handler(CommandHandler("typy", cmd_picks))
    app.add_handler(CommandHandler("mecze", cmd_matches))
    app.add_handler(CommandHandler("mecz", cmd_find))
    app.add_handler(CommandHandler("skutecznosc", cmd_stats))
    app.add_handler(CommandHandler("premium", cmd_premium))
    app.add_handler(CommandHandler("powiadomienia", cmd_notify))
    app.add_handler(CommandHandler("admin_premium", cmd_admin_premium))
    app.add_handler(CommandHandler("admin_staty", cmd_admin_stats))
    app.add_handler(CommandHandler("admin_wyslij", cmd_admin_send))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(PreCheckoutQueryHandler(on_precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_paid))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    app.job_queue.run_daily(daily_broadcast, dtime(hour=config.DAILY_HOUR, tzinfo=data.PL))
    app.job_queue.run_repeating(settle_job, interval=3 * 3600, first=60)
    # dane ładujemy od razu i odświeżamy co 2 h, żeby użytkownik nie czekał
    app.job_queue.run_repeating(warmup_job, interval=2 * 3600, first=10)
    log.info("Bot startuje…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
