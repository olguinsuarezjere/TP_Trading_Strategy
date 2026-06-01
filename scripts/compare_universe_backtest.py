"""
Backtest comparativo: universo COMPLETO (205) vs CURADO (1 ETF líquido por mercado, corr>=0.95).
Solo lectura — NO modifica universe.py ni config.yaml.

Corre el motor real (BacktestEngine) sobre ambos universos, con:
  (A) los parámetros del config tal cual (lookback/target_vol actuales), y
  (B) cada universo en SU PROPIO óptimo in-sample (como hace el dashboard).

Uso:  python scripts/compare_universe_backtest.py [--threshold 0.95]
"""
import os
import sys
import argparse
from copy import deepcopy

import numpy as np
import pandas as pd
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.loader import load_returns  # noqa: E402
from src.backtest.engine import BacktestEngine  # noqa: E402
from src.backtest.metrics import (  # noqa: E402
    sharpe_ratio, sortino_ratio, annualized_return, annualized_volatility,
    max_drawdown, calmar_ratio, turnover,
)
from src.robustness.sensitivity import optimize_sharpe  # noqa: E402
from scripts.universe_redundancy import compute_curation  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config.yaml")


def metrics_row(results) -> dict:
    r = results.portfolio_returns
    gross = results.gross_returns
    # drag de costos anualizado = (ret bruto - ret neto) anualizado
    cost_drag = annualized_return(gross) - annualized_return(r)
    # nº promedio de posiciones activas por mes
    w = results.weights
    n_pos = (w.abs() > 1e-9).sum(axis=1)
    return {
        "Sharpe": sharpe_ratio(r),
        "Sortino": sortino_ratio(r),
        "Ann.Return": annualized_return(r),
        "Ann.Vol": annualized_volatility(r),
        "MaxDD": max_drawdown(r),
        "Calmar": calmar_ratio(r),
        "Turnover/mes": turnover(w),
        "CostDrag/año": cost_drag,
        "Pos.activas~": n_pos.mean(),
    }


def run_universe(returns, config, label):
    results = BacktestEngine(config).run(
        returns, use_signal_strength=(config["strategy"]["signal_mode"] == "strength"))
    row = metrics_row(results)
    row["_label"] = label
    return row


def fmt(row):
    def p(x):
        return f"{x*100:.2f}%"
    return {
        "Sharpe": f"{row['Sharpe']:.3f}",
        "Sortino": f"{row['Sortino']:.3f}",
        "Ann.Return": p(row["Ann.Return"]),
        "Ann.Vol": p(row["Ann.Vol"]),
        "MaxDD": p(row["MaxDD"]),
        "Calmar": f"{row['Calmar']:.2f}",
        "Turnover/mes": p(row["Turnover/mes"]),
        "CostDrag/año": p(row["CostDrag/año"]),
        "Pos.activas~": f"{row['Pos.activas~']:.0f}",
    }


def print_block(title, full_row, cur_row):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    f_full, f_cur = fmt(full_row), fmt(cur_row)
    keys = ["Sharpe", "Sortino", "Ann.Return", "Ann.Vol", "MaxDD", "Calmar",
            "Turnover/mes", "CostDrag/año", "Pos.activas~"]
    print(f"{'Métrica':<14}{'205 (full)':>14}{'Curado':>14}{'Δ':>14}")
    print("-" * 72)
    for k in keys:
        delta = cur_row[_raw_key(k)] - full_row[_raw_key(k)]
        if k in ("Sharpe", "Sortino", "Calmar", "Pos.activas~"):
            dtxt = f"{delta:+.2f}" if k != "Pos.activas~" else f"{delta:+.0f}"
        else:
            dtxt = f"{delta*100:+.2f}pp"
        print(f"{k:<14}{f_full[k]:>14}{f_cur[k]:>14}{dtxt:>14}")


def _raw_key(k):
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.95)
    args = ap.parse_args()

    with open(CONFIG_PATH) as f:
        config = yaml.safe_load(f)

    returns_full = load_returns(config)
    print(f"Retornos: {returns_full.shape[1]} ETFs · {returns_full.index[0]:%Y-%m} → {returns_full.index[-1]:%Y-%m}")

    print(f"\nCurando universo (corr >= {args.threshold}, 1 ETF más líquido por grupo)…")
    cur = compute_curation(threshold=args.threshold, use_network=True)
    keep = [t for t in cur["keep"] if t in returns_full.columns]
    returns_cur = returns_full[keep]
    print(f"  Full: {returns_full.shape[1]} ETFs  →  Curado: {len(keep)} ETFs  (sacando {returns_full.shape[1]-len(keep)})")

    sig = config["strategy"]["signal_mode"]
    wgt = config["strategy"]["weighting"]
    print(f"  Config: señal={sig} · ponderación={wgt} · crash_filter={config['strategy'].get('use_crash_filter')} "
          f"· vol_scaling={config['strategy'].get('use_portfolio_vol_scaling')}")

    # ---------- (A) mismos parámetros del config ----------
    lb = config["strategy"]["lookback_months"]
    tv = config["strategy"]["target_volatility"]
    full_A = run_universe(returns_full, config, "full")
    cur_A = run_universe(returns_cur, config, "curado")
    print_block(f"(A) MISMOS PARÁMETROS DEL CONFIG  ·  LB={lb}m · TV={tv*100:.0f}% · {sig}/{wgt}",
                full_A, cur_A)

    # ---------- (B) cada universo en su propio óptimo in-sample ----------
    best_full, _ = optimize_sharpe(returns_full, config)
    best_cur, _ = optimize_sharpe(returns_cur, config)
    cfg_full = deepcopy(config)
    cfg_full["strategy"]["lookback_months"] = best_full["lookback"]
    cfg_full["strategy"]["target_volatility"] = best_full["target_vol"]
    cfg_cur = deepcopy(config)
    cfg_cur["strategy"]["lookback_months"] = best_cur["lookback"]
    cfg_cur["strategy"]["target_volatility"] = best_cur["target_vol"]
    full_B = run_universe(returns_full, cfg_full, "full")
    cur_B = run_universe(returns_cur, cfg_cur, "curado")
    print_block(
        f"(B) CADA UNO EN SU ÓPTIMO  ·  full LB={best_full['lookback']}m/TV={best_full['target_vol']*100:.0f}%  "
        f"vs  curado LB={best_cur['lookback']}m/TV={best_cur['target_vol']*100:.0f}%",
        full_B, cur_B)

    print("\nNota: rf=0 · costos = spread+comisión del config · 'Pos.activas~' = nº medio de posiciones/mes.")


if __name__ == "__main__":
    main()
