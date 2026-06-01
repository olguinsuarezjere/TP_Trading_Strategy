"""
Sincroniza Data/etf_prices.parquet con el universo oficial (src/data/universe.py).

Qué hace, en orden:
  1. Quita del parquet los tickers EXCLUIDOS (extranjeros .MI/.TO en EUR/CAD).
  2. Descarga de yfinance los ETFs del universo que falten en el parquet.
  3. Valida cada descarga: debe estar denominada en USD y tener al menos
     MIN_OBS días de historia. Los ETFs que arrancaron después de 2012 SÍ se
     aceptan — se usan desde su inception (el loader maneja el NaN pre-inception
     sin lookahead). Lo que no valida se RECHAZA y se reporta con el motivo.
  4. Hace merge, backup y guarda.

Es idempotente: se puede correr varias veces. Necesita un Python con yfinance
instalado, por ejemplo:

    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
        scripts/fetch_missing_etfs.py
    python scripts/fetch_missing_etfs.py --dry-run   # solo reporta, no escribe

Al final imprime, si las hay, los líneas de tickers a PODAR de universe.py
(los que no pasaron validación), para mantener universe.py == parquet.
"""
import sys
import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.universe import ETF_UNIVERSE, EXCLUDED_TICKERS  # noqa: E402

PARQUET = ROOT / "Data" / "etf_prices.parquet"
START = "2012-01-01"
MIN_OBS = 500             # mínimo de días con dato (~2 años) para aceptar un ticker
#   No hay corte de inception: los ETFs que arrancaron después de 2012 se aceptan
#   y se usan desde su inception. El loader (min_history_months) decide si tienen
#   historia suficiente para formar señal.


def load_existing() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET)
    if "Date" in df.columns:
        df = df.set_index("Date")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def get_currency(ticker: str, yf) -> str | None:
    """Moneda de cotización según yfinance (best-effort)."""
    try:
        fi = yf.Ticker(ticker).fast_info
        cur = getattr(fi, "currency", None)
        if cur is None and hasattr(fi, "get"):
            cur = fi.get("currency")
        return cur
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="solo reporta, no descarga ni escribe")
    args = ap.parse_args()

    import yfinance as yf

    existing = load_existing()
    universe = list(ETF_UNIVERSE.keys())

    print(f"Parquet actual:   {existing.shape[0]} días x {existing.shape[1]} columnas")
    print(f"Universo oficial: {len(universe)} ETFs")

    # --- 1) Quitar tickers excluidos (extranjeros en EUR/CAD) ---
    to_drop = [t for t in EXCLUDED_TICKERS if t in existing.columns]
    if to_drop:
        print(f"\nExcluidos a quitar del parquet ({len(to_drop)}):")
        for t in to_drop:
            print(f"  - {t:8} {EXCLUDED_TICKERS[t]}")

    # --- 2) Detectar faltantes ---
    have = set(existing.columns) - set(to_drop)
    missing = [t for t in universe if t not in have]
    print(f"\nEn el universo pero faltan en el parquet ({len(missing)}):")
    print(f"  {missing}" if missing else "  (ninguno)")

    if args.dry_run:
        print("\n[dry-run] no se descarga ni se escribe nada.")
        return

    accepted, rejected = [], []   # rejected: (ticker, motivo)
    close = pd.DataFrame()

    # --- 3) Descargar y validar faltantes ---
    if missing:
        print(f"\nDescargando {len(missing)} tickers desde {START} …")
        raw = yf.download(missing, start=START, auto_adjust=True, progress=False)
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
        if isinstance(close, pd.Series):  # un solo ticker
            close = close.to_frame(missing[0])

        for t in missing:
            col = close[t] if t in close.columns else None
            if col is None or col.notna().sum() < MIN_OBS:
                obs = 0 if col is None else int(col.notna().sum())
                rejected.append((t, f"sin datos / delisted ({obs} días)"))
                continue
            cur = get_currency(t, yf)
            if cur is not None and cur != "USD":
                rejected.append((t, f"moneda {cur} (no USD)"))
                continue
            first = col.first_valid_index()
            accepted.append(t)
            if first is not None and first > pd.Timestamp("2012-06-01"):
                print(f"  + {t:6} late-starter, se usa desde {first.date()}")

        print(f"\nValidación (USD, >={MIN_OBS} días):")
        print(f"  Aceptados ({len(accepted)}): {accepted}")
        if rejected:
            print(f"  Rechazados ({len(rejected)}):")
            for t, motivo in rejected:
                print(f"    - {t:8} {motivo}")

    # --- 4) Aplicar cambios al parquet ---
    changed = bool(to_drop) or bool(accepted)
    if not changed:
        print("\nNada que cambiar. El parquet ya está sincronizado con el universo.")
        _print_prune_hint(rejected)
        return

    backup = PARQUET.with_suffix(".parquet.bak")
    if not backup.exists():
        existing.to_parquet(backup)
        print(f"\nBackup del parquet original -> {backup.name}")

    combined = existing.drop(columns=to_drop, errors="ignore")
    if accepted:
        new_idx = combined.index.union(close.index)
        combined = combined.reindex(new_idx)
        for t in accepted:
            combined[t] = close[t].reindex(new_idx)
    combined = combined.sort_index()

    combined.to_parquet(PARQUET)
    print(f"\nGuardado: {combined.shape[0]} días x {combined.shape[1]} columnas")
    if to_drop:
        print(f"  (-{len(to_drop)} excluidos)")
    if accepted:
        print(f"  (+{len(accepted)} ETFs nuevos)")

    _print_prune_hint(rejected)


def _print_prune_hint(rejected: list[tuple[str, str]]) -> None:
    if rejected:
        names = [t for t, _ in rejected]
        print("\n⚠  Estos tickers NO pasaron validación y deberían quitarse de "
              "universe.py para mantenerlo == parquet:")
        print(f"   {names}")


if __name__ == "__main__":
    main()
