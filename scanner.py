from market_data import download_daily
from strategy import make_signal

def scan_watchlist(watchlist):
    results = []
    for symbol in watchlist:
        try:
            df = download_daily(symbol)
            signal = make_signal(symbol, df)
            if signal:
                results.append(signal)
        except Exception:
            continue
    return results
