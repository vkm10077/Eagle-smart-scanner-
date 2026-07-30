"""Simple scanner and scoring engine.
This implements minimal rules described in the MVP: trend, momentum, breakout, RSI and liquidity placeholder.
Returns rows only if score >= threshold and signal in Buy/Strong Buy.
"""
import os
from typing import Dict, Any

import pandas as pd

from src.data.fetcher import fetch_ohlcv, fetch_quote
from src.indicators import add_basic_indicators

SCORE_THRESHOLD = int(os.environ.get('SCORE_THRESHOLD', 70))


def score_for_horizon(df: pd.DataFrame, horizon: str = 'swing') -> Dict[str, Any]:
    latest = df.iloc[-1]
    score = 0

    # Trend: 50 > 200
    if latest.get('sma50', 0) and latest.get('sma200', 0) and latest['sma50'] > latest['sma200']:
        score += 30

    # Momentum: MACD > signal
    if latest.get('macd') is not None and latest.get('macd_signal') is not None and latest['macd'] > latest['macd_signal']:
        score += 25

    # RSI comfortable range
    if 40 <= latest.get('rsi14', 0) <= 65:
        score += 15

    # Breakout: price > recent 20-day high
    recent_high = df['close'].rolling(20).max().iloc[-2] if len(df) > 20 else None
    if recent_high is not None and latest['close'] > recent_high:
        score += 20

    # Liquidity placeholder (to be filled with ADTV checks)
    # For now, give small liquidity score by default
    score += 10

    signal = None
    if score >= SCORE_THRESHOLD:
        signal = 'Strong Buy' if score >= 85 else 'Buy'

    # Entry, SL, Target simple rules
    atr = latest.get('atr14', 0) or 0
    entry = float(latest['close'])
    sl = entry - (atr * 1.5) if atr else entry * 0.97
    target = entry + (atr * 3) if atr else entry * 1.05

    return {
        'score': int(min(score, 100)),
        'signal': signal,
        'entry': round(entry, 2),
        'sl': round(sl, 2),
        'target': round(target, 2),
    }


def scan_ticker(ticker: str, provider: str = None, horizon: str = 'swing') -> Dict[str, Any]:
    try:
        df = fetch_ohlcv(ticker, provider=provider)
        if df is None or len(df) < 50:
            return {'ticker': ticker, 'error': 'insufficient data'}
        # Normalize column names to lower-case expected in indicators
        df = df.rename(columns={c: c.lower() for c in df.columns})
        df = add_basic_indicators(df)
        s = score_for_horizon(df, horizon=horizon)
        quote = fetch_quote(ticker, provider=provider)
        out = {
            'ticker': ticker,
            'name': ticker,
            'sector': None,
            'sector_strength': None,
            'current_price': float(df['close'].iloc[-1]),
            'data_timestamp': str(df.index[-1]),
            **s
        }
        return out
    except Exception as e:
        return {'ticker': ticker, 'error': str(e)}
