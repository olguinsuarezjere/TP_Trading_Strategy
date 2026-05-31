import time
import pandas as pd
from ib_insync import IB, Stock, util


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

    def get_market_price(self, ticker: str) -> float:
        """Solicita el último precio de mercado para un ticker."""
        contract = Stock(ticker, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        ticker_data = self.ib.reqMktData(contract, "", False, False)
        self.ib.sleep(0.5)
        price = ticker_data.last or ticker_data.close or 0.0
        return float(price)
