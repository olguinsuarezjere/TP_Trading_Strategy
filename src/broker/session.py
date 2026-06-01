"""
Manejo de sesión con IBKR TWS.

Usa un client_id distinto por propósito para evitar choques en TWS (TWS rechaza
dos conexiones con el mismo clientId), y garantiza la desconexión con un context
manager:

    from src.broker.session import ibkr_session
    with ibkr_session(config, "monitor") as conn:
        account = conn.get_account_summary()
"""
from contextlib import contextmanager

from .ibkr import IBKRConnection

# Un id por propósito para que monitoreo / rebalanceo / corte no choquen entre sí.
CLIENT_IDS = {
    "monitor":   11,
    "rebalance": 12,
    "kill":      13,
    "validate":  14,
    "status":    15,
    "default":   19,
}


@contextmanager
def ibkr_session(config: dict, purpose: str = "default"):
    broker = config["broker"]
    client_id = CLIENT_IDS.get(purpose, broker.get("client_id", 1))
    conn = IBKRConnection(broker["host"], broker["port"], client_id)
    try:
        conn.connect()
        yield conn
    finally:
        conn.disconnect()
