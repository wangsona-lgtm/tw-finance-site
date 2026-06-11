import pandas as pd

def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    EMA 10/30 Crossover Strategy
    Input df has columns: Open, High, Low, Close, Volume
    Returns df with added column 'signal':
      1  = buy (EMA10 crosses above EMA30)
     -1  = sell / close long (EMA10 crosses below EMA30)
      0  = hold
    """
    # Calculate 10-day and 30-day Exponential Moving Averages
    df['ema10'] = df['Close'].ewm(span=10, adjust=False).mean()
    df['ema30'] = df['Close'].ewm(span=30, adjust=False).mean()

    # Generate signals based on EMA crossover
    df['signal'] = 0

    # EMA10 above EMA30 -> bullish (buy signal)
    df.loc[df['ema10'] > df['ema30'], 'signal'] = 1

    # EMA10 below EMA30 -> bearish (sell signal)
    df.loc[df['ema10'] < df['ema30'], 'signal'] = -1

    return df
