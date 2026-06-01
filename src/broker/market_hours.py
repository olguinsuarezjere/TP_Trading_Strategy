"""
Estado del mercado US en tiempo real (para el panel del dashboard).

Todos los ETFs del universo cotizan en bolsas de EE.UU. (NYSE / NASDAQ / ARCA /
BATS), así que comparten el mismo horario:

  - Sesión REGULAR : 09:30 - 16:00 ET  (lun-vie)  -> market orders confiables.
  - Pre-market      : 04:00 - 09:30 ET  (extendido)
  - After-hours     : 16:00 - 20:00 ET  (extendido) -> market orders POCO confiables.
  - Resto / fin de semana: CERRADO.

Se calcula con la hora de Nueva York (maneja DST automáticamente vía zoneinfo), sin
depender de IBKR. No contempla feriados del NYSE (un día feriado se mostrará como
abierto si cae en día hábil; para la demo alcanza, y se aclara en el panel).
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

REG_OPEN, REG_CLOSE = time(9, 30), time(16, 0)
PRE_OPEN, AFT_CLOSE = time(4, 0), time(20, 0)


def _next_weekday_open(dt_et: datetime) -> datetime:
    """Próxima apertura de sesión regular (09:30 ET de un día hábil) desde dt_et."""
    candidate = dt_et
    # Si hoy es hábil y aún no abrió, es hoy 09:30; si no, avanzar de día.
    if candidate.weekday() < 5 and candidate.time() < REG_OPEN:
        return candidate.replace(hour=9, minute=30, second=0, microsecond=0)
    candidate = candidate + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.replace(hour=9, minute=30, second=0, microsecond=0)


def us_market_status(now_utc: datetime | None = None) -> dict:
    """Devuelve el estado del mercado US ahora.

    Claves: status (regular|pre|after|closed), label, detail, color, can_trade
    (bool: ¿market orders confiables?), now_et, regular_local, extended_local,
    next_open_local.
    """
    now = now_utc or datetime.now(tz=ZoneInfo("UTC"))
    now_et = now.astimezone(ET)
    wd = now_et.weekday()
    t = now_et.time()
    weekday = wd < 5

    if not weekday:
        status, detail, color, can_trade = "closed", "Fin de semana — mercado cerrado", "#d65f5f", False
    elif REG_OPEN <= t < REG_CLOSE:
        status, detail, color, can_trade = "regular", "Sesión regular — operación normal", "#3fb950", True
    elif PRE_OPEN <= t < REG_OPEN:
        status, detail, color, can_trade = "pre", "Pre-market (extendido)", "#e0a23b", False
    elif REG_CLOSE <= t < AFT_CLOSE:
        status, detail, color, can_trade = "after", "After-hours (extendido)", "#e0a23b", False
    else:
        status, detail, color, can_trade = "closed", "Fuera de horario — mercado cerrado", "#d65f5f", False

    label = {"regular": "● MERCADO ABIERTO", "pre": "◐ PRE-MARKET",
             "after": "◐ AFTER-HOURS", "closed": "○ MERCADO CERRADO"}[status]

    # Equivalentes en hora local (de la máquina) para que el usuario los lea fácil.
    def _local_hhmm(hh, mm):
        ref = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0)
        return ref.astimezone().strftime("%H:%M")

    return {
        "status": status,
        "label": label,
        "detail": detail,
        "color": color,
        "can_trade": can_trade,
        "now_et": now_et.strftime("%H:%M:%S ET · %a %d-%b"),
        "now_local": now.astimezone().strftime("%H:%M:%S"),
        "regular_et": "09:30 – 16:00 ET",
        "regular_local": f"{_local_hhmm(9, 30)} – {_local_hhmm(16, 0)} (tu hora)",
        "extended_et": "04:00 – 20:00 ET",
        "extended_local": f"{_local_hhmm(4, 0)} – {_local_hhmm(20, 0)} (tu hora)",
        "next_open_local": _next_weekday_open(now_et).astimezone().strftime("%a %d-%b %H:%M"),
    }
