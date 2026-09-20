import hashlib
import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).with_name("signals.sqlite3")


def _connection():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
    with _connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                check_timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                tp REAL NOT NULL,
                sl REAL NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )


def save_signals(signals):
    initialize_history_store()
    stored = []
    with _connection() as connection:
        for signal in signals or []:
            record = dict(signal)
            signal_id = record.setdefault("signal_id", _signal_id(record))
            record.setdefault("check_timestamp", record.get("timestamp"))
            connection.execute(
                """
                INSERT OR IGNORE INTO signals
                (signal_id, check_timestamp, symbol, direction, entry, tp, sl, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    str(record.get("check_timestamp")),
                    record["symbol"],
                    record["direction"],
                    float(record["entry"]),
                    float(record["tp"]),
                    float(record["sl"]),
                    json.dumps(record, default=str),
                ),
            )
            stored.append(record)
    return stored


def load_signals():
    initialize_history_store()
    with _connection() as connection:
        rows = connection.execute(
            "SELECT payload FROM signals ORDER BY check_timestamp ASC, signal_id ASC"
        ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def count_signals():
    initialize_history_store()
    with _connection() as connection:
        return connection.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
