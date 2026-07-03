from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import requests
import json
import os
import time
from datetime import datetime
import logging
from typing import Dict

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = "YOUR_BOT_TOKEN"  # ← ប្តូរ
TWELVE_DATA_API_KEYS = ["YOUR_API_KEY_1", "YOUR_API_KEY_2"]  # ← ប្តូរ

SYMBOL_MAP = {
    "eurusd": "EUR/USD", "gbpusd": "GBP/USD", "usdjpy": "USD/JPY",
    "audusd": "AUD/USD", "usdcad": "USD/CAD", "nzdusd": "NZD/USD",
    "usdchf": "USD/CHF", "xauusd": "XAU/USD",
    "btcusd": "BTC/USD", "ethusd": "ETH/USD", "solusd": "SOL/USD",
}

TIMEFRAMES = {"m5": "5min", "m15": "15min", "m30": "30min", "h1": "1h", "h4": "4h", "d1": "1day"}
DEFAULT_TF = "h1"

class Cache:
    def __init__(self):
        self.file = "forex_cache.json"
        self.data = self._load()
    def _load(self):
        if os.path.exists(self.file):
            try:
                with open(self.file, 'r') as f: return json.load(f)
            except: return {}
        return {}
    def get(self, key, max_age=180):
        if key in self.data and time.time() - self.data[key]['ts'] < max_age:
            return self.data[key]['data']
        return None
    def set(self, key, data):
        self.data[key] = {'ts': time.time(), 'data': data}
        with open(self.file, 'w') as f: json.dump(self.data, f)

cache = Cache()

class MarketAnalyzer:
    @staticmethod
    def calculate_rsi(prices, period=14):
        if len(prices) < period + 1: return None
        gains = [max(prices[i] - prices[i-1], 0) for i in range(1, len(prices))]
        losses = [max(prices[i-1] - prices[i], 0) for i in range(1, len(prices))]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period-1) + gains[i]) / period
            avg_loss = (avg_loss * (period-1) + losses[i]) / period
        return 100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))

    @staticmethod
    def analyze(symbol: str, tf: str):
        cache_key = f"{symbol}_{tf}"
        cached = cache.get(cache_key)
        if cached: return cached

        api_tf = TIMEFRAMES.get(tf, TIMEFRAMES[DEFAULT_TF])
        symbol_api = SYMBOL_MAP.get(symbol, symbol.upper())

        for api_key in TWELVE_DATA_API_KEYS:
            if not api_key or "YOUR_" in api_key: continue
            try:
                resp = requests.get("https://api.twelvedata.com/time_series",
                    params={"symbol": symbol_api, "interval": api_tf, "outputsize": 100, "apikey": api_key}, timeout=12)
                data = resp.json()
                if "values" not in data: continue

                values = list(reversed(data["values"]))
                closes = [float(v["close"]) for v in values]
                price = closes[-1]

                rsi = MarketAnalyzer.calculate_rsi(closes)
                score = 0
                signals = []

                if rsi:
                    if rsi < 30:
                        score += 2
                        signals.append(f"📈 RSI Oversold ({rsi:.1f})")
                    elif rsi > 70:
                        score -= 2
                        signals.append(f"📉 RSI Overbought ({rsi:.1f})")
                    else:
                        signals.append(f"RSI: {rsi:.1f}")

                if len(closes) >= 20:
                    ma10 = sum(closes[-10:]) / 10
                    ma20 = sum(closes[-20:]) / 20
                    if ma10 > ma20:
                        score += 1
                        signals.append("📈 MA Bullish")
                    else:
                        score -= 1
                        signals.append("📉 MA Bearish")

                highs = [float(v["high"]) for v in values[-14:]]
                lows = [float(v["low"]) for v in values[-14:]]
                atr = max(highs) - min(lows) if highs else price * 0.008

                if score >= 3:
                    bias = "🟢 STRONG BUY"
                    sl = round(price - 1.8*atr, 4)
                    tp = round(price + 3.8*atr, 4)
                elif score >= 1:
                    bias = "🟢 BUY"
                    sl = round(price - 1.6*atr, 4)
                    tp = round(price + 3.2*atr, 4)
                elif score <= -3:
                    bias = "🔴 STRONG SELL"
                    sl = round(price + 1.8*atr, 4)
                    tp = round(price - 3.8*atr, 4)
                else:
                    bias = "🟡 NEUTRAL"
                    sl = tp = None

                result = {
                    "price": round(price, 4 if "usd" in symbol.lower() else 2),
                    "bias": bias,
                    "score": score,
                    "rsi": round(rsi, 1) if rsi else None,
                    "sl": sl,
                    "tp": tp,
                    "signals": signals
                }
                cache.set(cache_key, result)
                return result
            except:
                continue
        raise Exception(f"មិនអាចទាញទិន្នន័យ {symbol} បាន។")

class TradeMindBot:
    def __init__(self):
        self.app = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()

    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("signal", self.signal))

        for pair in SYMBOL_MAP:
            self.app.add_handler(CommandHandler(pair, self.create_pair_handler(pair)))

        self.app.add_handler(CallbackQueryHandler(self.button_callback))

    def create_pair_handler(self, pair):
        async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            tf = context.args[0] if context.args else DEFAULT_TF
            await self.show_analysis(update, pair, tf)
        return handler

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html("<b>🌟 TradeMind AI v2.9</b>\n━━━━━━━━━━━━━━━━━━━\nសួស្តី! សាកល្បង /xauusd h1")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html("បញ្ជា៖ /eurusd h1, /xauusd h4, /btcusd m15")

    async def show_analysis(self, update: Update, pair: str, tf: str):
        await update.message.reply_text(f"🔄 កំពុងវិភាគ {pair.upper()} ({tf})...")
        try:
            result = MarketAnalyzer.analyze(pair, tf)
            text = f"""
📊 <b>{SYMBOL_MAP.get(pair, pair.upper())}</b> | {tf}
━━━━━━━━━━━━━━━━━━━
💰 Price: <b>{result['price']}</b>
🎯 Signal: <b>{result['bias']}</b>
📈 Score: {result['score']}

RSI: {result.get('rsi', 'N/A')}
"""
            for s in result.get('signals', []):
                text += f"{s}\n"
            if result.get('sl'):
                text += f"\n🛡️ SL: {result['sl']}\n🟢 TP: {result['tp']}"
            text += "\n\n⚠️ Educational only."
            await update.message.reply_html(text)
        except Exception as e:
            await update.message.reply_text(f"❌ {str(e)}")

    async def signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /signal xauusd h1")
            return
        pair = context.args[0].lower()
        tf = context.args[1] if len(context.args) > 1 else DEFAULT_TF
        if pair in SYMBOL_MAP:
            await self.show_analysis(update, pair, tf)
        else:
            await update.message.reply_text("Pair មិនត្រឹមត្រូវ")

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()

    def run(self):
        logging.info("🚀 Bot Started")
        self.app.run_polling()

if __name__ == "__main__":
    bot = TradeMindBot()
    bot.run()
