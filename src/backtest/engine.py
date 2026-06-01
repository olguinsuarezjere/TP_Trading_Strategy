from dataclasses import dataclass, field
import pandas as pd
import numpy as np

from ..strategy.portfolio import build_portfolio
from .costs import compute_transaction_costs
from .metrics import performance_report


def apply_portfolio_vol_scaling(
    weights: pd.DataFrame,
    returns: pd.DataFrame,
    target_portfolio_vol: float = 0.07,
    com_months: float = 3.0,
    max_leverage: float = 2.0,
) -> pd.DataFrame:
    """
    Moreira & Muir (2017): Volatility-Managed Portfolios.
    scaling_t = clip(target_portfolio_vol / ewma_port_vol_{t-1}, 0, max_leverage)
    """
    portfolio_ret = (weights * returns).sum(axis=1)
    ewma_var = (portfolio_ret ** 2).ewm(com=com_months, min_periods=1).mean()
    ewma_vol = np.sqrt(ewma_var * 12)
    scaling  = (target_portfolio_vol / ewma_vol.shift(1).replace(0, np.nan)).clip(upper=max_leverage)
    scaling  = scaling.fillna(1.0)
    return weights.mul(scaling, axis=0)


def build_scaled_weights(
    returns: pd.DataFrame,
    config: dict,
    use_signal_strength: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pesos FINALES de la estrategia: build_portfolio + (opcional) portfolio vol
    scaling de Moreira-Muir + re-clip de posiciones.

    Es la ÚNICA fuente de verdad de los pesos: la usan tanto el backtest como la
    ejecución en vivo, para que en IBKR se operen exactamente los pesos validados.
    """
    weights, signal = build_portfolio(returns, config, use_signal_strength)
    if config["strategy"].get("use_portfolio_vol_scaling", False):
        weights = apply_portfolio_vol_scaling(
            weights, returns,
            target_portfolio_vol=config["strategy"].get("target_portfolio_vol", 0.07),
            com_months=config["strategy"]["vol_com_months"],
        )
        from ..strategy.portfolio import apply_position_constraints
        weights = apply_position_constraints(weights, config["strategy"]["max_position_weight"])
    return weights, signal


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
        # Pesos finales (incluye portfolio vol scaling) — misma fuente que la ejecución en vivo.
        weights, signal = build_scaled_weights(returns, self.config, use_signal_strength)

        # Gross portfolio return: sum of (weight_{t-1} * return_t)
        gross_returns = (weights * returns).sum(axis=1)

        # Transaction costs — sobre weights finales (scaled + clipped)
        tc_config = self.config["transaction_costs"]
        costs = compute_transaction_costs(
            weights,
            spread=tc_config["bid_ask_spread"],
            commission=tc_config["commission_pct"],
        )

        net_returns = gross_returns - costs

        # Drop leading NaN rows (warm-up period for signals)
        first_valid = net_returns.first_valid_index()
        net_returns   = net_returns.loc[first_valid:]
        gross_returns = gross_returns.loc[first_valid:]
        costs         = costs.loc[first_valid:]
        weights       = weights.loc[first_valid:]
        signal        = signal.loc[first_valid:]

        return BacktestResults(
            portfolio_returns=net_returns,
            weights=weights,
            signal=signal,
            gross_returns=gross_returns,
            costs=costs,
        )
