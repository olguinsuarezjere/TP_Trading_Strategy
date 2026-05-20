import pandas as pd
import numpy as np


def compute_vol_scaled_weights(
    signal: pd.DataFrame,
    vol: pd.DataFrame,
    target_vol: float = 0.10,
) -> pd.DataFrame:
    """
    Volatility-scaled position weights (Moskowitz et al. 2012).

    w_{i,t} = signal_{i,t} * (target_vol / vol_{i,t}) / N_active
    Each active asset contributes equally to portfolio risk.
    """
    active = signal.notna() & vol.notna() & (vol > 0)
    n_active = active.sum(axis=1).replace(0, np.nan)

    raw = signal * (target_vol / vol.replace(0, np.nan))
    weights = raw.div(n_active, axis=0)
    return weights.where(active, 0.0)


def apply_position_constraints(weights: pd.DataFrame, max_weight: float = 0.15) -> pd.DataFrame:
    """Clip each individual position to [-max_weight, max_weight]."""
    return weights.clip(-max_weight, max_weight)


def build_portfolio(
    returns: pd.DataFrame,
    config: dict,
    use_signal_strength: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Full portfolio construction pipeline.

    Returns (weights, signal) DataFrames aligned to returns index.
    """
    from .volatility import compute_ex_ante_vol
    from .signals import compute_tsmom_signal, compute_signal_strength

    vol = compute_ex_ante_vol(returns, com_months=config["strategy"]["vol_com_months"])

    if use_signal_strength:
        signal = compute_signal_strength(returns, lookback=config["strategy"]["lookback_months"])
    else:
        signal = compute_tsmom_signal(returns, lookback=config["strategy"]["lookback_months"])

    weights = compute_vol_scaled_weights(signal, vol, target_vol=config["strategy"]["target_volatility"])
    weights = apply_position_constraints(weights, max_weight=config["strategy"]["max_position_weight"])

    return weights, signal
