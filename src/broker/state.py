"""
Estado persistente de la estrategia — el "cerebro" que sobrevive a cerrar el dashboard.

El dashboard es solo una VENTANA. Las posiciones reales viven en IBKR; acá guardamos
la INTENCIÓN de la estrategia: si está corriendo, con qué parámetros, y cuándo
rebalanceó por última vez. Así, cuando el usuario reconecta al día siguiente, el
sistema sabe en qué estado quedó todo y puede reconciliar (catch-up).

Máquina de estados (logs/strategy_state.json):

    DETENIDA  --start_strategy()-->  ACTIVA  <--resume()-- PAUSADA
       ^                              |  ^                    ^
       |                          pause()  \--resume()       /
       +-- stop() (kill switch) <----------+----------------+

  - "stopped"  : no enrolada. Estado inicial / después de cerrar todo (kill).
  - "running"  : enrolada y operando (rebalanceos mensuales habilitados).
  - "paused"   : enrolada pero NO opera; mantiene posiciones. (= halted legacy)

Rebalanceo MENSUAL puro: rebalance_due() devuelve True solo si la estrategia está
ACTIVA y todavía no se rebalanceó en el mes calendario actual. El "chequeo" puede
correr cada pocos segundos (es gratis e idempotente); la EJECUCIÓN ocurre una vez
por mes, cuando cambia el mes.
"""
import json
from datetime import date, datetime
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parents[2] / "logs" / "strategy_state.json"

_DEFAULT = {
    "status": "stopped",        # stopped | running | paused
    "enrolled_at": None,        # ISO timestamp en que se inició la estrategia
    "params": {},               # {signal_mode, lookback, target_vol, weighting}
    "last_rebalance_at": None,  # "YYYY-MM-DD" del último rebalanceo ejecutado
    "last_rebalance_id": None,  # id del último rebalanceo (para cruzar con los logs)
    # --- campos legacy (compatibilidad con código existente) ---
    "halted": False,            # True cuando status == "paused"
    "halted_at": None,
    "reason": None,
    "resumed_at": None,
}


def _read() -> dict:
    if STATE_PATH.exists():
        try:
            return {**_DEFAULT, **json.loads(STATE_PATH.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT)


def _write(state: dict) -> dict:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return state


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ lectura

def get_state() -> dict:
    return _read()


def status() -> str:
    return _read().get("status", "stopped")


def is_running() -> bool:
    return status() == "running"


def is_paused() -> bool:
    return status() == "paused"


def is_stopped() -> bool:
    return status() == "stopped"


def is_halted() -> bool:
    """Bloquea la ejecución de rebalanceos. True cuando la estrategia está PAUSADA.

    (Cuando está DETENIDA el usuario todavía puede ejecutar un rebalanceo manual;
    solo PAUSADA bloquea explícitamente, equivalente al viejo 'halt'.)
    """
    return is_paused()


# --------------------------------------------------------------- transiciones

def start_strategy(params: dict | None = None) -> dict:
    """Enrola la estrategia: pasa a ACTIVA y registra params + momento de inicio."""
    st = _read()
    st.update({
        "status": "running",
        "enrolled_at": _now(),
        "params": params or st.get("params", {}),
        # Enrolar de cero resetea el reloj de rebalanceo: el primero queda pendiente.
        "last_rebalance_at": None,
        "last_rebalance_id": None,
        "halted": False,
        "halted_at": None,
        "reason": None,
        "resumed_at": None,
    })
    return _write(st)


def pause(reason: str = "pausa manual") -> dict:
    """Pausa la estrategia: deja de operar pero mantiene posiciones y enrolamiento."""
    st = _read()
    st.update({
        "status": "paused",
        "halted": True,
        "halted_at": _now(),
        "reason": reason,
        "resumed_at": None,
    })
    return _write(st)


def resume() -> dict:
    """Reanuda la estrategia pausada: vuelve a ACTIVA."""
    st = _read()
    st.update({
        "status": "running",
        "halted": False,
        "resumed_at": _now(),
    })
    return _write(st)


def stop(reason: str = "detenida (kill switch)") -> dict:
    """Detiene y desenrola la estrategia (tras cerrar posiciones con el kill switch)."""
    st = _read()
    st.update({
        "status": "stopped",
        "halted": False,
        "reason": reason,
        "resumed_at": None,
    })
    return _write(st)


# alias legacy: el código viejo llamaba halt() para el kill/pausa.
halt = pause


def record_rebalance(rebalance_id: str, when: date | datetime | str | None = None) -> dict:
    """Marca que se ejecutó un rebalanceo (para el guard mensual y el catch-up)."""
    if when is None:
        when = date.today()
    if isinstance(when, datetime):
        when = when.date()
    if isinstance(when, date):
        when = when.isoformat()
    st = _read()
    st.update({"last_rebalance_at": when, "last_rebalance_id": rebalance_id})
    return _write(st)


# ----------------------------------------------------------- calendario mensual

def _month_key(d: date) -> tuple[int, int]:
    return (d.year, d.month)


def last_rebalance_date() -> date | None:
    raw = _read().get("last_rebalance_at")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None


def rebalance_due(today: date | None = None) -> bool:
    """True solo si la estrategia está ACTIVA y aún NO se rebalanceó este mes."""
    if not is_running():
        return False
    today = today or date.today()
    last = last_rebalance_date()
    if last is None:
        return True
    return _month_key(last) < _month_key(today)


def next_rebalance_date(today: date | None = None) -> date:
    """Fecha del próximo rebalanceo programado (primer día del mes correspondiente)."""
    today = today or date.today()
    last = last_rebalance_date()
    # Si nunca rebalanceó o ya pasó el mes, toca este mes (primero del mes actual).
    if last is None or _month_key(last) < _month_key(today):
        return date(today.year, today.month, 1)
    # Ya rebalanceó este mes -> el próximo es el primero del mes siguiente.
    year, month = today.year, today.month + 1
    if month > 12:
        year, month = year + 1, 1
    return date(year, month, 1)
