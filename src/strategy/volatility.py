import pandas as pd
import numpy as np


def compute_ex_ante_vol(returns: pd.DataFrame, com_months: float = 3.0) -> pd.DataFrame:
    """
    EWMA estimate of annualized volatility (Moskowitz et al. 2012, Eq. 1).

    Uses center-of-mass = 3 months ≈ 60 trading days (daily paper equivalent).
    .shift(1) ensures vol[t] is computed from data through t-1 (no look-ahead).
    """
    ewma_var = (returns ** 2).ewm(com=com_months, min_periods=1).mean().shift(1)
    return np.sqrt(ewma_var * 12)  # annualize monthly variance
