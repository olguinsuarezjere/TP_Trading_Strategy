import pandas as pd
import numpy as np


def compute_transaction_costs(
    weights: pd.DataFrame,
    spread: float = 0.001,
    commission: float = 0.0005,
) -> pd.Series:
    """
    Monthly transaction cost as a fraction of portfolio value.

    cost_t = sum_i |Δw_{i,t}| * (spread/2 + commission)
    Turnover is defined as the sum of absolute weight changes across all assets.
    """
    turnover = weights.diff().abs().sum(axis=1)
    return turnover * (spread / 2 + commission)
