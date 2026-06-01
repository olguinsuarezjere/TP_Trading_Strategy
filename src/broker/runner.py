"""
Runner de la estrategia en vivo — la lógica de "tick" (el termostato).

Separa CHEQUEAR de EJECUTAR:
  - check_rebalance(): mira si toca rebalancear (gratis, idempotente, corre seguido).
  - run_tick(): si toca (o si se fuerza), ejecuta el rebalanceo mensual y lo registra.

Es agnóstico del dashboard (no importa Streamlit), así que el mismo código sirve
para el botón "Forzar chequeo" del dashboard, el catch-up al reconectar, y —a futuro—
un cron que llame a `python main.py tick` aunque la app esté cerrada (Opción B).
"""
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from . import state
from .ibkr import IBKRConnection
from .orders import execute_rebalance


@dataclass
class RebalanceCheck:
    """Resultado de chequear si toca rebalancear (sin ejecutar nada)."""
    status: str                      # stopped | running | paused
    due: bool                        # ¿hay un rebalanceo pendiente este mes?
    last_rebalance_at: str | None
    next_rebalance_date: str
    reason: str                      # explicación legible del estado

    @property
    def is_running(self) -> bool:
        return self.status == "running"


def compute_target_weights(returns: pd.DataFrame, config: dict) -> pd.Series:
    """Pesos objetivo del próximo rebalanceo.

    Usa build_scaled_weights (la MISMA función que el backtest), así en IBKR se
    operan exactamente los pesos validados —incluyendo el portfolio vol scaling de
    Moreira-Muir— y no los pesos crudos de build_portfolio."""
    from ..backtest.engine import build_scaled_weights
    weights_df, _ = build_scaled_weights(returns, config)
    target = weights_df.iloc[-1].dropna()
    return target[target != 0]


def check_rebalance(today: date | None = None) -> RebalanceCheck:
    """Chequea (sin operar) si corresponde rebalancear. Es el 'mirar' del termostato."""
    today = today or date.today()
    st = state.get_state()
    status = st.get("status", "stopped")
    last = st.get("last_rebalance_at")
    nxt = state.next_rebalance_date(today)
    due = state.rebalance_due(today)

    if status == "stopped":
        reason = "Estrategia detenida — no enrolada."
    elif status == "paused":
        reason = "Estrategia pausada — no opera hasta reanudar."
    elif due:
        reason = (f"Rebalanceo pendiente: empezó un mes nuevo y todavía no se "
                  f"rebalanceó (último: {last or 'nunca'}).")
    else:
        reason = f"Al día — ya se rebalanceó este mes. Próximo: {nxt.isoformat()}."

    return RebalanceCheck(
        status=status, due=due, last_rebalance_at=last,
        next_rebalance_date=nxt.isoformat(), reason=reason,
    )


@dataclass
class TickResult:
    """Resultado de correr un tick (haya ejecutado o no)."""
    executed: bool
    orders: list = field(default_factory=list)
    rebalance_id: str | None = None
    message: str = ""


def run_tick(
    conn: IBKRConnection,
    returns: pd.DataFrame,
    config: dict,
    capital: float,
    force: bool = False,
    trigger: str = "auto",
    today: date | None = None,
) -> TickResult:
    """
    Corre un tick: si toca rebalancear (o force=True), ejecuta y registra.

    - force=True  -> ejecuta aunque no haya cambio de mes (para el botón de demo
                     "Forzar chequeo ahora" y el catch-up con confirmación).
    - Respeta el kill switch / pausa: si está pausada, no opera.
    """
    today = today or date.today()
    chk = check_rebalance(today)

    if state.is_paused():
        return TickResult(False, message="Estrategia PAUSADA: no se ejecuta.")
    if not state.is_running() and not force:
        return TickResult(False, message="Estrategia no activa: nada que hacer.")
    if not chk.due and not force:
        return TickResult(False, message=chk.reason)

    target = compute_target_weights(returns, config)
    params = {
        "signal_mode": config["strategy"].get("signal_mode"),
        "lookback": config["strategy"].get("lookback_months"),
        "target_vol": config["strategy"].get("target_volatility"),
    }
    orders = execute_rebalance(conn, target, capital=capital, dry_run=False,
                               trigger=trigger, params=params)
    # execute_rebalance ya registró el rebalanceo en el estado (state.record_rebalance).
    rid = state.get_state().get("last_rebalance_id")
    return TickResult(True, orders=orders, rebalance_id=rid,
                      message=f"Rebalanceo ejecutado ({len(orders)} órdenes).")
