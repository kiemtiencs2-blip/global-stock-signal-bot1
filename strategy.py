from config import STAKE_EUR, LEVERAGE, TARGET_PNL_EUR
from indicators import add_indicators

def make_signal(symbol, df):
    if df.empty or len(df) < 220:
        return None

    x = add_indicators(df)
    last, prev = x.iloc[-1], x.iloc[-2]

    vals = [last[c] for c in ["Close","MA20","MA50","MA200","RSI","MACD","MACD_SIGNAL","ATR","VOL_MA20"]]
    if any(v != v for v in vals):
        return None

    price = float(last["Close"])
    long_score = 0
    short_score = 0

    if price > last["MA20"]: long_score += 1
    if last["MA20"] > last["MA50"]: long_score += 1
    if last["MA50"] > last["MA200"]: long_score += 1
    if last["MACD"] > last["MACD_SIGNAL"]: long_score += 1
    if 50 <= last["RSI"] <= 70: long_score += 1
    if last["Volume"] > last["VOL_MA20"] and price > float(prev["Close"]): long_score += 1

    if price < last["MA20"]: short_score += 1
    if last["MA20"] < last["MA50"]: short_score += 1
    if last["MA50"] < last["MA200"]: short_score += 1
    if last["MACD"] < last["MACD_SIGNAL"]: short_score += 1
    if 30 <= last["RSI"] <= 50: short_score += 1
    if last["Volume"] > last["VOL_MA20"] and price < float(prev["Close"]): short_score += 1

    if long_score >= 4 and long_score > short_score:
        direction, score = "LONG", long_score
    elif short_score >= 4 and short_score > long_score:
        direction, score = "SHORT", short_score
    else:
        return None

    move = TARGET_PNL_EUR / (STAKE_EUR * LEVERAGE)
    tp = price * (1 + move) if direction == "LONG" else price * (1 - move)
    sl = price * (1 - move) if direction == "LONG" else price * (1 + move)

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": price,
        "tp": tp,
        "sl": sl,
        "score": score,
    }
