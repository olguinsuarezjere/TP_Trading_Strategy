import pandas as pd
import numpy as np


def compute_tsmom_signal(returns: pd.DataFrame, lookback: int = 12) -> pd.DataFrame:
    """
    Time Series Momentum signal (Moskowitz et al. 2012).

    s_{i,t} = sign(sum of returns from t-lookback to t-1).
    .rolling(lookback).sum() at t gives sum through t, .shift(1) shifts so
    at index t we use data only through t-1, enforcing no look-ahead bias.

    Returns +1 (long) or -1 (short); NaN where insufficient history.
    """
    cumulative = returns.rolling(lookback).sum().shift(1)
    return cumulative.apply(np.sign)


def compute_signal_strength(returns: pd.DataFrame, lookback: int = 12) -> pd.DataFrame:
    """
    Continuous trend signal normalized by volatility (Baz et al. 2015).

    Captures both direction and magnitude of recent trend, scaled to unit variance.
    """
    cumulative = returns.rolling(lookback).sum().shift(1)
    rolling_std = cumulative.rolling(lookback * 2, min_periods=lookback).std()
    normalized = cumulative / rolling_std.replace(0, np.nan)
    # Clip extreme values to [-3, 3] to avoid outsized positions
    return normalized.clip(-3, 3)
