import pandas as pd
import numpy as np

from ..data.universe import ETF_UNIVERSE


def compute_vol_scaled_weights(
    signal: pd.DataFrame,
    vol: pd.DataFrame,
    target_vol: float = 0.10,
) -> pd.DataFrame:
    """
    Volatility-scaled position weights (Moskowitz et al. 2012).

    w_{i,t} = signal_{i,t} * (target_vol / vol_{i,t}) / N_active
    Each active asset contributes equally to portfolio risk.
    """
    active = signal.notna() & vol.notna() & (vol > 0)
    n_active = active.sum(axis=1).replace(0, np.nan)

    raw = signal * (target_vol / vol.replace(0, np.nan))
    weights = raw.div(n_active, axis=0)
    return weights.where(active, 0.0)


def compute_classbalanced_weights(
    signal: pd.DataFrame,
    vol: pd.DataFrame,
    target_vol: float = 0.10,
    asset_class: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    Pesos con presupuesto de riesgo IGUAL por clase de activo.

    El universo de ETFs está muy sesgado a equities (correlación intra-equity ~0.87),
    así que el esquema 1/N_global hace que las acciones dominen el riesgo del portafolio
    (~88% de la varianza). Repartir el presupuesto en partes iguales entre equity / bond
    / commodity / currency replica la diversificación que el TSMOM clásico obtiene del
    universo balanceado de FUTUROS (Moskowitz et al. 2012), y sube el Sharpe.

        w_{i,t} = signal_{i,t} * (target_vol / vol_{i,t}) / (N_activos_en_su_clase * N_clases_activas)
    """
    asset_class = asset_class or ETF_UNIVERSE
    active = signal.notna() & vol.notna() & (vol > 0)
    raw = (signal * (target_vol / vol.replace(0, np.nan))).where(active, 0.0)

    classes: dict[str, list[str]] = {}
    for col in raw.columns:
        classes.setdefault(asset_class.get(col, "other"), []).append(col)

    counts = {c: active[ts].sum(axis=1) for c, ts in classes.items()}
    n_classes_active = sum((counts[c] > 0).astype(int) for c in classes)

    out = pd.DataFrame(0.0, index=raw.index, columns=raw.columns)
    for c, ts in classes.items():
        denom = counts[c].replace(0, np.nan) * n_classes_active.replace(0, np.nan)
        out[ts] = raw[ts].div(denom, axis=0)
    return out.fillna(0.0)


def apply_position_constraints(weights: pd.DataFrame, max_weight: float = 0.15) -> pd.DataFrame:
    """Clip each individual position to [-max_weight, max_weight]."""
    return weights.clip(-max_weight, max_weight)


def _build_signal(returns: pd.DataFrame, config: dict, use_signal_strength: bool) -> pd.DataFrame:
    """Selecciona la señal según config['strategy']['signal_mode'] (con fallback legacy)."""
    from .signals import (
        compute_tsmom_signal, compute_signal_strength, compute_multihorizon_signal,
    )
    strat = config["strategy"]
    mode = strat.get("signal_mode")
    if mode is None:  # compatibilidad con el toggle viejo binary/strength
        mode = "strength" if use_signal_strength else "binary"

    if mode == "multihorizon":
        lookbacks = tuple(strat.get("lookbacks", [3, 6, 12]))
        return compute_multihorizon_signal(returns, lookbacks=lookbacks)
    if mode == "strength":
        return compute_signal_strength(returns, lookback=strat["lookback_months"])
    return compute_tsmom_signal(returns, lookback=strat["lookback_months"])


def build_portfolio(
    returns: pd.DataFrame,
    config: dict,
    use_signal_strength: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Full portfolio construction pipeline.

    Returns (weights, signal) DataFrames aligned to returns index.
    """
    from .volatility import compute_ex_ante_vol
    from .signals import compute_crash_filter

    strat = config["strategy"]
    vol = compute_ex_ante_vol(returns, com_months=strat["vol_com_months"])

    signal = _build_signal(returns, config, use_signal_strength)

    # Daniel & Moskowitz (2016): crash regime filter
    if strat.get("use_crash_filter", False):
        crash_multiplier = compute_crash_filter(returns)
        signal = signal.mul(crash_multiplier, axis=0)

    # Esquema de ponderación: 1/N global (clásico) o presupuesto igual por clase
    if strat.get("weighting", "pooled") == "class_balanced":
        weights = compute_classbalanced_weights(signal, vol, target_vol=strat["target_volatility"])
    else:
        weights = compute_vol_scaled_weights(signal, vol, target_vol=strat["target_volatility"])

    weights = apply_position_constraints(weights, max_weight=strat["max_position_weight"])
    return weights, signal
