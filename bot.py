
import os
import asyncio
import logging
from decimal import Decimal, InvalidOperation

import yfinance as yf
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")
logging.basicConfig(level=logging.INFO)

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Set Lot Size", callback_data="lot")],
        [InlineKeyboardButton("📊 Generate Gold Signal", callback_data="signal")]
    ])

def indicators(df):
    df = df.copy()
    df["EMA9"] = df["Close"].ewm(span=9).mean()
    df["EMA21"] = df["Close"].ewm(span=21).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["RSI"] = 100 - (100 / (1 + rs))
    fast = df["Close"].ewm(span=12).mean()
    slow = df["Close"].ewm(span=26).mean()
    df["MACD"] = fast - slow
    df["MACD_SIGNAL"] = df["MACD"].ewm(span=9).mean()
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift()).abs(),
        (df["Low"] - df["Close"].shift()).abs()
    ], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(14).mean()
    return df.dropna()

def get_data(interval):
    df = yf.download(
        "XAUUSD=X", period="5d", interval=interval,
        progress=False, auto_adjust=False, threads=False
    )
    if df.empty:
        raise ValueError("Gold market data is unavailable.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return indicators(df)

def generate_signal(lot):
    five = get_data("5m")
    fifteen = get_data("15m")

    a = five.iloc[-2]
    b = fifteen.iloc[-2]

    buy = (
        a["Close"] > a["EMA21"]
        and a["EMA9"] > a["EMA21"]
        and a["RSI"] > 52 and a["RSI"] < 70
        and a["MACD"] > a["MACD_SIGNAL"]
        and b["Close"] > b["EMA21"]
        and b["EMA9"] > b["EMA21"]
    )

    sell = (
        a["Close"] < a["EMA21"]
        and a["EMA9"] < a["EMA21"]
        and a["RSI"] < 48 and a["RSI"] > 30
        and a["MACD"] < a["MACD_SIGNAL"]
        and b["Close"] < b["EMA21"]
        and b["EMA9"] < b["EMA21"]
    )

    price = float(a["Close"])
    atr = float(a["ATR"])

    if buy:
        side = "BUY 🟢"
        sl = price - (1.5 * atr)
        tp1 = price + (2 * atr)
        tp2 = price + (3 * atr)
    elif sell:
        side = "SELL 🔴"
        sl = price + (1.5 * atr)
        tp1 = price - (2 * atr)
        tp2 = price - (3 * atr)
    else:
        return (
            "⏸ NO TRADE\n\n"
            "5m اور 15m کی تصدیق مکمل نہیں ہوئی۔\n"
            "اگلے موقع پر دوبارہ Generate کریں۔"
        )

    return (
        "🏆 BILAL GOLD AI\n"
        "━━━━━━━━━━━━━━\n"
        f"Symbol: XAUUSD (Gold)\n"
        f"Signal: {side}\n"
        f"Lot Size: {lot}\n\n"
        f"Entry: {price:.2f}\n"
        f"Stop Loss: {sl:.2f}\n"
        f"Take Profit 1: {tp1:.2f}\n"
        f"Take Profit 2: {tp2:.2f}\n\n"
        "Strategy: EMA + RSI + MACD + ATR\n"
        "Timeframes: 5m + 15m\n\n"
        "⚠️ یہ تعلیمی سگنل ہے، منافع کی ضمانت نہیں۔ "
        "Yahoo قیمت MT5 بروکر کی قیمت سے مختلف ہو سکتی ہے۔ "
        "Trade سے پہلے اپنے MT5 پر قیمت چیک کریں۔"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["lot"] = "0.01"
    await update.message.reply_text(
        "👋 Welcome to BILAL GOLD AI!\n\n"
        "Gold XAUUSD Signal Generator\n"
        "اپنی Lot Size منتخب کریں:",
        reply_markup=menu()
    )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "lot":
        context.user_data["waiting_lot"] = True
        await query.message.reply_text(
            "اپنی Lot Size لکھیں۔ مثال: 0.01"
        )

    elif query.data == "signal":
        lot = context.user_data.get("lot", "0.01")
        await query.message.reply_text("🔍 Gold کا تجزیہ ہو رہا ہے...")
        try:
            result = await asyncio.to_thread(generate_signal, lot)
            await query.message.reply_text(result, reply_markup=menu())
        except Exception as e:
            logging.exception("Signal error")
            await query.message.reply_text(
                "Live Gold Data ابھی دستیاب نہیں۔ بعد میں دوبارہ کوشش کریں۔",
                reply_markup=menu()
            )

async def receive_lot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("waiting_lot"):
        return

    try:
        lot = Decimal(update.message.text.strip())
        if not lot.is_finite() or lot <= 0 or lot > 100:
            raise InvalidOperation
        context.user_data["lot"] = str(lot)
        context.user_data["waiting_lot"] = False
        await update.message.reply_text(
            f"✅ Lot Size محفوظ ہوگئی: {lot}\n"
            "اب Generate Gold Signal دبائیں۔",
            reply_markup=menu()
        )
    except (InvalidOperation, ValueError):
        await update.message.reply_text(
            "درست Lot Size لکھیں، مثلاً 0.01"
        )

def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable missing")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_lot))
    app.run_polling()

if __name__ == "__main__":
    main()
