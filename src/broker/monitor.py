import time
import pandas as pd
from datetime import datetime

from .ibkr import IBKRConnection


def get_live_portfolio(conn: IBKRConnection) -> pd.DataFrame:
    """
    Retorna el portafolio actual con posiciones, valores y P&L.

    Usa la vía rápida (`get_portfolio_fast`, una sola llamada vía stream de cuenta)
    en vez de pedir precio ticker por ticker — clave con muchas posiciones.
    """
    positions_df = conn.get_portfolio_fast()
    if positions_df.empty:
        return positions_df

    summary = conn.get_account_summary()
    net_liq = summary.get("NetLiquidation", 1.0) or 1.0

    positions_df["weight"] = positions_df["market_value"] / net_liq
    return positions_df


def compute_live_pnl(portfolio_df: pd.DataFrame) -> dict:
    """Agrega P&L total del portafolio."""
    if portfolio_df.empty:
        return {"total_market_value": 0.0, "total_unrealized_pnl": 0.0}
    return {
        "total_market_value":   float(portfolio_df["market_value"].sum()),
        "total_unrealized_pnl": float(portfolio_df["unrealized_pnl"].sum()),
        "n_positions":          int(len(portfolio_df)),
        "n_long":               int((portfolio_df["qty"] > 0).sum()),
        "n_short":              int((portfolio_df["qty"] < 0).sum()),
    }


def print_portfolio_table(portfolio_df: pd.DataFrame, account: dict) -> None:
    """Imprime el portafolio en formato tabla."""
    print(f"\n{'-'*65}")
    print(f"  Portfolio Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'-'*65}")
    print(f"  Net Liquidation:  ${account.get('NetLiquidation', 0):>12,.2f}")
    print(f"  Cash:             ${account.get('TotalCashValue', 0):>12,.2f}")
    print(f"  Unrealized P&L:   ${account.get('UnrealizedPnL', 0):>12,.2f}")
    print(f"{'-'*65}")

    if portfolio_df.empty:
        print("  Sin posiciones abiertas.")
    else:
        header = f"  {'Ticker':<8} {'Qty':>8} {'Price':>10} {'MktVal':>12} {'Weight':>8} {'UnrPnL':>12}"
        print(header)
        print(f"  {'-'*61}")
        for _, row in portfolio_df.iterrows():
            print(f"  {row['ticker']:<8} {row['qty']:>8.0f} {row['market_price']:>10.2f} "
                  f"{row['market_value']:>12,.0f} {row['weight']:>7.1%} "
                  f"{row['unrealized_pnl']:>12,.0f}")
    print(f"{'-'*65}\n")


def stream_portfolio_updates(
    conn: IBKRConnection,
    interval_seconds: int = 30,
    max_iterations: int | None = None,
) -> None:
    """
    Loop de monitoreo: imprime el portfolio cada `interval_seconds`.
    Presionar Ctrl+C para detener.
    """
    print(f"Monitoreo iniciado. Actualizando cada {interval_seconds}s. (Ctrl+C para salir)")
    iterations = 0
    try:
        while True:
            portfolio_df = get_live_portfolio(conn)
            account = conn.get_account_summary()
            print_portfolio_table(portfolio_df, account)

            iterations += 1
            if max_iterations and iterations >= max_iterations:
                break
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\nMonitoreo detenido.")
