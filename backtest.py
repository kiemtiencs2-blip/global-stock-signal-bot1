import pandas as pd
from functools import lru_cache

from config import WATCHLIST
from market_data import _currency_for_symbol, download_daily, download_ohlc
from strategy import make_signal


PERIOD_DAYS = (30, 90, 180, 365)
PROVIDER_WINDOWS = {
    "15m": pd.Timedelta(days=60),
    "1h": pd.Timedelta(days=730),
    "4h": pd.Timedelta(days=1825),
    "1d": pd.Timedelta(days=3650),
}


def _utc_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _normalise_index(df):
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    result.index = pd.DatetimeIndex([_utc_timestamp(value) for value in result.index])
    return result[~result.index.duplicated(keep="last")].sort_index()


def _rows_at_or_before(df, timestamp):
    """Return rows at or before a UTC-normalized pandas timestamp."""
    frame = _normalise_index(df)
    if frame.empty:
        return frame
    signal_timestamp = _utc_timestamp(timestamp)
    return frame.loc[frame.index <= signal_timestamp]


TIMEFRAME_ORDER = ("15m", "1h", "4h", "1d")
TIMEFRAME_DURATION = {
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}
RESULT_STATUSES = frozenset({"WIN", "LOSS", "OPEN", "DATA_UNAVAILABLE"})
LEGACY_RESULT_STATUSES = {
    "UNCERTAIN": "DATA_UNAVAILABLE",
    "NO ENTRY": "DATA_UNAVAILABLE",
    "NO DATA": "DATA_UNAVAILABLE",
}


def _data_unavailable():
    return {"status": "DATA_UNAVAILABLE", "exit_timestamp": None, "pnl_eur": 0.0}


def _normalise_result(result):
    normalised = dict(result or {})
    status = normalised.get("status")
    result_value = normalised.get("result")
    candidate = status if status in RESULT_STATUSES else result_value
    normalized_status = LEGACY_RESULT_STATUSES.get(candidate, candidate)
    if normalized_status not in RESULT_STATUSES:
        normalised.update(_data_unavailable())
        normalized_status = "DATA_UNAVAILABLE"
    else:
        normalised["status"] = normalized_status
    normalised["result"] = normalized_status
    normalised.setdefault("pnl_eur", 0.0)
    return normalised


def _timeframe_is_available(signal_timestamp, timeframe, now=None):
    now = now or pd.Timestamp.now(tz="UTC")
    return signal_timestamp >= now - PROVIDER_WINDOWS[timeframe]


@lru_cache(maxsize=256)
def _download_historical_cached(symbol, timeframe, period):
    return _normalise_index(download_ohlc(symbol, timeframe, period))


def _historical_frames(symbol, signal_timestamp, now):
    periods = {"15m": "60d", "1h": "730d", "4h": "5y", "1d": "10y"}
    frames = {}
    for timeframe in TIMEFRAME_ORDER:
        if _timeframe_is_available(signal_timestamp, timeframe, now):
            frames[timeframe] = _download_historical_cached(
                symbol, timeframe, periods[timeframe]
            )
        else:
            frames[timeframe] = pd.DataFrame()
    return frames


def _evaluate_from_entry(
    signal, future, finer_future=None, next_finer_future=None, finer_chain=None
):
    entry = float(signal["entry_raw"])
    tp = float(signal["tp_raw"])
    sl = float(signal["sl_raw"])
    direction = signal["direction"]

    if finer_chain is None:
        finer_chain = []
        if next_finer_future is not None:
            finer_chain.append(next_finer_future)

    for index, row in future.iterrows():
        high = float(row["High"])
        low = float(row["Low"])
        if direction == "LONG":
            tp_hit, sl_hit = high >= tp, low <= sl
        else:
            tp_hit, sl_hit = low <= tp, high >= sl
        if tp_hit and sl_hit:
            if finer_future is None or finer_future.empty:
                return _data_unavailable()
            finer_rows = finer_future.loc[
                (finer_future.index >= index)
                & (finer_future.index < index + TIMEFRAME_DURATION[signal["timeframe"]])
            ]
            if finer_rows.empty:
                return _data_unavailable()
            finer_signal = dict(signal)
            current_index = TIMEFRAME_ORDER.index(signal["timeframe"])
            finer_timeframe = signal.get(
                "finer_timeframe", TIMEFRAME_ORDER[current_index - 1]
            )
            finer_signal["timeframe"] = finer_timeframe
            if current_index > 1:
                finer_signal["finer_timeframe"] = TIMEFRAME_ORDER[current_index - 2]
            return _evaluate_from_entry(
                finer_signal,
                finer_rows,
                finer_chain[0] if finer_chain else None,
                finer_chain=finer_chain[1:],
            )
        if tp_hit:
            return {"status": "WIN", "exit_timestamp": index, "pnl_eur": 20.0}
        if sl_hit:
            return {"status": "LOSS", "exit_timestamp": index, "pnl_eur": -20.0}
    return {"status": "OPEN", "exit_timestamp": None, "pnl_eur": 0.0}


def evaluate_signal(signal, df=None, period="3mo"):
    if df is None:
        df = download_daily(signal["symbol"], period=period)
    if df is None or df.empty:
        return {"status": "DATA_UNAVAILABLE", "pnl_eur": 0.0, "timestamp": None}

    df = _normalise_index(df)

    if "timestamp" in signal and signal["timestamp"] is not None:
        signal_ts = _utc_timestamp(signal["timestamp"])
    else:
        signal_ts = _utc_timestamp(df.index.min())

    entry = float(signal["entry"])
    tp = float(signal["tp"])
    sl = float(signal["sl"])
    direction = signal["direction"]

    future = df.loc[df.index >= signal_ts].copy()
    if future.empty:
        return {"status": "DATA_UNAVAILABLE", "pnl_eur": 0.0, "timestamp": None}

    hit_entry = False
    entry_idx = None
    for idx, row in future.iterrows():
        hi = float(row["High"])
        lo = float(row["Low"])
        if lo <= entry <= hi:
            hit_entry = True
            entry_idx = idx
            break

    if not hit_entry:
        return {"status": "DATA_UNAVAILABLE", "pnl_eur": 0.0, "timestamp": None}

    entry_idx = _utc_timestamp(entry_idx)
    after_entry = future.loc[future.index >= entry_idx].copy()
    for idx, row in after_entry.iterrows():
        hi = float(row["High"])
        lo = float(row["Low"])
        if direction == "LONG":
            tp_hit = hi >= tp
            sl_hit = lo <= sl
        else:
            tp_hit = lo <= tp
            sl_hit = hi >= sl

        if tp_hit and sl_hit:
            return {"status": "DATA_UNAVAILABLE", "timestamp": idx, "pnl_eur": 0.0}
        if tp_hit:
            return {"status": "WIN", "timestamp": idx, "pnl_eur": 20.0}
        if sl_hit:
            return {"status": "LOSS", "timestamp": idx, "pnl_eur": -20.0}

    return {"status": "OPEN", "pnl_eur": 0.0, "timestamp": entry_idx}


def _empty_summary(message=""):
    return {
        "total_trades": 0,
        "WIN": 0,
        "LOSS": 0,
        "OPEN": 0,
        "net_pnl": 0.0,
        "win_rate": 0.0,
        "max_drawdown": 0.0,
        "results": [],
        "message": message,
    }


def _summary(results, message=""):
    normalized_results = [_normalise_result(result) for result in results]
    results = [
        result
        for result in normalized_results
        if result["status"] in {"WIN", "LOSS", "OPEN"}
    ]

    total = len(results)
    wins = sum(1 for r in results if r["status"] == "WIN")
    losses = sum(1 for r in results if r["status"] == "LOSS")
    open_trades = sum(1 for r in results if r["status"] == "OPEN")
    net_pnl = sum(float(r["pnl_eur"]) for r in results)
    win_rate = (wins / max(1, wins + losses)) * 100 if (wins + losses) else 0.0

    cumulative = []
    running = 0.0
    for r in results:
        running += float(r["pnl_eur"])
        cumulative.append(running)
    max_drawdown = 0.0
    peak = 0.0
    for value in cumulative:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)

    return {
        "total_trades": total,
        "WIN": wins,
        "LOSS": losses,
        "OPEN": open_trades,
        "net_pnl": net_pnl,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "results": results,
        "message": message,
    }


def _checked_signal_outcome(signal):
    symbol = signal["symbol"]
    signal_timestamp = _utc_timestamp(signal["timestamp"])
    fx_rate = signal.get("fx_rate")
    if fx_rate is None or float(fx_rate) <= 0:
        return _data_unavailable()
    now = pd.Timestamp.now(tz="UTC")
    entry = float(signal["entry"]) * float(fx_rate)
    tp = float(signal["tp"]) * float(fx_rate)
    sl = float(signal["sl"]) * float(fx_rate)
    checked_signal = {
        "entry_raw": entry,
        "tp_raw": tp,
        "sl_raw": sl,
        "direction": signal["direction"],
    }
    frames = _historical_frames(symbol, signal_timestamp, now)
    for index, timeframe in enumerate(TIMEFRAME_ORDER):
        frame = frames[timeframe]
        future = frame.loc[frame.index > signal_timestamp].copy()
        if future.empty:
            continue
        checked_signal["timeframe"] = timeframe
        if index > 0:
            finer_timeframe = TIMEFRAME_ORDER[index - 1]
            checked_signal["finer_timeframe"] = finer_timeframe
            finer_future = frames[finer_timeframe].loc[
                frames[finer_timeframe].index > signal_timestamp
            ]
            next_finer_timeframe = (
                TIMEFRAME_ORDER[index - 2] if index > 1 else None
            )
            next_finer_future = (
                frames[next_finer_timeframe].loc[
                    frames[next_finer_timeframe].index > signal_timestamp
                ]
                if next_finer_timeframe
                else None
            )
        else:
            finer_future = None
            next_finer_future = None
        finer_chain = [
            frames[lower_timeframe].loc[
                frames[lower_timeframe].index > signal_timestamp
            ]
            for lower_timeframe in reversed(TIMEFRAME_ORDER[:index - 2])
        ]
        return _evaluate_from_entry(
            checked_signal,
            future,
            finer_future,
            next_finer_future,
            finer_chain,
        )
    return _data_unavailable()


def run_checked_backtest(signals):
    results = []
    for signal in signals or []:
        try:
            outcome = _checked_signal_outcome(signal)
        except Exception:
            outcome = _data_unavailable()
        outcome.update({
            "symbol": signal.get("symbol", ""),
            "direction": signal.get("direction", ""),
            "entry": signal.get("entry", 0.0),
            "tp": signal.get("tp", 0.0),
            "sl": signal.get("sl", 0.0),
            "score": signal.get("score", 0),
            "setup": signal.get("setup", ""),
            "timestamp": _utc_timestamp(signal["timestamp"]),
            "entry_status": "FILLED",
        })
        results.append(_normalise_result(outcome))
    return _summary(results, "Backtest used the exact timestamp recorded by CHECK without hindsight.")


def run_historical_backtest(days, watchlist=WATCHLIST):
    """Replay the V3 engine using only candles known at each 15m timestamp.

    Yahoo Finance only retains a limited amount of 15m history. The replay
    and uses the next available timeframe for outcome evaluation.
    """
    if days not in PERIOD_DAYS:
        raise ValueError(f"days must be one of {PERIOD_DAYS}")

    now = _utc_timestamp(pd.Timestamp.utcnow())
    start = now - pd.Timedelta(days=days)
    data_by_symbol = {}
    unavailable = []
    for symbol in watchlist:
        frames = {}
        for timeframe, period in (
            ("15m", "60d"),
            ("1h", "730d"),
            ("4h", "5y"),
            ("1d", "10y"),
        ):
            if days * pd.Timedelta(days=1) > PROVIDER_WINDOWS[timeframe]:
                frames[timeframe] = pd.DataFrame()
            else:
                frames[timeframe] = _download_historical_cached(
                    symbol, timeframe, period
                )
        if all(frame.empty for frame in frames.values()):
            unavailable.append(symbol)
            continue
        data_by_symbol[symbol] = frames

    available_start = min(
        (
            next(
                (
                    frames[timeframe].index.min()
                    for timeframe in TIMEFRAME_ORDER
                    if not frames[timeframe].empty
                ),
                None,
            )
            for frames in data_by_symbol.values()
        ),
        default=None,
    )
    if available_start is None:
        return _empty_summary("Yahoo Finance returned no 15m history for this watchlist.")
    if start < available_start:
        message = (
            f"Yahoo Finance 15m history starts at {available_start.date()}; "
            f"the requested {days}-day window begins earlier. Only available "
            "15m history was replayed. Missing historical intraday data was not invented."
        )
    else:
        message = "Historical replay used Yahoo Finance 15m candles for entry timing; coverage may vary by ticker."

    results = []
    for symbol, frames in data_by_symbol.items():
        entry_timeframe = next(
            timeframe for timeframe in TIMEFRAME_ORDER if not frames[timeframe].empty
        )
        entry_frame = frames[entry_timeframe]
        replay_start = max(start, available_start)
        timestamps = pd.DatetimeIndex(
            entry_frame.index[
                (entry_frame.index >= replay_start) & (entry_frame.index <= now)
            ]
        )
        last_signal = {}
        for signal_timestamp in timestamps:
            signal_timestamp = _utc_timestamp(signal_timestamp)
            context = {
                timeframe: _rows_at_or_before(frame, signal_timestamp)
                for timeframe, frame in frames.items()
            }
            historical_quote = {
                "verified": True,
                "status": "HISTORICAL",
                "price": float(context[entry_timeframe].iloc[-1]["Close"]),
                "currency": _currency_for_symbol(symbol),
                "exchange": "Yahoo historical candle",
                "timestamp": signal_timestamp,
                "source": f"Yahoo Finance historical {entry_timeframe}",
            }
            signal = make_signal(symbol, context, market_quote=historical_quote)
            if signal is None:
                continue
            key = (symbol, signal["direction"])
            if key in last_signal and signal_timestamp <= last_signal[key]:
                continue

            raw_price = float(context[entry_timeframe].iloc[-1]["Close"])
            raw_tp = raw_price * (1 + 20 / 1500) if signal["direction"] == "LONG" else raw_price * (1 - 20 / 1500)
            raw_sl = raw_price * (1 - 20 / 1500) if signal["direction"] == "LONG" else raw_price * (1 + 20 / 1500)
            historical_signal = dict(signal)
            historical_signal.update({
                "timestamp": signal_timestamp,
                "entry_raw": raw_price,
                "tp_raw": raw_tp,
                "sl_raw": raw_sl,
            })
            outcome = _data_unavailable()
            for index, timeframe in enumerate(TIMEFRAME_ORDER):
                candidate = frames[timeframe]
                candidate_future = candidate.loc[candidate.index > signal_timestamp]
                if candidate_future.empty:
                    continue
                historical_signal["timeframe"] = timeframe
                if index > 0:
                    finer_timeframe = TIMEFRAME_ORDER[index - 1]
                    historical_signal["finer_timeframe"] = finer_timeframe
                    finer_future = frames[finer_timeframe].loc[
                        frames[finer_timeframe].index > signal_timestamp
                    ]
                    next_finer_future = (
                        frames["15m"].loc[frames["15m"].index > signal_timestamp]
                        if timeframe == "1d"
                        else None
                    )
                else:
                    finer_future = None
                    next_finer_future = None
                outcome = _evaluate_from_entry(
                    historical_signal,
                    candidate_future,
                    finer_future,
                    next_finer_future,
                )
                break
            outcome.update({
                "symbol": symbol,
                "direction": signal["direction"],
                "entry": signal["entry"],
                "tp": signal["tp"],
                "sl": signal["sl"],
                "score": signal["score"],
                "setup": signal["setup"],
                "timestamp": signal_timestamp,
            })
            results.append(_normalise_result(outcome))
            last_signal[key] = outcome["exit_timestamp"] or signal_timestamp

    if unavailable:
        message += f" No 15m data was available for {len(unavailable)} ticker(s)."
    return _summary(results, message)


def run_backtest(days=30, watchlist=WATCHLIST, signals=None):
    """Public backtest API used by the Streamlit application."""
    if signals is not None:
        return run_checked_backtest(signals)
    return run_historical_backtest(days=days, watchlist=watchlist)
