import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    if x.empty:
        return x
    close = x["Close"]
    high = x["High"]
    low = x["Low"]
    vol = x["Volume"]

    x["MA20"] = close.rolling(20).mean()
    x["MA50"] = close.rolling(50).mean()
    x["MA200"] = close.rolling(200).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    x["RSI"] = 100 - 100 / (1 + rs)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    x["MACD"] = ema12 - ema26
    x["MACD_SIGNAL"] = x["MACD"].ewm(span=9, adjust=False).mean()

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    x["ATR"] = tr.rolling(14).mean()
    x["VOL_MA20"] = vol.rolling(20).mean()
    return x
