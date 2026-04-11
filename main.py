import asyncio
import os
import traceback
import aiohttp
from aiohttp_socks import ProxyConnector
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta
import matplotlib.pyplot as plt
import mplfinance as mpf
import secrets
import string
from io import BytesIO
import matplotlib
from dotenv import load_dotenv

matplotlib.use('Agg')

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import RetryAfter, TelegramError
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ================== НАСТРОЙКИ СИСТЕМЫ ==================
# Все секреты читаются из файла .env, лежащего рядом с main.py.
load_dotenv()

TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_ID_RAW = os.environ.get('ADMIN_ID')
# PROXY_URL опционален: если задан — все запросы к Bybit идут через SOCKS5.
# Если пусто — ccxt ходит напрямую (пригодится на европейском VPS).
PROXY_URL = os.environ.get('PROXY_URL') or None

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
if not ADMIN_ID_RAW:
    raise RuntimeError("ADMIN_ID не задан в .env")
ADMIN_ID = int(ADMIN_ID_RAW)

# Параметры торговой стратегии
SYMBOLS = ['ETH/USDT:USDT', 'BNB/USDT:USDT', 'SOL/USDT:USDT']
TIMEFRAME = '15m'

# Глобальные семафоры для защиты от Rate Limit (API Flood)
EXCHANGE_SEM = asyncio.Semaphore(3)  # Макс. 3 одновременных запроса к бирже
TG_SEM = asyncio.Semaphore(15)  # Макс. 15 сообщений в секунду в Telegram

# База данных в памяти
users_db = {ADMIN_ID: {'role': 'admin'}}
referral_codes = {}
IS_RUNNING = False

# Инициализация асинхронного клиента Bybit
exchange = ccxt.bybit({
    'enableRateLimit': True,
    'timeout': 30000,
    'options': {
        'defaultType': 'linear',
        'fetchMarkets': ['linear'],
    },
})
_exchange_session_ready = False


async def ensure_exchange_session():
    """Подменяем aiohttp-сессию ccxt под наше окружение.
    Если в .env задан PROXY_URL — поднимаем SOCKS5-туннель (rdns=True,
    DNS резолвит сам прокси). Если нет — обычная сессия с системным resolver."""
    global _exchange_session_ready
    if _exchange_session_ready:
        return
    if PROXY_URL:
        connector = ProxyConnector.from_url(PROXY_URL, rdns=True)
    else:
        connector = aiohttp.TCPConnector(ssl=True)
    exchange.session = aiohttp.ClientSession(connector=connector)
    _exchange_session_ready = True


# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================

def get_spy_sentiment_sync():
    """SPY-фильтр отключён: yfinance нестабилен через TLS и всё равно
    возвращал 0 в 100% случаев. При необходимости восстановить — сюда."""
    return 0


async def get_market_internals_async(symbol):
    """Асинхронный сбор данных стакана, фандинга и OI"""
    imbalance, funding, oi_delta = 1, 0.01, 0
    try:
        # Параллельный запрос данных для максимальной скорости
        # Из 'ETH/USDT:USDT' делаем 'ETHUSDT' — формат, который ожидает raw-endpoint Bybit
        clean_symbol = symbol.split(':')[0].replace('/', '')
        ob_task = exchange.fetch_order_book(symbol, limit=50)
        funding_task = exchange.fetch_funding_rate(symbol)
        oi_task = exchange.publicGetV5MarketOpenInterest({
            'category': 'linear', 'symbol': clean_symbol, 'interval': '15', 'limit': 2
        })

        ob, f_rate, oi_data = await asyncio.gather(ob_task, funding_task, oi_task, return_exceptions=True)

        if not isinstance(ob, Exception):
            bids = sum([v[1] for v in ob['bids']])
            asks = sum([v[1] for v in ob['asks']])
            imbalance = bids / asks if asks > 0 else 1

        if not isinstance(f_rate, Exception):
            funding = f_rate.get('fundingRate', 0) * 100

        if not isinstance(oi_data, Exception):
            oi_list = oi_data.get('result', {}).get('list', [])
            if len(oi_list) >= 2:
                oi_now = float(oi_list[0]['openInterest'])
                oi_prev = float(oi_list[1]['openInterest'])
                oi_delta = ((oi_now - oi_prev) / oi_prev) * 100

    except Exception as e:
        print(f"Ошибка internals {symbol}: {e}")

    return imbalance, funding, oi_delta


def calculate_kelly(win_rate=0.55, rr=2.5):
    """Оптимальный риск по Келли"""
    p, q, b = win_rate, 1 - win_rate, rr
    kelly_f = (p * b - q) / b
    return max(0.01, round(kelly_f * 100, 2))


def create_signal_chart_sync(symbol, df):
    """Генерация графика (выполняется в отдельном потоке)"""
    temp_df = df.tail(40).copy()
    add_plots = [
        mpf.make_addplot(temp_df['EMA_200'], color='orange', width=1.5),
        mpf.make_addplot(temp_df['VWAP_D'], color='blue', width=1.0)
    ]
    buf = BytesIO()
    mpf.plot(temp_df, type='candle', style='charles', addplot=add_plots,
             title=f"\n{symbol} {TIMEFRAME} Analysis", savefig=dict(fname=buf, format='png'),
             volume=True, tight_layout=True)
    buf.seek(0)
    return buf


# ================== ЯДРО АНАЛИЗА ==================

async def analyze_symbol_async(symbol, spy_change):
    async with EXCHANGE_SEM:
        try:
            bars = await exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=300)
            df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            df['ts'] = pd.to_datetime(df['ts'], unit='ms')
            df.set_index('ts', inplace=True)

            # Индикаторы (pandas_ta ждёт колонку именно 'volume')
            df.ta.adx(append=True)
            df.ta.vwap(append=True)
            df.ta.ema(length=200, append=True)
            df.ta.stochrsi(length=14, append=True)
            df['rvol'] = df['volume'] / df['volume'].rolling(20).mean()

            # Имена индикаторных колонок у pandas_ta 0.3.x и 0.4.x немного
            # отличаются, поэтому ищем их по префиксу и нормализуем.
            def _first_col(prefix):
                matches = [c for c in df.columns if c.startswith(prefix)]
                return matches[0] if matches else None

            vwap_col = _first_col('VWAP')
            ema_col = _first_col('EMA_200')
            adx_col = _first_col('ADX_')
            stoch_col = _first_col('STOCHRSIk')
            if not all([vwap_col, ema_col, adx_col, stoch_col]):
                print(f"{symbol}: не все индикаторы посчитались, колонки: {list(df.columns)}")
                return None
            df['VWAP_D'] = df[vwap_col]
            df['EMA_200'] = df[ema_col]
            df['ADX_14'] = df[adx_col]
            df['STOCHRSIk_14_14_3_3'] = df[stoch_col]

            # Динамические пороги
            df['adx_thresh'] = df['ADX_14'].rolling(192).quantile(0.75).fillna(25)
            df['rvol_thresh'] = df['rvol'].rolling(192).quantile(0.75).fillna(1.3)

            df = df.dropna()
            last = df.iloc[-1]

            imbalance, funding, oi_delta = await get_market_internals_async(symbol)
            signal, reasons = None, []

            # ЛОГИКА LONG
            if last['close'] > last['VWAP_D'] and last['close'] > last['EMA_200']:
                if last['ADX_14'] > last['adx_thresh'] and last['rvol'] > last['rvol_thresh']:
                    if last['STOCHRSIk_14_14_3_3'] < 20 and oi_delta > 0.1:
                        if spy_change > -0.2 and funding < 0.04:
                            signal = "LONG 🟢"
                            reasons = [f"ADX: {last['ADX_14']:.1f}", f"RVOL: {last['rvol']:.1f}",
                                       f"OI Delta: +{oi_delta:.2f}%"]

            # ЛОГИКА SHORT
            elif last['close'] < last['VWAP_D'] and last['close'] < last['EMA_200']:
                if last['ADX_14'] > last['adx_thresh'] and last['rvol'] > last['rvol_thresh']:
                    if last['STOCHRSIk_14_14_3_3'] > 80 and oi_delta > 0.1:
                        if spy_change < 0.2 and funding > -0.04:
                            signal = "SHORT 🔴"
                            reasons = [f"ADX: {last['ADX_14']:.1f}", f"RVOL: {last['rvol']:.1f}",
                                       f"OI Delta: +{oi_delta:.2f}%"]

            if signal:
                kelly_val = calculate_kelly()
                # Рисуем график асинхронно, чтобы не блокировать Event Loop
                chart = await asyncio.to_thread(create_signal_chart_sync, symbol, df)
                return {
                    "symbol": symbol, "side": signal, "entry": last['close'],
                    "conf": "Высокая" if kelly_val > 12 else "Средняя",
                    "risk_pct": f"{kelly_val / 4:.1f}%",
                    "oi": oi_delta, "reasons": reasons, "chart": chart
                }
        except Exception as e:
            print(f"Ошибка анализа {symbol}: [{type(e).__name__}] {e}")
            traceback.print_exc()
        return None


# ================== ИНТЕРФЕЙС ТЕЛЕГРАМ ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in users_db:
        await update.message.reply_text("🔒 Доступ закрыт.\nВведите код активации.")
        return

    is_admin = users_db[user_id]['role'] == 'admin'
    keyboard = [[InlineKeyboardButton("▶️ ЗАПУСТИТЬ АЛГОРИТМ", callback_data='on')]]

    if is_admin:
        keyboard.append([InlineKeyboardButton("🔑 ГЕНЕРИРОВАТЬ КОД", callback_data='gen_code')])

    status = "👑 Панель Админа" if is_admin else "✅ Доступ активен"
    await update.message.reply_text(f"{status}\nГотов к сканированию.", reply_markup=InlineKeyboardMarkup(keyboard),
                                    parse_mode='Markdown')


async def handle_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = update.message.text.strip()
    if user_id in users_db: return

    if code in referral_codes:
        users_db[user_id] = {'role': 'user'}
        del referral_codes[code]
        await update.message.reply_text("✅ Код принят! Нажмите /start")
    else:
        await update.message.reply_text("❌ Неверный код.")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global IS_RUNNING
    q = update.callback_query
    user_id = q.from_user.id
    await q.answer()

    if q.data == 'on' and users_db.get(user_id, {}).get('role') == 'admin':
        IS_RUNNING = True
        # Запускаем цикл анализа каждые 15 минут (900 секунд)
        context.job_queue.run_repeating(broadcast_signals, interval=60, first=1)
        await q.edit_message_text("🚀 Алгоритм запущен.")

    elif q.data == 'gen_code' and users_db.get(user_id, {}).get('role') == 'admin':
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        referral_codes[code] = True
        await context.bot.send_message(user_id, f"🎟 Новый код: {code}", parse_mode='Markdown')


async def send_with_semaphore(context, uid, photo, caption):
    """Безопасная отправка с учетом лимитов Telegram"""
    async with TG_SEM:
        try:
            photo.seek(0)
            await context.bot.send_photo(chat_id=uid, photo=photo, caption=caption, parse_mode='Markdown')
            await asyncio.sleep(0.05)
        except RetryAfter as e:
            print(f"⚠️ Flood Wait. Пауза {e.retry_after} сек.")
            await asyncio.sleep(e.retry_after)
            photo.seek(0)
            await context.bot.send_photo(chat_id=uid, photo=photo, caption=caption, parse_mode='Markdown')
        except Exception as e:
            print(f"Ошибка отправки UID {uid}: {e}")


async def broadcast_signals(context: ContextTypes.DEFAULT_TYPE):
    if not IS_RUNNING: return

    # Гарантируем, что aiohttp-сессия ccxt использует системный DNS-резолвер
    await ensure_exchange_session()

    # YFinance синхронный, выполняем в отдельном потоке
    spy = await asyncio.to_thread(get_spy_sentiment_sync)

    # Параллельный запуск анализа всех пар через gather
    tasks = [analyze_symbol_async(s, spy) for s in SYMBOLS]
    results = await asyncio.gather(*tasks)

    for res in results:
        if res:
            caption = (
                    f"🚨 СИГНАЛ: {res['side']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💎 Актив: #{res['symbol'].split('/')[0]}\n"
                    f"💰 Вход: {res['entry']:.4f}\n\n"
                    f"📊 Уверенность: {res['conf']}\n"
                    f"⚖️ Риск: {res['risk_pct']} от депо\n"
                    f"📈 OI Delta: {res['oi']:+.2f}%\n"
                    f"📋 Причины:\n" + "\n".join([f"• {r}" for r in res['reasons']]) +
                    f"\n━━━━━━━━━━━━━━━━━━━━"
            )

            target_users = list(users_db.keys())
            send_tasks = [send_with_semaphore(context, uid, res['chart'], caption) for uid in target_users]
            await asyncio.gather(*send_tasks)


# ================== ЗАПУСК ==================

async def on_shutdown(app):
    """Корректно отпускаем aiohttp-сессию ccxt при остановке бота."""
    try:
        await exchange.close()
    except Exception as e:
        print(f"Ошибка при закрытии ccxt: {e}")


if __name__ == "__main__":
    builder = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_shutdown(on_shutdown)
    )
    # Если PROXY_URL задан — пускаем Telegram-трафик через тот же SOCKS5,
    # что и ccxt. Нужно на серверах, где api.telegram.org недоступен
    # напрямую (российские хостинги, закрытые сети).
    if PROXY_URL:
        builder = builder.proxy(PROXY_URL).get_updates_proxy(PROXY_URL)
    app = builder.build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_auth))

    print("Бот успешно запущен (Async Mode). Ожидание команд...")
    app.run_polling()