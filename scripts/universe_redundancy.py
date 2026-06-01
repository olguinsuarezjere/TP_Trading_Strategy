"""
Análisis de redundancia del universo de ETFs (solo lectura, NO modifica nada).

Idea (fiel a Moskowitz et al. 2012, que usa 1 instrumento líquido por mercado):
  1. Correlación de retornos MENSUALES entre los 205 ETFs (pairwise, con overlap mínimo).
  2. Agrupar por correlación >= THRESHOLD con complete-linkage: dentro de cada grupo
     TODOS los pares superan el umbral -> son el "mismo mercado" repetido.
  3. Dentro de cada grupo, marcar el más líquido por ADV (dollar volume promedio 1y, yfinance).
  4. Reportar antes/después por clase de activo. No recorta: solo propone.

Uso:  python scripts/universe_redundancy.py [--threshold 0.95] [--no-network]
"""
import os
import sys
import argparse

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.universe import ETF_UNIVERSE, ASSET_CLASSES  # noqa: E402
from src.data.loader import load_etf_prices, compute_monthly_returns  # noqa: E402

PRICES_PATH = os.path.join(ROOT, "Data", "etf_prices.parquet")
CLASS_ORDER = ["equity", "bond", "commodity", "currency"]


def monthly_returns() -> pd.DataFrame:
    prices = load_etf_prices(PRICES_PATH)
    rets = compute_monthly_returns(prices)
    return rets


def fetch_adv(tickers, period="1y", lookback_days=252) -> pd.Series:
    """Average daily DOLLAR volume (proxy de liquidez). Devuelve NaN si falla la red."""
    try:
        import yfinance as yf
        raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)
        close = raw["Close"]
        vol = raw["Volume"]
        adv = (close * vol).tail(lookback_days).mean()
        return adv.reindex(tickers)
    except Exception as e:  # pragma: no cover
        print(f"[warn] no se pudo bajar volumen ({type(e).__name__}: {e}). ADV = NaN.")
        return pd.Series(np.nan, index=list(tickers))


def complete_linkage_groups(corr: pd.DataFrame, threshold: float):
    """Clusters donde TODO par tiene corr >= threshold (complete linkage)."""
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import squareform

    cols = list(corr.columns)
    d = 1.0 - corr.values
    np.fill_diagonal(d, 0.0)
    d = (d + d.T) / 2.0                      # forzar simetría exacta
    condensed = squareform(d, checks=False)
    Z = linkage(condensed, method="complete")
    labels = fcluster(Z, t=1.0 - threshold, criterion="distance")
    groups = {}
    for tk, lab in zip(cols, labels):
        groups.setdefault(lab, []).append(tk)
    return list(groups.values())


def compute_curation(threshold=0.95, min_overlap=36, use_network=True):
    """Devuelve dict con keep/drop/groups/adv — la lista curada (1 ETF líquido por grupo).

    Reutilizable desde otros scripts (p. ej. el backtest comparativo). No imprime nada.
    """
    rets = monthly_returns()
    tickers = [t for t in rets.columns if t in ETF_UNIVERSE]
    rets = rets[tickers]

    corr = rets.corr(min_periods=min_overlap).fillna(0.0)
    np.fill_diagonal(corr.values, 1.0)
    groups = complete_linkage_groups(corr, threshold)

    adv = fetch_adv(tickers) if use_network else pd.Series(np.nan, index=tickers)

    def adv_usd(tk):
        v = adv.get(tk, np.nan)
        return v if pd.notna(v) else -1.0

    keep, drop = [], []
    for g in groups:
        if len(g) == 1:
            keep.append(g[0])
            continue
        g_sorted = sorted(g, key=lambda t: -adv_usd(t))
        keep.append(g_sorted[0])
        drop.extend(g_sorted[1:])

    return {"keep": sorted(set(keep)), "drop": sorted(set(drop)),
            "groups": groups, "adv": adv, "tickers": tickers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.95)
    ap.add_argument("--min-overlap", type=int, default=36,
                    help="meses mínimos de solapamiento para confiar en la correlación")
    ap.add_argument("--no-network", action="store_true", help="omite ADV/yfinance")
    args = ap.parse_args()

    rets = monthly_returns()
    tickers = [t for t in rets.columns if t in ETF_UNIVERSE]
    rets = rets[tickers]
    print(f"Universo: {len(tickers)} ETFs · retornos mensuales {rets.index[0]:%Y-%m} → {rets.index[-1]:%Y-%m}")

    # --- correlación pairwise con overlap mínimo ---
    corr = rets.corr(min_periods=args.min_overlap)
    # pares sin overlap suficiente -> 0 (no se agrupan)
    corr = corr.fillna(0.0)
    np.fill_diagonal(corr.values, 1.0)

    groups = complete_linkage_groups(corr, args.threshold)

    # --- liquidez ---
    if args.no_network:
        adv = pd.Series(np.nan, index=tickers)
    else:
        print("Bajando volumen (ADV 1y) de yfinance…")
        adv = fetch_adv(tickers)

    def adv_usd(tk):
        v = adv.get(tk, np.nan)
        return v if pd.notna(v) else -1.0

    # --- armar reporte ---
    dup_groups = [g for g in groups if len(g) > 1]
    singletons = [g[0] for g in groups if len(g) == 1]

    # representante = más líquido del grupo (mayor ADV); si no hay ADV, el primero
    keep, drop = [], []
    group_rows = []
    for g in sorted(dup_groups, key=lambda g: -len(g)):
        g_sorted = sorted(g, key=lambda t: -adv_usd(t))
        rep = g_sorted[0]
        keep.append(rep)
        drop.extend(g_sorted[1:])
        # min corr intra-grupo (control de calidad del cluster)
        sub = corr.loc[g, g].values
        min_corr = sub[np.triu_indices(len(g), k=1)].min()
        cls = ETF_UNIVERSE[rep]
        group_rows.append((cls, rep, g_sorted, min_corr))

    keep_all = sorted(set(keep) | set(singletons))

    # ---------- IMPRESIÓN ----------
    print("\n" + "=" * 78)
    print(f"GRUPOS DE ETFs CASI IDÉNTICOS  (corr >= {args.threshold}, complete-linkage)")
    print("=" * 78)
    if not group_rows:
        print("No se encontraron grupos redundantes con ese umbral.")
    for cls, rep, g_sorted, min_corr in sorted(group_rows, key=lambda r: (CLASS_ORDER.index(r[0]), -len(r[2]))):
        print(f"\n[{cls}] {len(g_sorted)} ETFs · corr intra-grupo ≥ {min_corr:.3f}")
        for i, tk in enumerate(g_sorted):
            a = adv.get(tk, np.nan)
            adv_txt = f"${a/1e6:,.0f}M/día" if pd.notna(a) else "ADV n/d"
            mark = "  ✅ MANTENER (más líquido)" if i == 0 else "  ✂️  candidato a sacar"
            print(f"     {tk:6} {adv_txt:>16}{mark}")

    # ---------- RESUMEN POR CLASE ----------
    def by_class(tks):
        c = {k: 0 for k in CLASS_ORDER}
        for t in tks:
            c[ETF_UNIVERSE[t]] += 1
        return c

    before = by_class(tickers)
    after = by_class(keep_all)
    print("\n" + "=" * 78)
    print("ANTES vs DESPUÉS  (mercados distintos = 1 ETF líquido por grupo)")
    print("=" * 78)
    print(f"{'Clase':<12}{'Antes':>8}{'Después':>10}{'Sacar':>8}")
    for c in CLASS_ORDER:
        print(f"{c:<12}{before[c]:>8}{after[c]:>10}{before[c]-after[c]:>8}")
    print(f"{'TOTAL':<12}{len(tickers):>8}{len(keep_all):>10}{len(tickers)-len(keep_all):>8}")
    print(f"\nGrupos redundantes: {len(dup_groups)} · ETFs únicos (singletons): {len(singletons)}")
    print(f"ETFs a sacar (propuesta): {len(drop)}")

    if drop:
        print("\nLista completa de candidatos a SACAR:")
        print("  " + ", ".join(sorted(drop)))


if __name__ == "__main__":
    main()
