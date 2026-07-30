"""Simple data fetcher adapter supporting yfinance (fallback) and Fyers (REST).
This module intentionally keeps Fyers REST calls minimal and requires your API keys in env or secrets.

Note: Do NOT commit API keys. Put them in .env or set as GitHub secrets and load them into runtime.
"""
import os
import time
import logging
from typing import Optional, Dict

import pandas as pd
import requests

try:
    import yfinance as yf
except Exception:
    yf = None

LOG = logging.getLogger(__name__)

FYERS_BASE = "https://api.fyers.in"

def _get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


def fetch_ohlcv_yfinance(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    if yf is None:
        raise RuntimeError("yfinance is not installed")
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns={
        'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Adj Close': 'adj_close', 'Volume': 'volume'
    })
    return df


def _fyers_history(symbol: str, start: Optional[int] = None, end: Optional[int] = None, resolution: str = "D") -> pd.DataFrame:
    """Fetch historical OHLCV from Fyers REST history endpoint.
    This uses the documentated /history endpoint. You must provide FYERS_ACCESS_TOKEN env var.

    Note: Implementation here is minimal. If you prefer, use fyers python SDK and websocket for live ticks.
    """
    access_token = _get_env('FYERS_ACCESS_TOKEN')
    if not access_token:
        raise RuntimeError("FYERS_ACCESS_TOKEN not set in environment")

    headers = {"Authorization": f"Bearer {access_token}"}
    # Fyers history endpoint requires specific parameters; below is a generic example.
    # symbol must be in Fyers symbol format (e.g., NSE:SBIN- EQ)
    url = FYERS_BASE + "/api/v2/history"
    params = {
        "symbol": symbol,
        "resolution": resolution,  # D, 60, 5 etc
        # optionally from and to as epoch seconds
    }
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    # The exact response schema depends on Fyers; adjust parsing as needed.
    # If response contains o, h, l, c, v arrays, convert to DataFrame
    if 'candles' in data:
        candles = data['candles']
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        df = df.set_index('timestamp')
        return df
    raise RuntimeError(f"Unexpected Fyers response: {data}")


def fetch_ohlcv_fyers(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    # Map period/interval to Fyers resolution and date range if needed.
    # For simplicity, attempt a daily history call.
    # Convert period like '2y' to from/to epochs is left for future improvement.
    res = 'D'
    return _fyers_history(symbol, resolution=res)


def fetch_ohlcv(ticker: str, provider: Optional[str] = None, period: str = '2y', interval: str = '1d') -> pd.DataFrame:
    provider = provider or _get_env('DATA_PROVIDER', 'yfinance')
    if provider == 'fyers':
        try:
            return fetch_ohlcv_fyers(ticker, period=period, interval=interval)
        except Exception as e:
            LOG.warning("Fyers fetch failed (%s). Falling back to yfinance: %s", e, e)
            if yf is not None:
                return fetch_ohlcv_yfinance(ticker, period=period, interval=interval)
            raise
    else:
        return fetch_ohlcv_yfinance(ticker, period=period, interval=interval)


def fetch_quote(ticker: str, provider: Optional[str] = None) -> Dict:
    """Fetch latest quote (price + volume) for ticker.
    For fyers, use quotes endpoint. For yfinance, use history(period='1d').
    """
    provider = provider or _get_env('DATA_PROVIDER', 'yfinance')
    if provider == 'fyers':
        access_token = _get_env('FYERS_ACCESS_TOKEN')
        if not access_token:
            raise RuntimeError("FYERS_ACCESS_TOKEN not set")
        headers = {"Authorization": f"Bearer {access_token}"}
        url = FYERS_BASE + "/api/v2/quotes"
        params = {"symbols": ticker}
        r = requests.get(url, headers=headers, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        return data
    else:
        if yf is None:
            raise RuntimeError("yfinance not available for quote")
        df = yf.download(ticker, period='2d', interval='1d', progress=False)
        if df.empty:
            raise RuntimeError("No data from yfinance for %s" % ticker)
        last = df.iloc[-1]
        return {"price": float(last['Close']), "volume": int(last['Volume']), "timestamp": str(df.index[-1])}
