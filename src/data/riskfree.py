"""Tasa libre de riesgo para el Sharpe — T-bill a 1 mes, variable en el tiempo.

El rf del ratio de Sharpe debe matchear el período de TENENCIA/MEDICIÓN de la
estrategia (Sharpe 1994: "one-period riskless asset"). Como rebalanceamos y medimos
MENSUAL, el match correcto es la T-bill a 1 mes — no el lookback de la señal ni la
duración de los activos.

Fuente canónica: FRED `DGS1MO` (Fed H.15, "1-Month Treasury Constant Maturity Rate").
Se cachea en disco (Data/riskfree_1m.parquet) para no depender de la red en cada
corrida — mismo criterio que el parquet de precios. Si no hay red ni cache, cae a un
proxy 100% offline: el retorno mensual realizado de **BIL** (ETF de T-bills 1-3m), que
ES el retorno libre de riesgo efectivamente ganado ese mes (consistente con que
medimos el Sharpe sobre retornos realizados).
"""
import pandas as pd
from pathlib import Path

# Fuente PRIMARIA: Tesoro de EE.UU. (Daily Treasury Bill Rates). La columna
# "4 WEEKS COUPON EQUIVALENT" es la T-bill a 1 mes en base bond-equivalent — la misma
# que publica FRED como DGS1MO (FRED deriva de acá). Es por año.
TREASURY_BILL_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_bill_rates"
    "&field_tdr_date_value={year}&page&_format=csv"
)
TREASURY_1M_COL = "4 WEEKS COUPON EQUIVALENT"
FRED_DGS1MO_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS1MO"
DEFAULT_CACHE = "Data/riskfree_1m.parquet"


def _fetch_treasury_1m(start_year: int = 2012, end_year: int | None = None) -> pd.Series | None:
    """Baja la T-bill a 4 semanas (= 1 mes), coupon-equivalent, del Tesoro de EE.UU.
    Recorre año por año (2012..hoy). Serie diaria en decimal anual, o None si falla todo."""
    end_year = end_year or pd.Timestamp.today().year
    frames = []
    for y in range(start_year, end_year + 1):
        try:
            df = pd.read_csv(TREASURY_BILL_URL.format(year=y))
        except Exception:
            continue
        if TREASURY_1M_COL not in df.columns or "Date" not in df.columns:
            continue
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        s = pd.to_numeric(df.set_index("Date")[TREASURY_1M_COL], errors="coerce").dropna()
        if len(s):
            frames.append(s)
    if not frames:
        return None
    out = (pd.concat(frames).sort_index() / 100.0)            # % anual -> decimal anual
    return out[~out.index.duplicated(keep="last")]


def _fetch_fred_dgs1mo() -> pd.Series | None:
    """Alterna: baja DGS1MO de FRED (yield anual en %). Serie diaria en decimal, o None."""
    try:
        df = pd.read_csv(FRED_DGS1MO_URL)
        df.columns = ["date", "rate"]
        df["date"] = pd.to_datetime(df["date"])
        df["rate"] = pd.to_numeric(df["rate"], errors="coerce")   # FRED usa '.' para faltantes -> NaN
        s = df.set_index("date")["rate"].dropna() / 100.0          # % anual -> decimal anual
        return s if len(s) else None
    except Exception:
        return None


def _bil_proxy_monthly(prices_path: str) -> pd.Series | None:
    """Proxy offline: retorno mensual realizado de BIL (T-bills 1-3m) = rf mensual realizado."""
    try:
        from .loader import load_etf_prices
        px = load_etf_prices(prices_path)
        if "BIL" not in px.columns:
            return None
        return px["BIL"].resample("ME").last().pct_change().dropna()
    except Exception:
        return None


def load_tbill_1m_raw(
    cache_path: str = DEFAULT_CACHE,
    prices_path: str = "Data/etf_prices.parquet",
    refresh: bool = False,
) -> pd.Series:
    """Serie COMPLETA (sin alinear) de la T-bill a 1 mes como rf MENSUAL (decimal).

    Orden de fuentes: cache en disco -> Tesoro EE.UU. -> FRED DGS1MO -> proxy BIL (offline).
    `refresh=True` ignora el cache y vuelve a bajar de la fuente oficial.
    El atributo `.attrs['source']` indica de dónde salió.
    """
    p = Path(cache_path)
    annual = None
    source = None
    if p.exists() and not refresh:
        annual = pd.read_parquet(p).iloc[:, 0]
        source = f"cache ({cache_path})"
    else:
        annual = _fetch_treasury_1m()                 # 1) fuente oficial (alcanzable)
        source = "Tesoro EE.UU. 4-semanas coupon-equiv (descargado y cacheado)"
        if annual is None:
            annual = _fetch_fred_dgs1mo()             # 2) alterna FRED
            source = "FRED DGS1MO (descargado y cacheado)"
        if annual is not None:
            p.parent.mkdir(parents=True, exist_ok=True)
            annual.to_frame("tbill_1m").to_parquet(p)

    if annual is not None:
        monthly = annual.resample("ME").last() / 12.0     # yield anual -> tasa mensual
    else:
        monthly = _bil_proxy_monthly(prices_path)          # ya es retorno mensual realizado
        source = "BIL proxy (offline, sin red ni cache)"
        if monthly is None:
            raise RuntimeError("No se pudo obtener la rf: ni cache, ni Tesoro, ni FRED, ni BIL en el parquet.")

    monthly = monthly.dropna()
    monthly.attrs["source"] = source
    monthly.name = "rf_1m_monthly"
    return monthly


def load_tbill_1m_monthly(
    index: pd.DatetimeIndex,
    cache_path: str = DEFAULT_CACHE,
    prices_path: str = "Data/etf_prices.parquet",
    refresh: bool = False,
) -> pd.Series:
    """T-bill a 1 mes como rf MENSUAL (decimal) alineada al `index` mensual dado."""
    raw = load_tbill_1m_raw(cache_path, prices_path, refresh)
    out = raw.reindex(index).ffill().bfill()
    out.attrs["source"] = raw.attrs.get("source")
    out.name = "rf_1m_monthly"
    return out
