import pandas as pd
import streamlit as st

from backtest import run_backtest
from config import WATCHLIST
from history_store import (
    HistoryStoreConfigurationError,
    initialize_history_store,
    load_signals,
    save_signals,
)
from scanner import dedupe_signals, scan_watchlist

st.set_page_config(page_title="Global Stock Signal Bot V3", page_icon="📈", layout="wide")
initialize_history_store()


def _load_persistent_signals():
    try:
        return load_signals()
    except HistoryStoreConfigurationError as exc:
        st.error(str(exc))
        return []


def _format_fx_rate(value):
    if value is None or pd.isna(value):
        return "UNAVAILABLE"
    return f"{float(value):.6f}"


def _ensure_signal_columns(frame):
    defaults = {
        "market_price": None,
        "market_currency": "UNKNOWN",
        "market_exchange": "UNKNOWN EXCHANGE",
        "market_timestamp": None,
        "market_source": "Unknown",
        "signal_price": None,
        "signal_currency": "UNKNOWN",
        "price_status": "PRICE UNVERIFIED",
        "fx_status": "UNKNOWN",
        "fx_source": "Unknown",
    }
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = default
    return frame


def _build_backtest_dataframe(results):
    frame = pd.DataFrame(results)
    columns = [
        "signal_id", "timestamp", "ticker", "direction", "EUR Entry",
        "EUR TP", "EUR SL", "result", "P&L",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    if set(columns).issubset(frame.columns):
        return frame[columns].copy()
    source = frame["status"] if "status" in frame else frame["result"]
    frame["result"] = source.where(source.isin(["WIN", "LOSS", "OPEN"]), "OPEN")
    frame["signal_id"] = frame.get("signal_id", "")
    frame["timestamp"] = frame["timestamp"].map(str)
    frame["ticker"] = frame["symbol"]
    frame["EUR Entry"] = frame["entry"].map(lambda x: f"€{float(x):.2f}")
    frame["EUR TP"] = frame["tp"].map(lambda x: f"€{float(x):.2f}")
    frame["EUR SL"] = frame["sl"].map(lambda x: f"€{float(x):.2f}")
    pnl = frame["result"].map({"WIN": 20.0, "LOSS": -20.0, "OPEN": 0.0})
    frame["P&L"] = pnl.map(lambda x: f"€{x:.2f}")
    return frame[columns].copy()


st.title("🌍 Global Stock Signal Bot V3")
st.caption("50 global stocks • LONG / SHORT • €500 ×3 • TP/SL ±€20 • EUR display")
st.caption("Yahoo Finance data only — not Trade Republic / LS Exchange prices. FX status is shown when available.")

if "results" not in st.session_state:
    st.session_state["results"] = []
st.session_state["history"] = _load_persistent_signals()
if "active" not in st.session_state:
    st.session_state["active"] = [
        signal for signal in st.session_state["history"]
        if signal.get("status", "OPEN") == "OPEN"
    ]
else:
    st.session_state["active"] = [
        signal for signal in st.session_state["history"]
        if signal.get("status", "OPEN") == "OPEN"
    ]

c1, c2, c3 = st.columns(3)
c1.metric("Watchlist", "50")
c2.metric("Stake", "€500")
c3.metric("Leverage", "×3")

check_tab, active_tab, backtest_tab, history_tab, watchlist_tab = st.tabs([
    "CHECK",
    "ACTIVE SIGNALS",
    "BACKTEST",
    "HISTORY",
    "WATCHLIST",
])

with check_tab:
    if st.button("🔎 CHECK 50 MÃ", type="primary", use_container_width=True):
        progress = st.progress(0, text="Starting parallel scan: 0/50")

        def update_scan_progress(completed, total, symbol, status):
            progress.progress(completed / total, text=f"Scanning {completed}/{total}: {symbol} ({status})")

        with st.spinner("Scanning 50 tickers in parallel with per-ticker timeouts..."):
            fresh_results = scan_watchlist(WATCHLIST, progress_callback=update_scan_progress)
            st.session_state["price_rejections"] = scan_watchlist.last_rejections
            try:
                stored_results = save_signals(fresh_results)
                st.session_state["history"] = _load_persistent_signals()
            except HistoryStoreConfigurationError as exc:
                st.error(str(exc))
                stored_results = []
            results = dedupe_signals(stored_results)
        progress.progress(1.0, text=f"Scan complete: {len(results)} signals from {len(WATCHLIST)} tickers")
        st.session_state["results"] = results
        st.session_state["active"] = [
            signal for signal in st.session_state["history"]
            if signal.get("status", "OPEN") == "OPEN"
        ]
        st.session_state["checked_at"] = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if st.session_state["results"]:
        table = _ensure_signal_columns(pd.DataFrame(st.session_state["results"]))
        table = table[["symbol", "direction", "entry", "tp", "sl", "score", "setup", "timestamp", "fx_rate", "fx_pair", "fx_timestamp"]].copy()
        table["entry"] = table["entry"].map(lambda x: float(x))
        table["tp"] = table["tp"].map(lambda x: float(x))
        table["sl"] = table["sl"].map(lambda x: float(x))
        table["Ticker"] = table["symbol"]
        table["Direction"] = table["direction"]
        table["EUR Entry"] = table["entry"].map(lambda x: f"€{x:.2f}")
        table["EUR TP"] = table["tp"].map(lambda x: f"€{x:.2f}")
        table["EUR SL"] = table["sl"].map(lambda x: f"€{x:.2f}")
        table["Score"] = table["score"]
        table["Setup"] = table["setup"]
        table["Timestamp"] = table["timestamp"].map(lambda x: str(x))
        table["FX Rate"] = table["fx_rate"].map(_format_fx_rate)
        table["FX Pair"] = table["fx_pair"]
        table["FX Timestamp"] = table["fx_timestamp"].map(lambda x: str(x))
        source_table = _ensure_signal_columns(pd.DataFrame(st.session_state["results"]))
        table["FX Status"] = source_table["fx_status"]
        table["FX Source"] = source_table["fx_source"]
        table["Market Price"] = source_table["market_price"].map(lambda x: "UNAVAILABLE" if x is None else f"{float(x):.6f}")
        table["Signal Price"] = source_table["signal_price"].map(lambda x: "UNAVAILABLE" if x is None else f"{float(x):.6f}")
        table["Currency"] = source_table["market_currency"]
        table["Exchange"] = source_table["market_exchange"]
        table["Price Status"] = source_table["price_status"]
        table["Market Source"] = source_table["market_source"]
        table["Market Timestamp"] = source_table["market_timestamp"].map(str)
        st.dataframe(table[["Ticker", "Direction", "Market Price", "Signal Price", "Currency", "Exchange", "Price Status", "Market Source", "Market Timestamp", "EUR Entry", "EUR TP", "EUR SL", "Score", "Setup", "Timestamp", "FX Rate", "FX Status", "FX Pair", "FX Source", "FX Timestamp"]], use_container_width=True, hide_index=True)
    else:
        st.info("No valid signal was generated. The engine did not force a setup.")
        rejected = st.session_state.get("price_rejections", [])
        if rejected:
            st.warning(
                f"PRICE UNVERIFIED: {len(rejected)} ticker(s) were not made tradable because their latest market quote was unavailable or stale."
            )

    st.subheader("Market context / news")
    st.info("No reliable live macro/news feed is connected in this app. Major rate decisions, CPI, NFP, earnings, and company news are not being fabricated or inferred. Yahoo Finance data — not Trade Republic / LS Exchange live pricing.")

    st.caption(f"Last check: {st.session_state.get('checked_at', '')}")

with active_tab:
    if not st.session_state["active"]:
        st.info("No active signals yet.")
    else:
        active_df = _ensure_signal_columns(pd.DataFrame(st.session_state["active"]))
        active_df = active_df[["symbol", "direction", "entry", "tp", "sl", "score", "setup", "timestamp", "fx_rate", "fx_pair", "fx_timestamp"]].copy()
        active_df["Ticker"] = active_df["symbol"]
        active_df["Direction"] = active_df["direction"]
        active_df["EUR Entry"] = active_df["entry"].map(lambda x: f"€{float(x):.2f}")
        active_df["EUR TP"] = active_df["tp"].map(lambda x: f"€{float(x):.2f}")
        active_df["EUR SL"] = active_df["sl"].map(lambda x: f"€{float(x):.2f}")
        active_df["Score"] = active_df["score"]
        active_df["Setup"] = active_df["setup"]
        active_df["Timestamp"] = active_df["timestamp"].map(lambda x: str(x))
        active_df["FX Rate"] = active_df["fx_rate"].map(_format_fx_rate)
        active_df["FX Pair"] = active_df["fx_pair"]
        active_df["FX Timestamp"] = active_df["fx_timestamp"].map(lambda x: str(x))
        active_source = _ensure_signal_columns(pd.DataFrame(st.session_state["active"]))
        active_df["FX Status"] = active_source["fx_status"]
        active_df["FX Source"] = active_source["fx_source"]
        active_df["Market Price"] = active_source["market_price"].map(lambda x: "UNAVAILABLE" if x is None else f"{float(x):.6f}")
        active_df["Signal Price"] = active_source["signal_price"].map(lambda x: "UNAVAILABLE" if x is None else f"{float(x):.6f}")
        active_df["Currency"] = active_source["market_currency"]
        active_df["Exchange"] = active_source["market_exchange"]
        active_df["Price Status"] = active_source["price_status"]
        active_df["Market Source"] = active_source["market_source"]
        active_df["Market Timestamp"] = active_source["market_timestamp"].map(str)
        st.dataframe(active_df[["Ticker", "Direction", "Market Price", "Signal Price", "Currency", "Exchange", "Price Status", "Market Source", "Market Timestamp", "EUR Entry", "EUR TP", "EUR SL", "Score", "Setup", "Timestamp", "FX Rate", "FX Status", "FX Pair", "FX Source", "FX Timestamp"]], use_container_width=True, hide_index=True)

with backtest_tab:
    st.caption("Historical replay uses only Yahoo Finance candles available at each historical timestamp. Yahoo Finance does not provide unlimited 15m history; unavailable periods/tickers are reported rather than fabricated.")
    selected_days = st.selectbox("Historical period", (30, 90, 180, 365), format_func=lambda value: f"{value} days")
    if st.button("Run historical backtest", type="primary", use_container_width=True):
        with st.spinner(f"Replaying {selected_days} days across the fixed 50-stock watchlist..."):
            checked_signals = _load_persistent_signals()
            st.session_state["backtest"] = run_backtest(
                selected_days,
                WATCHLIST,
                signals=checked_signals,
            )

    bt = st.session_state.get("backtest")
    if bt is None:
        st.info("Choose a period and run the historical backtest. CHECK is not required.")
    else:
        if bt.get("message"):
            st.warning(bt["message"])
        bt_df = _build_backtest_dataframe(bt["results"])
        results = bt_df["result"] if not bt_df.empty else pd.Series(dtype=str)
        wins = int((results == "WIN").sum())
        losses = int((results == "LOSS").sum())
        open_trades = int((results == "OPEN").sum())
        win_rate = (wins / (wins + losses)) * 100 if wins + losses else 0.0
        pnl_values = results.map({"WIN": 20.0, "LOSS": -20.0, "OPEN": 0.0})
        net_pnl = float(pnl_values.sum())
        cumulative = pnl_values.cumsum()
        max_drawdown = float((cumulative.cummax() - cumulative).max()) if not cumulative.empty else 0.0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total trades", len(bt_df))
        c2.metric("WIN", wins)
        c3.metric("LOSS", losses)
        c4.metric("OPEN", open_trades)

        c6, c7, c8 = st.columns(3)
        c6.metric("Net P&L", f"€{net_pnl:.2f}")
        c7.metric("Win rate", f"{win_rate:.1f}%")
        c8.metric("Max drawdown", f"€{max_drawdown:.2f}")

        if bt_df.empty:
            st.info("No historical V3 setups were found in the available data window.")
        else:
            st.dataframe(bt_df[["signal_id", "timestamp", "ticker", "direction", "EUR Entry", "EUR TP", "EUR SL", "result", "P&L"]], use_container_width=True, hide_index=True)

with history_tab:
    st.session_state["history"] = _load_persistent_signals()
    if not st.session_state["history"]:
        st.info("No historical signal scans yet.")
    else:
        hist_df = pd.DataFrame(st.session_state["history"])
        hist_df["Ticker"] = hist_df["symbol"]
        hist_df["Direction"] = hist_df["direction"]
        hist_df["EUR Entry"] = hist_df["entry"].map(lambda x: f"€{float(x):.2f}")
        hist_df["EUR TP"] = hist_df["tp"].map(lambda x: f"€{float(x):.2f}")
        hist_df["EUR SL"] = hist_df["sl"].map(lambda x: f"€{float(x):.2f}")
        hist_df["Timestamp"] = hist_df["timestamp"].map(str)
        st.dataframe(hist_df[["signal_id", "Timestamp", "Ticker", "Direction", "EUR Entry", "EUR TP", "EUR SL", "market_source", "market_timestamp", "fx_source", "fx_timestamp"]], use_container_width=True, hide_index=True)

with watchlist_tab:
    st.write(", ".join(WATCHLIST))
    st.caption("Yahoo Finance data — not Trade Republic / LS Exchange live pricing.")

    if st.button("Refresh check", type="secondary"):
        with st.spinner("Refreshing scanner..."):
            st.session_state["results"] = dedupe_signals(scan_watchlist(WATCHLIST), st.session_state.get("active", []))
            st.session_state["price_rejections"] = scan_watchlist.last_rejections
            st.session_state["active"] = st.session_state["results"]

    if st.session_state.get("results"):
        st.subheader("Current watchlist summary")
        st.write(f"Signals: {len(st.session_state['results'])}")
