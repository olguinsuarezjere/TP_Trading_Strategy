import asyncio
import time

import pandas as pd

# ib_insync/eventkit llaman a asyncio.get_event_loop() AL IMPORTARSE. En un hilo que
# no es el principal (p.ej. el ScriptRunner de Streamlit) puede no haber event loop y
# eso explota con RuntimeError. Garantizamos uno antes de importar ib_insync.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock, util  # noqa: E402


class IBKRConnection:
    """
    Wrapper sobre ib_insync para conectarse a TWS Paper Trading.

    Uso:
        conn = IBKRConnection()
        conn.connect()
        positions = conn.get_positions()
        conn.disconnect()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    def connect(self) -> None:
        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
        except Exception as e:
            raise ConnectionError(
                f"No se pudo conectar a TWS en {self.host}:{self.port}. "
                f"Asegurate de que TWS o IB Gateway esté corriendo. Error: {e}"
            )
        self._verify_connection()

    def _verify_connection(self) -> None:
        if not self.ib.isConnected():
            raise ConnectionError("Conexión fallida: TWS no respondió.")
        accounts = self.ib.managedAccounts()
        server_v = self.ib.client.serverVersion()
        print(f"[OK] Conectado a IBKR TWS en {self.host}:{self.port}")
        print(f"     Cuenta(s)  : {', '.join(accounts)}")
        print(f"     Servidor   : v{server_v}")
        # Datos diferidos (tipo 3) — disponibles sin suscripción en cuentas paper
        self.ib.reqMarketDataType(3)

    def disconnect(self) -> None:
        if self.ib.isConnected():
            self.ib.disconnect()
            print("Desconectado de IBKR TWS")

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    def get_connection_info(self) -> dict:
        """Info de la conexión para el panel de estado: cuenta(s), versión de servidor."""
        accounts = list(self.ib.managedAccounts())
        return {
            "connected":      self.ib.isConnected(),
            "accounts":       accounts,
            "account":        accounts[0] if accounts else "—",
            "server_version": self.ib.client.serverVersion() if self.ib.isConnected() else None,
            "host":           self.host,
            "port":           self.port,
        }

    def get_account_summary(self) -> dict:
        """Retorna valores clave de la cuenta: cash, net liquidation, unrealized PnL."""
        summary = self.ib.accountSummary()
        result = {}
        for item in summary:
            if item.tag in ("NetLiquidation", "TotalCashValue", "UnrealizedPnL", "RealizedPnL"):
                result[item.tag] = float(item.value)
        return result

    def get_positions(self) -> pd.DataFrame:
        """Retorna las posiciones actuales como DataFrame, agregadas por ticker."""
        positions = self.ib.positions()
        if not positions:
            return pd.DataFrame(columns=["ticker", "qty", "avg_cost", "market_price", "market_value"])

        # Agregar por ticker (TWS puede reportar múltiples lotes por símbolo)
        aggregated: dict[str, dict] = {}
        for pos in positions:
            ticker = pos.contract.symbol
            if ticker not in aggregated:
                aggregated[ticker] = {"qty": 0.0, "cost_basis": 0.0, "contract": pos.contract}
            aggregated[ticker]["qty"] += pos.position
            aggregated[ticker]["cost_basis"] += pos.position * pos.avgCost

        rows = []
        for ticker, data in aggregated.items():
            qty = data["qty"]
            avg_cost = data["cost_basis"] / qty if qty != 0 else 0.0
            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            ticker_data = self.ib.reqMktData(contract, "", False, False)
            self.ib.sleep(1.0)
            price = ticker_data.last if ticker_data.last and ticker_data.last > 0 else avg_cost
            rows.append({
                "ticker":       ticker,
                "qty":          qty,
                "avg_cost":     avg_cost,
                "market_price": price,
                "market_value": qty * price,
            })
        return pd.DataFrame(rows)

    def validate_tradeable(
        self,
        tickers: list[str],
        exchange: str = "SMART",
        currency: str = "USD",
        pause: float = 0.05,
    ) -> dict[str, tuple[bool, str]]:
        """
        Verifica qué tickers son operables en IBKR vía SMART routing en USD.

        Para cada ticker pide la definición de contrato (reqContractDetails). Si
        IBKR devuelve al menos una definición -> operable. Si no -> no operable
        (delisted, no disponible en la cuenta, o símbolo inexistente).

        Devuelve {ticker: (operable, detalle)}.
        """
        results: dict[str, tuple[bool, str]] = {}
        for t in tickers:
            contract = Stock(t, exchange, currency)
            try:
                details = self.ib.reqContractDetails(contract)
            except Exception as e:
                results[t] = (False, f"error: {e}")
                self.ib.sleep(pause)
                continue
            if not details:
                results[t] = (False, "sin definición de contrato en IBKR")
            else:
                d = details[0]
                primary = d.contract.primaryExchange or exchange
                name = (d.longName or "").strip()
                results[t] = (True, f"{primary}{' · ' + name if name else ''}")
            self.ib.sleep(pause)
        return results

    def get_market_price(self, ticker: str) -> float:
        """Último precio de mercado para un ticker. Devuelve 0.0 si no hay dato válido.

        Ojo: `nan or x` devuelve nan (nan es truthy), por eso filtramos NaN/<=0
        explícitamente en vez de usar `last or close or 0`."""
        contract = Stock(ticker, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker_data = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(0.5)
        for p in (ticker_data.last, ticker_data.close):
            if p is not None and p == p and p > 0:  # p == p excluye NaN
                return float(p)
        return 0.0

    def get_positions_simple(self) -> pd.DataFrame:
        """Posiciones (ticker, qty, avg_cost) SIN pedir market data — rápido.

        Útil para el corte/flatten, donde solo importa cuánto hay que cerrar.
        Agrega por símbolo por si TWS reporta varios lotes.
        """
        agg: dict[str, dict] = {}
        for pos in self.ib.positions():
            sym = pos.contract.symbol
            d = agg.setdefault(sym, {"qty": 0.0, "cost_basis": 0.0})
            d["qty"] += pos.position
            d["cost_basis"] += pos.position * pos.avgCost
        rows = [
            {"ticker": s, "qty": d["qty"],
             "avg_cost": (d["cost_basis"] / d["qty"]) if d["qty"] else 0.0}
            for s, d in agg.items()
        ]
        return pd.DataFrame(rows, columns=["ticker", "qty", "avg_cost"])

    def get_portfolio_fast(self, settle: float = 2.0) -> pd.DataFrame:
        """Portafolio completo (precio, valor de mercado, P&L) en UNA sola llamada.

        Usa `ib.portfolio()` (viene del stream de actualizaciones de cuenta de TWS),
        en vez de pedir `reqMktData` ticker por ticker con pausa. Para 100+ posiciones
        esto pasa de ~minutos a ~2 segundos. TWS calcula el marketPrice (datos
        demorados si no hay suscripción en tiempo real)."""
        self.ib.reqAccountUpdates()
        self.ib.sleep(settle)
        rows = []
        for it in self.ib.portfolio():
            if abs(it.position) < 1e-9:
                continue
            rows.append({
                "ticker":         it.contract.symbol,
                "sec_type":       it.contract.secType,
                "qty":            it.position,
                "avg_cost":       it.averageCost,
                "market_price":   it.marketPrice,
                "market_value":   it.marketValue,
                "unrealized_pnl": it.unrealizedPNL,
            })
        return pd.DataFrame(rows, columns=[
            "ticker", "sec_type", "qty", "avg_cost", "market_price",
            "market_value", "unrealized_pnl"])

    def get_raw_positions(self, settle: float = 3.0) -> list:
        """Posiciones abiertas con su CONTRATO EXACTO (conId, secType), SIN agregar
        por símbolo.

        Clave para el kill switch: un mismo símbolo puede tener varios instrumentos
        (p.ej. la acción OPEN y warrants de OPEN). Agregar por símbolo y reconstruir
        un Stock haría operar el instrumento equivocado. Acá devolvemos el contrato
        real de cada lote.

        Pide reqPositions y espera `settle` segundos porque ib.positions() puede venir
        incompleto justo después de conectar.
        """
        self.ib.reqPositions()
        self.ib.sleep(settle)
        out = []
        for p in self.ib.positions():
            if abs(p.position) < 1e-9:
                continue
            out.append({
                "contract": p.contract,
                "symbol":   p.contract.symbol,
                "secType":  p.contract.secType,
                "qty":      p.position,
                "avg_cost": p.avgCost,
            })
        return out

    def get_open_orders(self) -> pd.DataFrame:
        """Órdenes abiertas (pendientes) en la cuenta."""
        rows = []
        for t in self.ib.openTrades():
            rows.append({
                "order_id": t.order.orderId,
                "ticker":   t.contract.symbol,
                "action":   t.order.action,
                "qty":      t.order.totalQuantity,
                "type":     t.order.orderType,
                "status":   t.orderStatus.status,
            })
        return pd.DataFrame(rows, columns=["order_id", "ticker", "action", "qty", "type", "status"])

    def cancel_all_orders(self) -> None:
        """Cancela todas las órdenes abiertas (global cancel)."""
        self.ib.reqGlobalCancel()
        self.ib.sleep(1)
