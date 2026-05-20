import pandas as pd
import numpy as np


def sharpe_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    excess = returns - rf / 12
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


def sortino_ratio(returns: pd.Series, rf: float = 0.0) -> float:
    excess = returns - rf / 12
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
