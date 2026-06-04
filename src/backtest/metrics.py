import pandas as pd
import numpy as np


_RF_SERIES_CACHE = None  # serie cruda mensual de la T-bill 1m, memoizada por proceso


def _default_rf_series() -> pd.Series:
    """T-bill a 1 mes (rf mensual real) — el default del proyecto. Se carga una sola vez."""
    global _RF_SERIES_CACHE
    if _RF_SERIES_CACHE is None:
        from ..data.riskfree import load_tbill_1m_raw
        _RF_SERIES_CACHE = load_tbill_1m_raw()
    return _RF_SERIES_CACHE


def _excess_returns(returns: pd.Series, rf) -> pd.Series:
    """Retorno en exceso de la tasa libre de riesgo.

    rf = None   -> DEFAULT del proyecto: exceso sobre la T-bill a 1 mes (serie real,
                   variable en el tiempo; ver src/data/riskfree.py). Operamos ETF cash
                   fully-funded, así que el Sharpe se mide sobre el exceso (Sharpe 1994).
    rf Series   -> tasa MENSUAL ya por-período, alineada por índice.
    rf escalar  -> tasa ANUAL constante (se divide por 12). Solo para análisis explícito.
    """
    if rf is None:
        rf = _default_rf_series()
    if isinstance(rf, pd.Series):
        return returns - rf.reindex(returns.index).ffill().bfill()
    return returns - rf / 12


def sharpe_ratio(returns: pd.Series, rf=None) -> float:
    excess = _excess_returns(returns, rf)
    if excess.std() == 0:
        return np.nan
    return float((excess.mean() / excess.std()) * np.sqrt(12))


def annualized_return(returns: pd.Series) -> float:
    n = len(returns)
    if n == 0:
        return np.nan
    return float((1 + returns).prod() ** (12 / n) - 1)


def annualized_volatility(returns: pd.Series) -> float:
    return float(returns.std() * np.sqrt(12))


def max_drawdown(returns: pd.Series) -> float:
    cum = (1 + returns).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    return float(dd.min())


def calmar_ratio(returns: pd.Series) -> float:
    ann_ret = annualized_return(returns)
    mdd = abs(max_drawdown(returns))
    if mdd == 0:
        return np.nan
    return ann_ret / mdd


def sortino_ratio(returns: pd.Series, rf=None) -> float:
    excess = _excess_returns(returns, rf)
    downside = excess[excess < 0].std()
    if downside == 0:
        return np.nan
    return float((excess.mean() / downside) * np.sqrt(12))


def turnover(weights: pd.DataFrame) -> float:
    """Average monthly one-way turnover (sum of absolute weight changes)."""
    return float(weights.diff().abs().sum(axis=1).mean())


def hit_rate(returns: pd.Series) -> float:
    return float((returns > 0).mean())


def performance_report(returns: pd.Series, weights: pd.DataFrame | None = None) -> dict:
    report = {
        "Annualized Return":     f"{annualized_return(returns):.2%}",
        "Annualized Volatility": f"{annualized_volatility(returns):.2%}",
        "Sharpe Ratio":          f"{sharpe_ratio(returns):.2f}",
        "Sortino Ratio":         f"{sortino_ratio(returns):.2f}",
        "Max Drawdown":          f"{max_drawdown(returns):.2%}",
        "Calmar Ratio":          f"{calmar_ratio(returns):.2f}",
        "Hit Rate":              f"{hit_rate(returns):.2%}",
        "Num Months":            str(len(returns)),
    }
    if weights is not None:
        report["Avg Monthly Turnover"] = f"{turnover(weights):.2%}"
    return report


def print_report(metrics: dict, title: str = "Performance Summary") -> None:
    width = 42
    print(f"\n{'-' * width}")
    print(f"  {title}")
    print(f"{'-' * width}")
    for k, v in metrics.items():
        print(f"  {k:<28} {v:>10}")
    print(f"{'-' * width}\n")
