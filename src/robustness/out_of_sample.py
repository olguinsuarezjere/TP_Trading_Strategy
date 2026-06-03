import pandas as pd
import numpy as np
from copy import deepcopy

from ..backtest.engine import BacktestEngine
from ..backtest.metrics import sharpe_ratio, annualized_return, max_drawdown
from .sensitivity import optimize_sharpe

# Grillas por defecto para la RE-OPTIMIZACIÓN out-of-sample. Más gruesas que las del
# óptimo in-sample del dashboard (paso 1m / 1%) a propósito: acá optimize_sharpe se
# llama una vez POR VENTANA, así que una grilla fina multiplicaría el costo por el
# nº de ventanas sin cambiar la conclusión (lo que importa es la degradación IS→OOS,
# no clavar el parámetro exacto). Igual cubren todo el rango operable.
_WF_LOOKBACKS = [3, 6, 9, 12, 15, 18, 21, 24]
_WF_TARGET_VOLS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]


def walk_forward(
    returns: pd.DataFrame,
    config: dict,
    train_years: int = 5,
    test_years: int = 1,
    reoptimize: bool = True,
    lookbacks: list[int] | None = None,
    target_vols: list[float] | None = None,
) -> pd.DataFrame:
    """
    Walk-forward OUT-OF-SAMPLE **anclado** (expanding train).

    En cada ventana:
      1. Con TODOS los datos hasta `train_end` se RE-OPTIMIZAN los parámetros
         (lookback, target_vol) maximizando el Sharpe in-sample (`optimize_sharpe`).
      2. Con ESOS parámetros se mide la performance del año siguiente (`test`), que
         el optimizador **nunca vio**.

    Así el test es genuinamente out-of-sample en la **selección de parámetros**, no
    solo en las señales (que ya son causales por el `shift(1)`). La columna
    `lookback`/`target_vol` muestra cómo migra el óptimo ventana a ventana: si salta
    mucho, es señal de sobreajuste del parámetro (y justo eso es lo que el test honesto
    debe exponer).

    Con `reoptimize=False` cae al comportamiento viejo (parámetros fijos del config),
    útil solo para comparar contra la versión ingenua.
    """
    lookbacks = lookbacks or _WF_LOOKBACKS
    target_vols = target_vols or _WF_TARGET_VOLS
    train_months = train_years * 12
    test_months = test_years * 12
    rows = []

    start_idx = train_months
    while start_idx + test_months <= len(returns):
        train = returns.iloc[:start_idx]                       # train ANCLADO (expanding)

        if reoptimize:
            best, _ = optimize_sharpe(train, config, lookbacks=lookbacks, target_vols=target_vols)
            cfg = deepcopy(config)
            cfg["strategy"]["lookback_months"] = best["lookback"]
            cfg["strategy"]["target_volatility"] = best["target_vol"]
        else:
            cfg = config
            best = {"lookback": config["strategy"]["lookback_months"],
                    "target_vol": config["strategy"]["target_volatility"]}

        # Corremos sobre train+test para que las señales del test tengan TODO su
        # historial causal; después nos quedamos solo con los meses de test. El
        # trim de warm-up del motor es por delante, así que los últimos `test_months`
        # del backtest activo == el período de test calendario.
        combined = returns.iloc[:start_idx + test_months]
        res = BacktestEngine(cfg).run(combined)
        test_returns = res.portfolio_returns.iloc[-test_months:]

        rows.append({
            "train_end":  train.index[-1].strftime("%Y-%m"),
            "test_start": returns.index[start_idx].strftime("%Y-%m"),
            "test_end":   returns.index[start_idx + test_months - 1].strftime("%Y-%m"),
            "lookback":   int(best["lookback"]),
            "target_vol": float(best["target_vol"]),
            "sharpe":     sharpe_ratio(test_returns),
            "ann_ret":    annualized_return(test_returns),
            "max_dd":     max_drawdown(test_returns),
        })
        start_idx += test_months

    return pd.DataFrame(rows)


def out_of_sample_split(
    returns: pd.DataFrame,
    config: dict,
    split_frac: float = 0.6,
    lookbacks: list[int] | None = None,
    target_vols: list[float] | None = None,
) -> pd.DataFrame:
    """
    Validación OOS **honesta** por corte temporal único.

    Optimiza (lookback, target_vol) usando SOLO la primera fracción `split_frac` de
    los datos (in-sample) y, con esos parámetros fijos, mide la performance en el
    resto (out-of-sample) — datos que el optimizador nunca vio.

    A diferencia de la versión vieja (que optimizaba sobre TODA la muestra y después
    la partía, contaminando el OOS), acá el OOS es limpio: la caída de Sharpe IS→OOS
    es el costo real de no conocer el futuro. Devuelve un resumen con los parámetros
    elegidos y la fecha de corte en `.attrs`.
    """
    lookbacks = lookbacks or _WF_LOOKBACKS
    target_vols = target_vols or _WF_TARGET_VOLS

    split_idx = int(len(returns) * split_frac)
    split_date = returns.index[split_idx]
    in_sample = returns.iloc[:split_idx]

    best, _ = optimize_sharpe(in_sample, config, lookbacks=lookbacks, target_vols=target_vols)
    cfg = deepcopy(config)
    cfg["strategy"]["lookback_months"] = best["lookback"]
    cfg["strategy"]["target_volatility"] = best["target_vol"]

    res = BacktestEngine(cfg).run(returns)          # mismos parámetros, toda la serie
    pr = res.portfolio_returns
    is_r = pr.loc[:split_date]
    oos_r = pr.loc[split_date:].iloc[1:]            # excluye el mes de corte (ya está en IS)

    summary = pd.DataFrame({
        "Period":  ["In-Sample", "Out-of-Sample", "Full"],
        "Sharpe":  [sharpe_ratio(is_r), sharpe_ratio(oos_r), sharpe_ratio(pr)],
        "Ann Ret": [annualized_return(is_r), annualized_return(oos_r), annualized_return(pr)],
        "Max DD":  [max_drawdown(is_r), max_drawdown(oos_r), max_drawdown(pr)],
        "Months":  [len(is_r), len(oos_r), len(pr)],
    }).set_index("Period")
    summary.attrs["params"] = {"lookback": int(best["lookback"]), "target_vol": float(best["target_vol"])}
    summary.attrs["split_date"] = split_date.strftime("%Y-%m")
    return summary


def expanding_window(returns: pd.DataFrame, config: dict, min_train_months: int = 36) -> pd.DataFrame:
    """[DEPRECADO] Partía la muestra IS/OOS pero con parámetros optimizados sobre TODA
    la serie, así que el 'OOS' estaba contaminado (el optimizador ya había visto ese
    tramo). Se mantiene solo por compatibilidad; usar `out_of_sample_split`, que
    re-optimiza únicamente con el in-sample."""
    return out_of_sample_split(returns, config)
