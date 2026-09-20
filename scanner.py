from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from threading import Lock

import pandas as pd

from market_data import download_ohlcv, get_market_quote
from strategy import make_signal


def dedupe_signals(results, prior_results=None):
    prior_results = prior_results or []
    unique = []
    seen = set()
    for signal in results:
        key = (signal["symbol"].upper(), signal["direction"])
        existing = next((x for x in prior_results if (x["symbol"].upper(), x["direction"]) == key), None)
        if existing is not None:
            same_entry = abs(float(existing["entry"]) - float(signal["entry"])) / max(float(existing["entry"]), 1e-9) < 0.02
            same_tp = abs(float(existing["tp"]) - float(signal["tp"])) / max(float(existing["tp"]), 1e-9) < 0.02
            same_sl = abs(float(existing["sl"]) - float(signal["sl"])) / max(float(existing["sl"]), 1e-9) < 0.02
            if same_entry and same_tp and same_sl:
                continue
        if key not in seen:
            seen.add(key)
            unique.append(signal)
    return unique


MAX_SCAN_WORKERS = 8
TICKER_TIMEOUT_SECONDS = 20


def _report_progress(progress_callback, completed, total, symbol, status):
    if progress_callback is None:
        return
    try:
        progress_callback(completed, total, symbol, status)
    except Exception:
        pass


def _scan_symbol(symbol, data_cache, cache_lock):
    def cached_download(interval, period):
        key = (symbol, interval, period)
        with cache_lock:
            if key in data_cache:
                return data_cache[key]
        frame = download_ohlcv(symbol, interval=interval, period=period)
        with cache_lock:
            data_cache[key] = frame
        return frame

    market_quote = get_market_quote(symbol)
    if not market_quote["verified"]:
        return None, {
            "symbol": symbol,
            "status": market_quote["status"],
            "reason": market_quote["reason"],
            "timestamp": market_quote["timestamp"],
            "source": market_quote["source"],
        }
    data = {
        "15m": cached_download("15m", "60d"),
        "1h": cached_download("1h", "200d"),
        "4h": cached_download("4h", "365d"),
        "1d": cached_download("1d", "5y"),
    }
    signal = make_signal(symbol, data, market_quote=market_quote)
    if signal and "timestamp" not in signal:
        signal["timestamp"] = pd.Timestamp.now(tz="UTC")
    return signal, None


def scan_watchlist(watchlist, progress_callback=None, timeout_seconds=TICKER_TIMEOUT_SECONDS):
    results = []
    scan_watchlist.last_rejections = []
    data_cache = {}
    cache_lock = Lock()
    pending = {}
    completed = 0
    total = len(watchlist)
    executor = ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS)
    try:
        for symbol in watchlist:
            pending[executor.submit(_scan_symbol, symbol, data_cache, cache_lock)] = (symbol, pd.Timestamp.now())
        while pending:
            done, _ = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            now = pd.Timestamp.now()
            for future in done:
                symbol, started = pending.pop(future)
                completed += 1
                if (now - started).total_seconds() >= timeout_seconds:
                    scan_watchlist.last_rejections.append({
                        "symbol": symbol,
                        "status": "TIMEOUT",
                        "reason": f"Ticker scan exceeded {timeout_seconds} seconds.",
                        "timestamp": None,
                        "source": "scanner",
                    })
                    status = "timeout"
                    _report_progress(progress_callback, completed, total, symbol, status)
                    continue
                try:
                    signal, rejection = future.result()
                    if signal:
                        results.append(signal)
                    if rejection:
                        scan_watchlist.last_rejections.append(rejection)
                    status = "signal" if signal else "checked"
                except Exception as exc:
                    rejection = {"symbol": symbol, "status": "ERROR", "reason": str(exc), "timestamp": None, "source": "scanner"}
                    scan_watchlist.last_rejections.append(rejection)
                    status = "failed"
                _report_progress(progress_callback, completed, total, symbol, status)
            expired = [future for future, (symbol, started) in pending.items() if (now - started).total_seconds() >= timeout_seconds]
            for future in expired:
                symbol, _ = pending.pop(future)
                future.cancel()
                completed += 1
                scan_watchlist.last_rejections.append({
                    "symbol": symbol,
                    "status": "TIMEOUT",
                    "reason": f"Ticker scan exceeded {timeout_seconds} seconds.",
                    "timestamp": None,
                    "source": "scanner",
                })
                _report_progress(progress_callback, completed, total, symbol, "timeout")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return results


scan_watchlist.last_rejections = []
