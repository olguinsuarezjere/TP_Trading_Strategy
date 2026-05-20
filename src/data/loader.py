import pandas as pd
import numpy as np
from pathlib import Path
from .universe import ETF_UNIVERSE


def load_etf_prices(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "Date" in df.columns:
            df = df.set_index("Date")
        df.index = pd.to_datetime(df.index)
    return df.sort_index()


def update_prices(path: str, tickers: list[str] | None = None, start: str = "2012-01-01") -> pd.DataFrame:
    import yfinance as yf  # lazy import — solo se necesita al actualizar datos

    if tickers is None:
        tickers = list(ETF_UNIVERSE.keys())

    existing = pd.DataFrame()
    p = Path(path)
    if p.exists():
        existing = load_etf_prices(path)
        last_date = existing.index[-1]
        start = (last_date + pd.offsets.BDay(1)).strftime("%Y-%m-%d")

    raw = yf.download(tickers, start=start, auto_adjust=True, progress=False)
    new_prices = raw["Close"] if "Close" in raw.columns else raw

    if not existing.empty:
        combined = pd.concat([existing, new_prices[~new_prices.index.isin(existing.index)]])
    else:
        combined = new_prices

    combined = combined.sort_index()
    p.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path)
    return combined


def compute_monthly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    monthly = prices.resample("ME").last().ffill()
    returns = monthly.pct_change().dropna(how="all")
    # Keep only tickers present in our universe
    known = [c for c in returns.columns if c in ETF_UNIVERSE]
    return returns[known]


def load_returns(config: dict) -> pd.DataFrame:
    prices = load_etf_prices(config["data"]["path"])
    returns = compute_monthly_returns(prices)

    start = config["backtest"].get("start_date")
    end = config["backtest"].get("end_date")
    if start:
        returns = returns[returns.index >= start]
    if end:
        returns = returns[returns.index <= end]

    # Drop columns with >20% missing values
    thresh = int(len(returns) * 0.8)
    returns = returns.dropna(axis=1, thresh=thresh)
    return returns.ffill().bfill()
