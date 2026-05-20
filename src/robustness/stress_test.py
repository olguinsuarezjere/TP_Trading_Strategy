import pandas as pd
import numpy as np

from ..backtest.metrics import sharpe_ratio, annualized_return, max_drawdown, annualized_volatility

CRISIS_PERIODS: dict[str, tuple[str, str]] = {
    "GFC_2008":        ("2007-01-01", "2009-06-30"),
    "COVID_2020":      ("2020-01-01", "2020-09-30"),
    "Rate_Shock_2022": ("2022-01-01", "2022-12-31"),
    "Taper_2013":      ("2013-05-01", "2013-12-31"),
}


def analyze_crisis_performance(portfolio_returns: pd.Series) -> pd.DataFrame:
    rows = []
    for name, (start, end) in CRISIS_PERIODS.items():
        window = portfolio_returns.loc[start:end]
        if len(window) < 2:
            continue
        rows.append({
            "Period":      name,
            "Start":       start,
            "End":         end,
            "Ann Return":  f"{annualized_return(window):.2%}",
            "Volatility":  f"{annualized_volatility(window):.2%}",
            "Sharpe":      f"{sharpe_ratio(window):.2f}",
            "Max DD":      f"{max_drawdown(window):.2%}",
            "Months":      len(window),
        })
    return pd.DataFrame(rows).set_index("Period")


def worst_drawdowns(portfolio_returns: pd.Series, n: int = 5) -> pd.DataFrame:
    cum = (1 + portfolio_returns).cumprod()
    running_max = cum.cummax()
    dd_series = (cum - running_max) / running_max

    drawdowns = []
    in_dd = False
    start = None
    trough_val = 0.0
    trough_date = None

    for date, val in dd_series.items():
        if val < 0 and not in_dd:
            in_dd = True
            start = date
            trough_val = val
            trough_date = date
        elif val < trough_val and in_dd:
            trough_val = val
            trough_date = date
        elif val == 0 and in_dd:
            drawdowns.append({
                "Start":    start,
                "Trough":   trough_date,
                "Recovery": date,
                "Depth":    f"{trough_val:.2%}",
                "Duration": (date - start).days // 30,
            })
            in_dd = False
            trough_val = 0.0

    drawdowns.sort(key=lambda x: float(x["Depth"].replace("%", "")))
    return pd.DataFrame(drawdowns[:n])
