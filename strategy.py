import pandas as pd

from config import LEVERAGE, STAKE_EUR, STOP_PNL_EUR, TARGET_PNL_EUR
from indicators import add_indicators
from market_data import convert_to_eur_price, get_fx_context, get_market_quote


def _support_resistance(df):
    window = df.tail(40)
    support = float(window["Low"].rolling(20).min().iloc[-1])
    resistance = float(window["High"].rolling(20).max().iloc[-1])
    return support, resistance


def _make_setup_label(direction, trend, structure, sweep, breakout, retest, fvg):
    if direction == "LONG":
        parts = [trend, structure, sweep, breakout, retest, fvg]
        return " | ".join([p for p in parts if p])
    parts = [trend, structure, sweep, breakout, retest, fvg]
    return " | ".join([p for p in parts if p])


def make_signal(symbol, dataframes, market_quote=None):
    if dataframes is None:
        return None
    required = ["15m", "1h", "4h", "1d"]
    if any(key not in dataframes or dataframes[key] is None or dataframes[key].empty for key in required):
        return None

    m15 = add_indicators(dataframes["15m"]).dropna()
    h1 = add_indicators(dataframes["1h"]).dropna()
    h4 = add_indicators(dataframes["4h"]).dropna()
    d1 = add_indicators(dataframes["1d"]).dropna()
    if len(m15) < 50 or len(h1) < 50 or len(h4) < 50 or len(d1) < 200:
        return None

    last15 = m15.iloc[-1]
    last1h = h1.iloc[-1]
    last4h = h4.iloc[-1]
    last1d = d1.iloc[-1]
    if market_quote is None:
        market_quote = get_market_quote(symbol)
    if not market_quote.get("verified"):
        return None
    price = float(market_quote["price"])
    atr = float(last15["ATR"]) if pd.notna(last15["ATR"]) else 0.0
    if atr <= 0:
        return None

    support_15m, resistance_15m = _support_resistance(m15)
    support_1h, resistance_1h = _support_resistance(h1)
    support_4h, resistance_4h = _support_resistance(h4)

    daily_long = float(last1d["Close"]) > float(last1d["MA20"]) > float(last1d["MA50"]) > float(last1d["MA200"])
    daily_short = float(last1d["Close"]) < float(last1d["MA20"]) < float(last1d["MA50"]) < float(last1d["MA200"])
    h4_long = float(last4h["Close"]) > float(last4h["MA20"]) > float(last4h["MA50"]) > float(last4h["MA200"])
    h4_short = float(last4h["Close"]) < float(last4h["MA20"]) < float(last4h["MA50"]) < float(last4h["MA200"])

    long_score = 0
    short_score = 0
    setup_parts = {"LONG": [], "SHORT": []}

    if daily_long or h4_long:
        long_score += 2
        setup_parts["LONG"].append("Major trend")
    if daily_short or h4_short:
        short_score += 2
        setup_parts["SHORT"].append("Major trend")

    if float(last15["Close"]) > float(last15["MA20"]):
        long_score += 1
    if float(last15["Close"]) < float(last15["MA20"]):
        short_score += 1
    if float(last1h["Close"]) > float(last1h["MA20"]):
        long_score += 1
        setup_parts["LONG"].append("1H trend")
    if float(last1h["Close"]) < float(last1h["MA20"]):
        short_score += 1
        setup_parts["SHORT"].append("1H trend")

    if 50 <= float(last15["RSI"]) <= 70:
        long_score += 1
    if 30 <= float(last15["RSI"]) <= 50:
        short_score += 1
    if float(last15["MACD"]) > float(last15["MACD_SIGNAL"]):
        long_score += 1
    if float(last15["MACD"]) < float(last15["MACD_SIGNAL"]):
        short_score += 1
    if float(last15["Volume"]) > float(last15["VOL_MA20"]):
        long_score += 1
        short_score += 1

    liquidity_long = float(last15["Low"]) <= support_15m * 1.002 and float(last15["Close"]) > support_15m
    liquidity_short = float(last15["High"]) >= resistance_15m * 0.998 and float(last15["Close"]) < resistance_15m
    breakout_long = float(last15["Close"]) > resistance_15m * 0.995 and float(last15["Close"]) > float(m15["Close"].iloc[-2])
    breakout_short = float(last15["Close"]) < support_15m * 1.005 and float(last15["Close"]) < float(m15["Close"].iloc[-2])
    retest_long = float(last15["Close"]) > support_15m * 1.005 and float(last15["Low"]) < support_15m * 1.005
    retest_short = float(last15["Close"]) < resistance_15m * 0.995 and float(last15["High"]) > resistance_15m * 0.995

    if liquidity_long:
        long_score += 1
        setup_parts["LONG"].append("Liquidity sweep")
    if liquidity_short:
        short_score += 1
        setup_parts["SHORT"].append("Liquidity sweep")
    if breakout_long:
        long_score += 1
        setup_parts["LONG"].append("Breakout")
    if breakout_short:
        short_score += 1
        setup_parts["SHORT"].append("Breakout")
    if retest_long:
        long_score += 1
        setup_parts["LONG"].append("Retest")
    if retest_short:
        short_score += 1
        setup_parts["SHORT"].append("Retest")

    # FVG / order-block style confirmation using recent impulse candles.
    recent = m15.tail(20)
    close_last = float(recent["Close"].iloc[-1])
    open_last = float(recent["Open"].iloc[-1])
    high_last = float(recent["High"].iloc[-1])
    low_last = float(recent["Low"].iloc[-1])
    impulse_up = (close_last > open_last) and (high_last - close_last) < (close_last - low_last)
    impulse_down = (close_last < open_last) and (close_last - low_last) < (high_last - close_last)

    if impulse_up and close_last > support_15m:
        long_score += 1
        setup_parts["LONG"].append("FVG / OB")
    if impulse_down and close_last < resistance_15m:
        short_score += 1
        setup_parts["SHORT"].append("FVG / OB")

    if float(last15["Close"]) > float(last15["Low"]) and float(last15["Low"]) < support_15m * 1.005:
        long_score += 1
    if float(last15["Close"]) < float(last15["High"]) and float(last15["High"]) > resistance_15m * 0.995:
        short_score += 1

    if price > support_1h * 1.01:
        long_score += 1
    if price < resistance_1h * 0.99:
        short_score += 1

    if abs(price - support_15m) <= 0.03 * price:
        long_score += 1
    if abs(price - resistance_15m) <= 0.03 * price:
        short_score += 1

    # Keep the core market structure mandatory while allowing supporting filters
    # to contribute through a balanced score.
    max_signal_score = 14
    minimum_score = int(max_signal_score * 0.7 + 0.9999)
    long_trend = daily_long or h4_long
    short_trend = daily_short or h4_short
    long_structure = liquidity_long or breakout_long or retest_long
    short_structure = liquidity_short or breakout_short or retest_short

    direction = None
    score = 0
    setup = ""
    if (
        long_trend
        and long_structure
        and long_score >= minimum_score
        and long_score >= short_score + 2
    ):
        direction = "LONG"
        score = long_score
        setup = " | ".join(setup_parts["LONG"][:5]) if setup_parts["LONG"] else "Structure + confirmation"
    elif (
        short_trend
        and short_structure
        and short_score >= minimum_score
        and short_score >= long_score + 2
    ):
        direction = "SHORT"
        score = short_score
        setup = " | ".join(setup_parts["SHORT"][:5]) if setup_parts["SHORT"] else "Structure + confirmation"
    else:
        return None

    move = TARGET_PNL_EUR / (STAKE_EUR * LEVERAGE)
    fx_ctx = get_fx_context(symbol, market_quote.get("currency"))
    if fx_ctx["status"] not in {"CURRENT"} or fx_ctx["rate"] is None:
        return None
    entry_eur = convert_to_eur_price(price, symbol, market_quote.get("currency"))
    if entry_eur is None or entry_eur <= 0:
        return None
    if direction == "LONG":
        tp = entry_eur * (1 + move)
        sl = entry_eur * (1 - move)
    else:
        tp = entry_eur * (1 - move)
        sl = entry_eur * (1 + move)

    if abs(tp - entry_eur) > abs((TARGET_PNL_EUR / (STAKE_EUR * LEVERAGE)) * entry_eur) * 1.02:
        return None
    if abs(entry_eur - sl) > abs((STOP_PNL_EUR / (STAKE_EUR * LEVERAGE)) * entry_eur) * 1.02:
        return None

    result = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry_eur,
        "tp": tp,
        "sl": sl,
        "score": int(score),
        "setup": setup,
        "timestamp": market_quote["timestamp"],
        "market_price": price,
        "market_currency": market_quote["currency"],
        "market_exchange": market_quote["exchange"],
        "market_timestamp": market_quote["timestamp"],
        "market_source": market_quote["source"],
        "price_status": market_quote["status"],
        "signal_price": price,
        "signal_currency": market_quote["currency"],
        "fx_rate": fx_ctx["rate"],
        "fx_currency": fx_ctx["currency"],
        "fx_pair": fx_ctx["pair"],
        "fx_timestamp": fx_ctx["timestamp"],
        "fx_status": fx_ctx["status"],
        "fx_source": fx_ctx["source"],
    }
    return result
