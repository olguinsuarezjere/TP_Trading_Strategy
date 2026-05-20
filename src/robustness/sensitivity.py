import pandas as pd
import numpy as np
from copy import deepcopy

from ..backtest.engine import BacktestEngine
from ..backtest.metrics import sharpe_ratio, annualized_return, max_drawdown


def _run_variant(returns: pd.DataFrame, config: dict) -> dict:
    engine = BacktestEngine(config)
    res = engine.run(returns)
    r = res.portfolio_returns
    return {
        "sharpe":   sharpe_ratio(r),
        "ann_ret":  annualized_return(r),
        "max_dd":   max_drawdown(r),
    }


def lookback_sensitivity(
    returns: pd.DataFrame,
    config: dict,
    lookbacks: list[int] = [3, 6, 9, 12, 18, 24],
) -> pd.DataFrame:
    rows = []
    for lb in lookbacks:
        cfg = deepcopy(config)
        cfg["strategy"]["lookback_months"] = lb
        stats = _run_variant(returns, cfg)
        stats["lookback"] = lb
        rows.append(stats)
    return pd.DataFrame(rows).set_index("lookback")


def target_vol_sensitivity(
    returns: pd.DataFrame,
    config: dict,
    target_vols: list[float] = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20],
) -> pd.DataFrame:
    rows = []
    for tv in target_vols:
        cfg = deepcopy(config)
        cfg["strategy"]["target_volatility"] = tv
        stats = _run_variant(returns, cfg)
        stats["target_vol"] = tv
        rows.append(stats)
    return pd.DataFrame(rows).set_index("target_vol")


def cost_sensitivity(
    returns: pd.DataFrame,
    config: dict,
    spreads: list[float] = [0.0, 0.001, 0.005, 0.01, 0.02],
) -> pd.DataFrame:
    rows = []
    for sp in spreads:
        cfg = deepcopy(config)
        cfg["transaction_costs"]["bid_ask_spread"] = sp
        stats = _run_variant(returns, cfg)
        stats["spread"] = sp
        rows.append(stats)
    return pd.DataFrame(rows).set_index("spread")
