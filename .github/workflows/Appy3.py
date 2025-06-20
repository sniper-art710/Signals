import requests
from flask import Flask, render_template, request
from tradingview_ta import TA_Handler, Interval
import logging
from datetime import datetime, timedelta

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TWELVEDATA_API_KEY = "7a6e43e3e24c41cdaf946494e0be3e21"

symbols = {
    "EURUSD": "FX_IDC:EURUSD",
    "GBPUSD": "FX_IDC:GBPUSD",
    "USDJPY": "FX_IDC:USDJPY",
    "USDCHF": "FX_IDC:USDCHF",
    "AUDUSD": "FX_IDC:AUDUSD",
    "USDCAD": "FX_IDC:USDCAD",
    "NZDUSD": "FX_IDC:NZDUSD",
    "EURJPY": "FX_IDC:EURJPY",
    "GBPJPY": "FX_IDC:GBPJPY",
    "CHFJPY": "FX_IDC:CHFJPY",
    "EURGBP": "FX_IDC:EURGBP",
    "EURAUD": "FX_IDC:EURAUD",
    "AUDJPY": "FX_IDC:AUDJPY",
    "CADJPY": "FX_IDC:CADJPY",
    "BTCUSD": "BINANCE:BTCUSDT",
    "XAUUSD": "FX_IDC:XAUUSD"
}

atr_cache = {}

def get_atr_12data(symbol, interval="15min", time_period=14):
    cache_key = f"{symbol}{interval}{time_period}"
    if cache_key in atr_cache:
        cached_entry = atr_cache[cache_key]
        if datetime.now() - cached_entry['timestamp'] < timedelta(minutes=15):
            return cached_entry['value']

    api_symbol = "XAU/USD" if symbol == "XAUUSD" else "BTC/USD" if symbol == "BTCUSD" else symbol[:3] + "/" + symbol[3:]
    url = "https://api.twelvedata.com/atr"
    params = {
        "symbol": api_symbol,
        "interval": interval,
        "time_period": time_period,
        "apikey": TWELVEDATA_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "ok":
            logger.error(f"TwelveData API error: {data.get('message', 'Unknown error')}")
            return 0.001

        values = data.get("values", [])
        if not values:
            logger.warning(f"No ATR values returned for {symbol}")
            return 0.001

        latest_atr = float(values[0]["atr"])
        result = latest_atr if latest_atr > 0 else 0.001

        atr_cache[cache_key] = {
            'value': result,
            'timestamp': datetime.now()
        }

        return result

    except Exception as e:
        logger.error(f"Error fetching ATR: {str(e)}")
        return 0.001

def get_signal(symbol, screener, exchange):
    timeframes = [
        (Interval.INTERVAL_1_HOUR, 4),
        (Interval.INTERVAL_15_MINUTES, 3),
        (Interval.INTERVAL_5_MINUTES, 2),
        (Interval.INTERVAL_1_MINUTE, 1)
    ]

    price = rsi = macd = macd_signal = volume = ema_50 = ema_200 = None

    try:
        logger.info(f"Analyzing: {symbol}")

        for tf, weight in timeframes:
            try:
                handler = TA_Handler(
                    symbol=symbol.split(":")[1],
                    screener=screener,
                    exchange=exchange,
                    interval=tf
                )
                analysis = handler.get_analysis()
                indicators = analysis.indicators

                if tf == Interval.INTERVAL_15_MINUTES:
                    price = indicators.get("close")
                    rsi = indicators.get("RSI")
                    macd = indicators.get("MACD.macd")
                    macd_signal = indicators.get("MACD.signal")
                    volume = indicators.get("volume")

                if tf == Interval.INTERVAL_1_HOUR:
                    ema_50 = indicators.get("EMA50")
                    ema_200 = indicators.get("EMA200")

            except Exception as e:
                logger.warning(f"Error in {tf}: {str(e)}")
                continue

        votes = {"BUY": 0, "SELL": 0}

        if rsi is not None:
            if rsi < 30:
                votes["BUY"] += 1
            elif rsi > 70:
                votes["SELL"] += 1

        if macd is not None and macd_signal is not None:
            if macd > macd_signal:
                votes["BUY"] += 1
            elif macd < macd_signal:
                votes["SELL"] += 1

        if ema_50 and ema_200:
            if ema_50 > ema_200:
                votes["BUY"] += 1
            elif ema_50 < ema_200:
                votes["SELL"] += 1

        atr_15 = get_atr_12data(symbol.split(":")[1], interval="15min")
        atr_1h = get_atr_12data(symbol.split(":")[1], interval="1h")
        atr = (atr_15 + atr_1h) / 2

        if atr > 0.01:
            votes["BUY"] += 1
        else:
            votes["SELL"] += 1

        if volume and volume > 1000:
            votes["BUY"] += 1
        elif volume:
            votes["SELL"] += 1

        # Final direction logic
        min_votes_required = 3
        direction = "NEUTRAL"
        if votes["BUY"] >= min_votes_required and votes["BUY"] > votes["SELL"]:
            direction = "BUY"
        elif votes["SELL"] >= min_votes_required and votes["SELL"] > votes["BUY"]:
            direction = "SELL"

        # If unclear or low confidence, return NEUTRAL
        if abs(votes["BUY"] - votes["SELL"]) <= 1 or max(votes.values()) < min_votes_required:
            direction = "NEUTRAL"

        confidence = round((max(votes.values()) / 7) * 100, 2)

        base_symbol = symbol.split(":")[1]
        decimals = 2 if base_symbol in ["BTCUSDT", "XAUUSD"] else 5

        tp = sl = None
        if direction != "NEUTRAL" and price and atr:
            rel_vol = atr / price if price else 0
            base_mult = 0.7 + min(rel_vol * 50, 1.2)

            if volume and volume < 400:
                base_mult += 0.2
            if confidence < 40:
                base_mult += 0.2
            if rsi and 45 < rsi < 55:
                base_mult += 0.1

            tp_mult = base_mult
            sl_mult = base_mult * 0.95

            if direction == "BUY":
                tp = round(price + atr * tp_mult, decimals)
                sl = round(price - atr * sl_mult, decimals)
            elif direction == "SELL":
                tp = round(price - atr * tp_mult, decimals)
                sl = round(price + atr * sl_mult, decimals)

        return {
            'symbol': base_symbol,
            'direction': direction,
            'confidence': confidence,
            'entry_price': round(price, decimals) if price else None,
            'tp': tp,
            'sl': sl,
            'rsi': round(rsi, 2) if rsi else None,
            'atr': round(atr, 5) if atr else None,
            'volume': round(volume, 2) if volume else None,
            'trend': "Bullish" if ema_50 and ema_200 and ema_50 > ema_200 else
                     "Bearish" if ema_50 and ema_200 and ema_50 < ema_200 else "Neutral"
        }

    except Exception as e:
        logger.error(f"Signal error: {str(e)}", exc_info=True)
        return {'error': str(e)}

@app.route("/", methods=["GET", "POST"])
def index():
    selected_symbol = None
    signal_data = None

    if request.method == "POST":
        selected_symbol = request.form.get("symbol")
        if selected_symbol in symbols:
            screener = "cfd" if "XAU" in selected_symbol else "crypto" if "BTC" in selected_symbol else "forex"
            exchange = symbols[selected_symbol].split(":")[0]
            signal_data = get_signal(symbols[selected_symbol], screener, exchange)
        else:
            signal_data = {'error': 'Invalid symbol selected'}

    return render_template("index.html",
                           symbols=symbols.keys(),
                           signal_data=signal_data,
                           selected_symbol=selected_symbol)

if __name__ == "__main__":
    app.run(debug=True)
