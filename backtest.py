import pandas as pd
from market_data import download_daily

def evaluate_signal(signal, period="3mo"):
    df = download_daily(signal["symbol"], period=period)
    if df.empty:
        return {"status": "NO DATA"}

    entry = float(signal["entry"])
    tp = float(signal["tp"])
    sl = float(signal["sl"])
    direction = signal["direction"]

    future = df[df.index > pd.Timestamp(signal["timestamp"])]
    for idx, row in future.iterrows():
        hi, lo = float(row["High"]), float(row["Low"])

        if direction == "LONG":
            hit_tp, hit_sl = hi >= tp, lo <= sl
        else:
            hit_tp, hit_sl = lo <= tp, hi >= sl

        if hit_tp and hit_sl:
            return {"status": "UNCERTAIN", "timestamp": idx}
        if hit_tp:
            return {"status": "WIN", "timestamp": idx, "pnl_eur": 20.0}
        if hit_sl:
            return {"status": "LOSS", "timestamp": idx, "pnl_eur": -20.0}

    return {"status": "OPEN"}
