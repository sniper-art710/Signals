from flask import Flask, render_template, request
from tradingview_ta import TA_Handler, Interval

app = Flask(__name__)

symbols = {
    "USDJPY": "OANDA:USDJPY",
    "EURUSD": "OANDA:EURUSD",
    "AUDUSD": "OANDA:AUDUSD",
    "GBPUSD": "OANDA:GBPUSD",
    "USDCAD": "OANDA:USDCAD",
    "USDCHF": "OANDA:USDCHF",
    "NZDUSD": "OANDA:NZDUSD",
    "EURJPY": "OANDA:EURJPY",
    "GBPJPY": "OANDA:GBPJPY",
    "AUDJPY": "OANDA:AUDJPY",
    "BTCUSD": "BINANCE:BTCUSDT"
}

# Take Profit and Stop Loss values for scalping
scalping_tp_sl = {
    "BTCUSD": (150, 100),         # $150 TP / $100 SL for BTC
    "default": (0.0015, 0.001)    # 15 pip TP / 10 pip SL for others
}

def get_signal(symbol, screener, exchange):
    handler = TA_Handler(
        symbol=symbol.split(":")[1],
        screener=screener,
        exchange=exchange,
        interval=Interval.INTERVAL_5_MINUTES
    )

    try:
        analysis = handler.get_analysis()
        summary = analysis.summary
        indicators = analysis.indicators

        recommendation = summary["RECOMMENDATION"]
        buy = summary["BUY"]
        sell = summary["SELL"]
        neutral = summary["NEUTRAL"]
        price = indicators.get("close")  # Entry price

        # Decide rounding precision
        if "BTC" in symbol:
            tp_val, sl_val = scalping_tp_sl["BTCUSD"]
            decimals = 2
        else:
            tp_val, sl_val = scalping_tp_sl.get(symbol.split(":")[1], scalping_tp_sl["default"])
            decimals = 3 if price < 1 else 2

        if recommendation in ["BUY", "STRONG_BUY"]:
            tp = round(price + tp_val, decimals)
            sl = round(price - sl_val, decimals)
            direction = "BUY"
        elif recommendation in ["SELL", "STRONG_SELL"]:
            tp = round(price - tp_val, decimals)
            sl = round(price + sl_val, decimals)
            direction = "SELL"
        else:
            tp = sl = None
            direction = "WAIT / NEUTRAL"

        return {
            'symbol': symbol.split(":")[1],
            'recommendation': recommendation,
            'buy': buy,
            'sell': sell,
            'neutral': neutral,
            'entry_price': round(price, decimals),
            'tp': tp,
            'sl': sl,
            'direction': direction
        }

    except Exception as e:
        return {'error': str(e)}

@app.route("/", methods=["GET", "POST"])
def index():
    selected_symbol = None
    signal_data = None

    if request.method == "POST":
        selected_symbol = request.form["symbol"]
        screener = "crypto" if "BINANCE" in symbols[selected_symbol] else "forex"
        exchange = symbols[selected_symbol].split(":")[0]
        signal_data = get_signal(symbols[selected_symbol], screener, exchange)

    return render_template("index.html", symbols=symbols, signal_data=signal_data, selected_symbol=selected_symbol)

if __name__ == "__main__":
    app.run(debug=True)