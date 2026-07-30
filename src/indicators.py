"""Indicator helpers using pandas_ta (preferred) or simple pandas implementations."""
import pandas as pd

try:
    import pandas_ta as ta
except Exception:
    ta = None


def add_basic_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if ta is not None:
        df['sma20'] = ta.sma(df['close'], length=20)
        df['sma50'] = ta.sma(df['close'], length=50)
        df['sma100'] = ta.sma(df['close'], length=100)
        df['sma200'] = ta.sma(df['close'], length=200)
        df['rsi14'] = ta.rsi(df['close'], length=14)
        macd = ta.macd(df['close'])
        if 'MACD_12_26_9' in macd:
            df['macd'] = macd['MACD_12_26_9']
            df['macd_signal'] = macd['MACDs_12_26_9']
        df['atr14'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    else:
        # Fallback simple implementations
        df['sma50'] = df['close'].rolling(50).mean()
        df['sma200'] = df['close'].rolling(200).mean()
        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        roll_up = up.rolling(14).mean()
        roll_down = down.rolling(14).mean()
        rs = roll_up / roll_down
        df['rsi14'] = 100.0 - (100.0 / (1.0 + rs))
        df['atr14'] = df['high'].subtract(df['low']).rolling(14).mean()
    return df
