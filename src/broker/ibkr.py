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
        self.ib.connect(self.host, self.port, clientId=self.client_id)
        print(f"Conectado a IBKR TWS en {self.host}:{self.port}")

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
        """Retorna las posiciones actuales como DataFrame."""
        positions = self.ib.positions()
        if not positions:
            return pd.DataFrame(columns=["ticker", "qty", "avg_cost", "market_value"])

        rows = []
        for pos in positions:
            ticker = pos.contract.symbol
            qty = pos.position
            avg_cost = pos.avgCost
            # Solicitar precio de mercado
            contract = Stock(ticker, "SMART", "USD")
            self.ib.qualifyContracts(contract)
            ticker_data = self.ib.reqMktData(contract, "", False, False)
            self.ib.sleep(0.5)
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
