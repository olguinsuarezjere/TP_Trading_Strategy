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


def compute_crash_filter(
    returns: pd.DataFrame,
    bear_lookback: int = 12,
    vol_short_window: int = 3,
    vol_long_window: int = 36,
    vol_long_min_periods: int = 12,
    vol_threshold: float = 1.2,
    crash_scale: float = 0.5,
) -> pd.Series:
    """
    Daniel & Moskowitz (2016): crash regime filter.

    Crash regime = SPY 12m return < 0 (bear) AND recent vol > 1.2x long-run vol.
    En crash: multiplier = 0.5. Normal: multiplier = 1.0.
    Todas las condiciones usan .shift(1) — sin look-ahead bias.
    """
    if "SPY" not in returns.columns:
        return pd.Series(1.0, index=returns.index)

    spy = returns["SPY"]

    bear_signal = spy.rolling(bear_lookback).sum().shift(1) < 0

    vol_short = spy.rolling(vol_short_window).std().shift(1)
    vol_long  = spy.rolling(vol_long_window, min_periods=vol_long_min_periods).std().shift(1)
    high_vol_signal = vol_short > vol_long.replace(0, np.nan) * vol_threshold

    crash_regime = (bear_signal & high_vol_signal).fillna(False)
    return crash_regime.map({True: crash_scale, False: 1.0})


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


def compute_multihorizon_signal(
    returns: pd.DataFrame,
    lookbacks: tuple[int, ...] = (3, 6, 12),
) -> pd.DataFrame:
    """
    Señal de momentum multi-horizonte (Moskowitz et al. 2012; práctica estándar AQR).

    Promedia la señal continua normalizada por volatilidad (Baz et al. 2015) sobre
    varios lookbacks. Captar tendencias de corto, medio y largo plazo a la vez reduce
    el ruido de un único horizonte y suaviza el turnover, mejorando el Sharpe.
    """
    parts = [compute_signal_strength(returns, lookback=lb) for lb in lookbacks]
    return sum(parts) / len(parts)
