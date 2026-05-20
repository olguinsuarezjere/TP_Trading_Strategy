from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from ..strategy.portfolio import build_portfolio
from .costs import compute_transaction_costs
from .metrics import performance_report


@dataclass
class BacktestResults:
    portfolio_returns: pd.Series
    weights: pd.DataFrame
    signal: pd.DataFrame
    gross_returns: pd.Series
    costs: pd.Series
    metrics: dict = field(default_factory=dict)

    def __post_init__(self):
        self.metrics = performance_report(self.portfolio_returns, self.weights)

    @property
    def cumulative(self) -> pd.Series:
        return (1 + self.portfolio_returns).cumprod()


class BacktestEngine:
    def __init__(self, config: dict):
        self.config = config

    def run(self, returns: pd.DataFrame, use_signal_strength: bool = False) -> BacktestResults:
        weights, signal = build_portfolio(returns, self.config, use_signal_strength)

        # Gross portfolio return: sum of (weight_{t-1} * return_t)
        # Weights are already lagged inside build_portfolio (signal uses .shift(1))
        gross_returns = (weights * returns).sum(axis=1)

        # Transaction costs
        tc_config = self.config["transaction_costs"]
        costs = compute_transaction_costs(
            weights,
            spread=tc_config["bid_ask_spread"],
            commission=tc_config["commission_pct"],
        )

        net_returns = gross_returns - costs

        # Drop leading NaN rows (warm-up period for signals)
        first_valid = net_returns.first_valid_index()
        net_returns = net_returns.loc[first_valid:]
        gross_returns = gross_returns.loc[first_valid:]
        costs = costs.loc[first_valid:]
        weights = weights.loc[first_valid:]
        signal = signal.loc[first_valid:]

        return BacktestResults(
            portfolio_returns=net_returns,
            weights=weights,
            signal=signal,
            gross_returns=gross_returns,
            costs=costs,
        )
