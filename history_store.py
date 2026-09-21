import hashlib
import json
from datetime import datetime, timezone

import streamlit as st


SIGNALS_TABLE = "signals"
REQUIRED_SIGNAL_FIELDS = (
    "signal_id", "ticker", "side", "timestamp", "entry", "tp", "sl",
    "status", "pnl", "source", "created_at", "closed_at",
)
_CLIENT_OVERRIDE = None


class HistoryStoreConfigurationError(RuntimeError):
    """Raised when the persistent Supabase history store is not configured."""


def _client():
    if _CLIENT_OVERRIDE is not None:
        return _CLIENT_OVERRIDE
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception as exc:
        raise HistoryStoreConfigurationError(
            "Persistent signal history is not configured. Add SUPABASE_URL "
            "and SUPABASE_KEY to Streamlit Secrets."
        ) from exc
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError as exc:
        raise HistoryStoreConfigurationError(
            "The supabase package is required for persistent signal history."
        ) from exc


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _set_client_for_testing(client):
    global _CLIENT_OVERRIDE
    _CLIENT_OVERRIDE = client


def _signal_id(signal):
    identity = {
        "symbol": signal.get("symbol"),
        "direction": signal.get("direction"),
        "timestamp": str(signal.get("timestamp")),
        "entry": signal.get("entry"),
        "tp": signal.get("tp"),
        "sl": signal.get("sl"),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def initialize_history_store():
    """Validate that the persistent backend can be configured."""
    try:
        return _client()
    except HistoryStoreConfigurationError:
        return None


def _to_signal_record(row):
    record = dict(row)
    record.update({
        "symbol": record.get("ticker", ""),
        "direction": record.get("side", ""),
        "timestamp": record.get("timestamp"),
        "result": record.get("status", "OPEN"),
        "status": record.get("status", "OPEN"),
        "pnl_eur": float(record.get("pnl", 0.0) or 0.0),
        "source": record.get("source", "V3 CHECK"),
        "fx_rate": 1.0,
    })
    return record


def save_signals(signals):
    client = _client()
    stored = []
    for signal in signals or []:
        record = dict(signal)
        signal_id = record.setdefault("signal_id", _signal_id(record))
        ticker = record["symbol"]
        side = record["direction"]
        duplicate = client.table(SIGNALS_TABLE).select("signal_id").eq(
            "ticker", ticker
        ).eq("side", side).eq("entry", float(record["entry"])).eq(
            "tp", float(record["tp"])
        ).eq("sl", float(record["sl"])).eq("status", "OPEN").execute()
        if duplicate.data:
            stored.append(_to_signal_record({**record, "signal_id": duplicate.data[0]["signal_id"]}))
            continue
        row = {
            "signal_id": signal_id,
            "ticker": ticker,
            "side": side,
            "timestamp": str(record["timestamp"]),
            "entry": float(record["entry"]),
            "tp": float(record["tp"]),
            "sl": float(record["sl"]),
            "status": "OPEN",
            "pnl": 0.0,
            "source": "V3 CHECK",
            "created_at": _now_iso(),
            "closed_at": None,
        }
        client.table(SIGNALS_TABLE).insert(row).execute()
        stored.append(_to_signal_record(row))
    return stored


def load_signals():
    response = _client().table(SIGNALS_TABLE).select("*").order(
        "timestamp", desc=False
    ).execute()
    return [_to_signal_record(row) for row in (response.data or [])]


def update_signal_result(signal_id, status, pnl):
    if status not in {"OPEN", "WIN", "LOSS"}:
        raise ValueError(f"Unsupported signal status: {status}")
    values = {"status": status, "pnl": float(pnl)}
    if status in {"WIN", "LOSS"}:
        values["closed_at"] = _now_iso()
    _client().table(SIGNALS_TABLE).update(values).eq(
        "signal_id", signal_id
    ).execute()


def count_signals():
    response = _client().table(SIGNALS_TABLE).select("signal_id", count="exact").execute()
    return int(response.count or 0)
