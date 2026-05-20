import pandas as pd
import numpy as np

from ..backtest.engine import BacktestEngine
from ..backtest.metrics import sharpe_ratio, annualized_return, max_drawdown


def walk_forward(
    returns: pd.DataFrame,
    config: dict,
    train_years: int = 5,
    test_years: int = 1,
) -> pd.DataFrame:
    """
    Rolling walk-forward analysis.

    Trains on train_years, tests on test_years, advances by test_years.
    Returns per-window performance metrics.
    """
    train_months = train_years * 12
    test_months = test_years * 12
    engine = BacktestEngine(config)
    rows = []

    start_idx = train_months
    while start_idx + test_months <= len(returns):
        train = returns.iloc[:start_idx]
        test_slice = returns.iloc[start_idx: start_idx + test_months]

        # Run on combined window so signals have context, then slice test period
        combined = returns.iloc[:start_idx + test_months]
        res = engine.run(combined)
        test_returns = res.portfolio_returns.iloc[-test_months:]

        rows.append({
            "train_end":  train.index[-1].strftime("%Y-%m"),
            "test_start": test_slice.index[0].strftime("%Y-%m"),
            "test_end":   test_slice.index[-1].strftime("%Y-%m"),
            "sharpe":     sharpe_ratio(test_returns),
            "ann_ret":    annualized_return(test_returns),
            "max_dd":     max_drawdown(test_returns),
        })
        start_idx += test_months

    return pd.DataFrame(rows)


def expanding_window(
    returns: pd.DataFrame,
    config: dict,
    min_train_months: int = 36,
) -> pd.Series:
    """
    Expanding-window out-of-sample returns.

    At each month t, uses all data up to t to form the signal, returns r_{t+1}.
    Equivalent to a live trading simulation starting after min_train_months.
    """
    engine = BacktestEngine(config)
    res = engine.run(returns)
    oos_returns = res.portfolio_returns.iloc[min_train_months:]
    is_returns = res.portfolio_returns.iloc[:min_train_months]

    summary = pd.DataFrame({
        "Period":    ["In-Sample", "Out-of-Sample", "Full"],
        "Sharpe":    [sharpe_ratio(is_returns), sharpe_ratio(oos_returns),
                      sharpe_ratio(res.portfolio_returns)],
        "Ann Ret":   [annualized_return(is_returns), annualized_return(oos_returns),
                      annualized_return(res.portfolio_returns)],
        "Max DD":    [max_drawdown(is_returns), max_drawdown(oos_returns),
                      max_drawdown(res.portfolio_returns)],
    }).set_index("Period")
    return summary
