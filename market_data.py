import math

import pandas as pd
import yfinance as yf

FX_CACHE = {}
FX_MAX_AGE = pd.Timedelta(days=3)
MARKET_MAX_AGE = pd.Timedelta(minutes=30)
MARKET_FALLBACK_MAX_AGE = pd.Timedelta(days=3)
YFINANCE_TIMEOUT_SECONDS = 10

__all__ = [
    "_currency_for_symbol",
    "convert_to_eur_price",
    "download_daily",
    "download_ohlc",
    "download_ohlcv",
    "get_fx_context",
    "get_market_quote",
]


def _get_fx_rate(pair: str):
    if pair in FX_CACHE:
        cached = FX_CACHE[pair]
    else:
        cached = None
    try:
        data = yf.download(
            pair,
            period="5d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
            timeout=YFINANCE_TIMEOUT_SECONDS,
        )
        if data is None or data.empty:
            raise ValueError("No FX data")
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        value = float(close.dropna().iloc[-1])
        if math.isnan(value) or value <= 0:
            raise ValueError("Invalid FX rate")
        source_timestamp = pd.Timestamp(data.index[-1])
        if source_timestamp.tzinfo is None:
            source_timestamp = source_timestamp.tz_localize("UTC")
        else:
            source_timestamp = source_timestamp.tz_convert("UTC")
        now = pd.Timestamp.now(tz="UTC")
        status = "CURRENT" if now - source_timestamp <= FX_MAX_AGE else "STALE"
        FX_CACHE[pair] = {
            "value": value,
            "timestamp": source_timestamp,
            "status": status,
            "source": "Yahoo Finance",
        }
        return FX_CACHE[pair]
    except Exception:
        if cached is not None:
            stale = dict(cached)
            stale["status"] = "STALE"
            return stale
        return {
            "value": None,
            "timestamp": None,
            "status": "UNAVAILABLE",
            "source": "Yahoo Finance",
        }


def _currency_for_symbol(symbol: str) -> str:
    s = symbol.upper()
    if any(s.endswith(suffix) for suffix in [".DE", ".PA", ".SW", ".AS", ".CO", ".BE", ".BR", ".AMS"]):
        return "EUR"
    if s.endswith(".KS"):
        return "KRW"
    if s.endswith(".TW"):
        return "TWD"
    if s.endswith(".T"):
        return "JPY"
    return "USD"


def _as_utc_timestamp(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _quote_from_frame(data, currency, exchange, source, max_age, fallback=False):
    if data is None or data.empty:
        return None
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        return None
    timestamp = _as_utc_timestamp(close.index[-1])
    price = float(close.iloc[-1])
    age = pd.Timestamp.now(tz="UTC") - timestamp
    if not math.isfinite(price) or price <= 0 or age > max_age:
        return None
    return {
        "verified": True,
        "status": "VERIFIED_FALLBACK" if fallback else "VERIFIED",
        "reason": "Latest available quote from fallback source." if fallback else "",
        "price": price,
        "currency": currency,
        "exchange": exchange,
        "timestamp": timestamp,
        "source": source,
    }


def get_market_quote(symbol: str):
    """Return the freshest real native-currency quote available for one symbol."""
    currency = _currency_for_symbol(symbol)
    exchange = "UNKNOWN EXCHANGE"
    last_reason = "No reliable quote was returned."
    try:
        ticker = yf.Ticker(symbol)
        fast_info = ticker.fast_info
        currency = fast_info.get("currency") or currency
        exchange = fast_info.get("exchange") or "UNKNOWN EXCHANGE"
        data = yf.download(
            symbol,
            period="1d",
            interval="1m",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=YFINANCE_TIMEOUT_SECONDS,
        )
        quote = _quote_from_frame(
            data, currency, exchange, "Yahoo Finance 1m", MARKET_MAX_AGE
        )
        if quote is not None:
            return quote
        last_reason = "Yahoo Finance 1m quote unavailable or outside freshness window."
    except Exception as exc:
        last_reason = str(exc)

    for interval, period, source in (
        ("5m", "5d", "Yahoo Finance 5m fallback"),
        ("15m", "60d", "Yahoo Finance 15m fallback"),
        ("1d", "5d", "Yahoo Finance daily fallback"),
    ):
        try:
            data = yf.download(
                symbol,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=YFINANCE_TIMEOUT_SECONDS,
            )
            quote = _quote_from_frame(
                data,
                currency,
                exchange,
                source,
                MARKET_FALLBACK_MAX_AGE,
                fallback=True,
            )
            if quote is not None:
                return quote
            last_reason = f"{source} unavailable or stale."
        except Exception as exc:
            last_reason = str(exc)

    return {
        "verified": False,
        "status": "PRICE UNVERIFIED",
        "reason": last_reason,
        "price": None,
        "currency": currency,
        "exchange": exchange,
        "timestamp": None,
        "source": "Yahoo Finance quote chain",
    }


def get_fx_context(symbol: str, currency: str | None = None):
    currency = currency or _currency_for_symbol(symbol)
    if currency == "EUR":
        return {
            "currency": "EUR",
            "pair": "EUR",
            "rate": 1.0,
            "timestamp": pd.Timestamp.now(tz="UTC"),
            "status": "CURRENT",
            "source": "Native EUR price",
        }
    pair_map = {
        "USD": "EURUSD=X",
        "JPY": "EURJPY=X",
        "KRW": "EURKRW=X",
        "TWD": "EURTWD=X",
        "CHF": "EURCHF=X",
    }
    pair = pair_map.get(currency, "EURUSD=X")
    fx = _get_fx_rate(pair)
    return {
        "currency": currency,
        "pair": pair,
        "rate": float(fx["value"]) if fx["value"] is not None else None,
        "timestamp": fx["timestamp"],
        "status": fx["status"],
        "source": fx["source"],
    }


def convert_to_eur_price(price: float, symbol: str, currency: str | None = None) -> float:
    if price is None or math.isnan(float(price)):
        return 0.0
    price = float(price)
    currency = currency or _currency_for_symbol(symbol)
    if currency == "EUR":
        return price
    rate = get_fx_context(symbol, currency)["rate"]
    return price / rate if rate else None


def download_ohlc(symbol: str, interval: str = "1d", period: str = "1y") -> pd.DataFrame:
    df = yf.download(
        symbol,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
        timeout=YFINANCE_TIMEOUT_SECONDS,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna().copy()
    return df


def download_ohlcv(symbol: str, interval: str = "1d", period: str = "1y") -> pd.DataFrame:
    return download_ohlc(symbol, interval=interval, period=period)


def download_daily(symbol: str, period: str = "1y") -> pd.DataFrame:
    return download_ohlc(symbol, interval="1d", period=period)
