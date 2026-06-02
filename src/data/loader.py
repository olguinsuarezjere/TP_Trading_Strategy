import pandas as pd
import numpy as np
from pathlib import Path
from .universe import ETF_UNIVERSE, REDUNDANT_TICKERS, EXCLUDED_TICKERS


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


def data_status(config: dict) -> dict:
    """Diagnóstico de consistencia entre universe.py y el parquet.

    Devuelve un dict con:
      - missing:     ETFs del universo SIN datos en el parquet (hay que descargar)
      - orphans:     columnas del parquet que NO están en el universo (datos sin usar)
      - coverage:    % de meses con dato en la ventana, por ticker del universo
      - inception:   primer mes con dato, por ticker
      - active:      tickers con historia suficiente -> participan del backtest
      - insufficient: tickers con < min_history_months -> el loader los descarta
      - late:        tickers activos pero que arrancan después del inicio de ventana
    """
    prices = load_etf_prices(config["data"]["path"])
    have = set(prices.columns)
    uni = set(ETF_UNIVERSE.keys())

    monthly = compute_monthly_returns(prices)
    start = config["backtest"].get("start_date")
    end = config["backtest"].get("end_date") or last_complete_month_end()
    if start:
        monthly = monthly[monthly.index >= start]
    if end:
        monthly = monthly[monthly.index <= end]

    min_history = config.get("data", {}).get("min_history_months", 24)
    n_obs = monthly.notna().sum()
    coverage = (monthly.notna().mean() * 100).round(1).sort_values()
    inception = {t: monthly[t].first_valid_index() for t in monthly.columns}

    active = [t for t in coverage.index if n_obs[t] >= min_history]
    insufficient = [t for t in coverage.index if n_obs[t] < min_history]
    win_start = monthly.index[0] if len(monthly) else None
    late = [t for t in active
            if inception[t] is not None and win_start is not None
            and inception[t] > win_start]

    return {
        "n_universe": len(uni),
        "n_parquet": len(have),
        "min_history": min_history,
        "missing": sorted(uni - have),
        # Redundantes (curación corr>=0.95) y excluidos (.MI/.TO) son exclusiones
        # intencionales: no se reportan como orphans sorpresa.
        "orphans": sorted(have - uni - set(REDUNDANT_TICKERS) - set(EXCLUDED_TICKERS)),
        "redundant_present": sorted(have & set(REDUNDANT_TICKERS)),
        "coverage": coverage,
        "inception": inception,
        "active": active,
        "insufficient": insufficient,
        "late": late,
        "window": (monthly.index[0], monthly.index[-1]) if len(monthly) else None,
    }


def last_complete_month_end() -> str:
    """Último mes CERRADO (fin del mes anterior al actual). Excluye el mes en curso
    para que nunca entre un retorno mensual parcial. Se calcula con la fecha de hoy,
    así la ventana del backtest avanza sola a medida que cierran los meses."""
    from datetime import date, timedelta
    first_of_month = date.today().replace(day=1)
    return (first_of_month - timedelta(days=1)).strftime("%Y-%m-%d")


def load_returns(config: dict) -> pd.DataFrame:
    prices = load_etf_prices(config["data"]["path"])
    returns = compute_monthly_returns(prices)

    start = config["backtest"].get("start_date")
    # end_date vacío/None => ventana abierta: usa hasta el último mes COMPLETO (auto-avanza).
    end = config["backtest"].get("end_date") or last_complete_month_end()
    if start:
        returns = returns[returns.index >= start]
    if end:
        returns = returns[returns.index <= end]

    # Cada ETF se usa DESDE SU INCEPTION: los meses previos a que existiera quedan
    # como NaN. El pipeline (señal -> peso) ya trata el NaN como "activo inactivo"
    # (peso 0), así que NO se rellena pre-inception (eso sería lookahead). Solo se
    # descartan los ETFs sin historia suficiente para llegar a formar una señal.
    min_history = config.get("data", {}).get("min_history_months", 24)
    enough = returns.notna().sum() >= min_history
    returns = returns.loc[:, enough]
    return returns
