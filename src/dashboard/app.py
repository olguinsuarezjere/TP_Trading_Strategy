import os
import sys
import yaml
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# Asegurar que el root del proyecto esté en el path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.loader import load_returns
from src.data.universe import ETF_UNIVERSE
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import (
    sharpe_ratio, annualized_return, annualized_volatility, max_drawdown, calmar_ratio
)
from src.robustness.sensitivity import lookback_sensitivity, target_vol_sensitivity, cost_sensitivity
from src.robustness.stress_test import analyze_crisis_performance, CRISIS_PERIODS
from src.robustness.out_of_sample import walk_forward, expanding_window
from src.strategy.signals import compute_tsmom_signal
from src.strategy.volatility import compute_ex_ante_vol

# --- Config y datos cacheados ------------------------------------------------

CONFIG_PATH = os.path.join(ROOT, "config.yaml")

@st.cache_data(show_spinner=False)
def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

@st.cache_data(show_spinner="Cargando retornos...")
def _load_returns(config_str: str):
    config = yaml.safe_load(config_str)
    return load_returns(config)

@st.cache_data(show_spinner="Corriendo backtest...")
def _run_backtest(config_str: str, signal_type: str):
    config = yaml.safe_load(config_str)
    returns = load_returns(config)
    engine = BacktestEngine(config)
    results = engine.run(returns, use_signal_strength=(signal_type == "strength"))
    return results, returns

# --- Layout global -----------------------------------------------------------

st.set_page_config(
    page_title="TSMOM Trading System",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Sidebar -----------------------------------------------------------------

with st.sidebar:
    st.title("📈 TSMOM System")
    st.caption("Ingeniería Financiera F414 — UdeSA")
    st.divider()

    page = st.radio(
        "Navegación",
        ["1. Overview", "2. Backtest", "3. Robustness", "4. Live Portfolio", "5. Trade Log"],
        label_visibility="collapsed",
    )
    st.divider()

    st.subheader("Parámetros")
    lookback = st.slider("Lookback (meses)", 3, 24, 12, step=1)
    target_vol = st.slider("Target Vol (anual)", 0.05, 0.25, 0.10, step=0.01, format="%.0%%")
    signal_type = st.radio("Señal", ["binary", "strength"], horizontal=True)
    start_date = st.date_input("Inicio backtest", value=pd.Timestamp("2015-01-01"))
    end_date = st.date_input("Fin backtest", value=pd.Timestamp("2024-12-31"))

    config = _load_config()
    config["strategy"]["lookback_months"] = lookback
    config["strategy"]["target_volatility"] = target_vol
    config["backtest"]["start_date"] = str(start_date)
    config["backtest"]["end_date"] = str(end_date)
    config_str = yaml.dump(config)

# --- Página 1: Overview ------------------------------------------------------

if page == "1. Overview":
    st.title("Time Series Momentum — Overview")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Universo", f"{len(ETF_UNIVERSE)} ETFs")
    col2.metric("Lookback", f"{lookback}m")
    col3.metric("Target Vol", f"{target_vol:.0%}")
    col4.metric("Señal", signal_type.capitalize())

    st.divider()

    returns = _load_returns(config_str)
    signal = compute_tsmom_signal(returns, lookback=lookback)
    latest_signal = signal.iloc[-1].dropna()
    latest_date = signal.index[-1].strftime("%Y-%m")

    st.subheader(f"Señales actuales — {latest_date}")

    # Heatmap de señales por asset class
    rows = []
    for ticker, sig_val in latest_signal.items():
        rows.append({
            "ticker": ticker,
            "signal": int(sig_val),
            "asset_class": ETF_UNIVERSE.get(ticker, "other"),
        })
    sig_df = pd.DataFrame(rows).sort_values(["asset_class", "ticker"])

    for ac in ["equity", "bond", "commodity", "currency"]:
        ac_df = sig_df[sig_df["asset_class"] == ac]
        if ac_df.empty:
            continue
        st.markdown(f"**{ac.capitalize()}**")
        cols = st.columns(min(len(ac_df), 10))
        for col, (_, row) in zip(cols, ac_df.iterrows()):
            color = "🟢" if row["signal"] == 1 else "🔴"
            col.metric(row["ticker"], f"{color} {'LONG' if row['signal']==1 else 'SHORT'}")

    st.divider()
    n_long = (latest_signal == 1).sum()
    n_short = (latest_signal == -1).sum()
    st.markdown(f"**Posiciones:** {n_long} long · {n_short} short · "
                f"Net exposure: {(n_long - n_short) / len(latest_signal):.1%}")

# --- Página 2: Backtest ------------------------------------------------------

elif page == "2. Backtest":
    st.title("Backtest Results")

    results, returns = _run_backtest(config_str, signal_type)

    # Métricas resumen
    r = results.portfolio_returns
    m_cols = st.columns(5)
    m_cols[0].metric("Sharpe Ratio",     f"{sharpe_ratio(r):.2f}")
    m_cols[1].metric("Ann. Return",      f"{annualized_return(r):.2%}")
    m_cols[2].metric("Ann. Volatility",  f"{annualized_volatility(r):.2%}")
    m_cols[3].metric("Max Drawdown",     f"{max_drawdown(r):.2%}")
    m_cols[4].metric("Calmar Ratio",     f"{calmar_ratio(r):.2f}")

    st.divider()

    # Equity curve
    cum_net   = (1 + results.portfolio_returns).cumprod()
    cum_gross = (1 + results.gross_returns).cumprod()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cum_net.index, y=cum_net.values,
                             name="Neto", line=dict(color="#1f77b4", width=2)))
    fig.add_trace(go.Scatter(x=cum_gross.index, y=cum_gross.values,
                             name="Bruto", line=dict(color="#aec7e8", width=1.5, dash="dot")))
    fig.update_layout(title="Curva de Capital", yaxis_title="Valor (base 1)",
                      yaxis_type="log", height=380, legend=dict(x=0, y=1))
    st.plotly_chart(fig, use_container_width=True)

    # Drawdown
    dd = (cum_net - cum_net.cummax()) / cum_net.cummax()
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(x=dd.index, y=dd.values * 100,
                                fill="tozeroy", fillcolor="rgba(255,100,100,0.3)",
                                line=dict(color="red", width=1), name="Drawdown"))
    fig_dd.update_layout(title="Drawdown (%)", yaxis_title="%", height=220)
    st.plotly_chart(fig_dd, use_container_width=True)

    # Retornos mensuales (heatmap)
    st.subheader("Retornos mensuales")
    monthly = results.portfolio_returns.copy()
    monthly_df = pd.DataFrame({
        "year":  monthly.index.year,
        "month": monthly.index.month,
        "ret":   monthly.values,
    })
    pivot = monthly_df.pivot(index="year", columns="month", values="ret")
    pivot.columns = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
    fig_heat = px.imshow(
        pivot * 100, text_auto=".1f", aspect="auto",
        color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
        title="Retornos mensuales (%)",
    )
    st.plotly_chart(fig_heat, use_container_width=True)

    # Tabla de métricas completa
    st.subheader("Métricas de performance")
    metrics_df = pd.DataFrame.from_dict(results.metrics, orient="index", columns=["Valor"])
    st.dataframe(metrics_df, use_container_width=True)

# --- Página 3: Robustness ----------------------------------------------------

elif page == "3. Robustness":
    st.title("Tests de Robustez")

    results, returns = _run_backtest(config_str, signal_type)

    tab1, tab2, tab3 = st.tabs(["📊 Sensibilidad", "🔥 Stress Test", "📉 Out-of-Sample"])

    with tab1:
        st.subheader("Sensibilidad al Lookback")
        with st.spinner("Calculando..."):
            lb_df = lookback_sensitivity(returns, config)
        fig_lb = go.Figure()
        fig_lb.add_bar(x=lb_df.index, y=lb_df["sharpe"], name="Sharpe",
                       marker_color=["green" if v > 0 else "red" for v in lb_df["sharpe"]])
        fig_lb.update_layout(title="Sharpe por lookback", xaxis_title="Meses", height=300)
        st.plotly_chart(fig_lb, use_container_width=True)
        st.dataframe(lb_df.round(2), use_container_width=True)

        st.subheader("Sensibilidad al Target Volatility")
        with st.spinner("Calculando..."):
            tv_df = target_vol_sensitivity(returns, config)
        st.dataframe(tv_df.round(2), use_container_width=True)

        st.subheader("Sensibilidad a Costos de Transacción")
        with st.spinner("Calculando..."):
            cs_df = cost_sensitivity(returns, config)
        fig_cs = px.line(cs_df.reset_index(), x="spread", y="sharpe",
                         markers=True, title="Sharpe vs. Spread bid-ask")
        st.plotly_chart(fig_cs, use_container_width=True)

    with tab2:
        st.subheader("Performance durante períodos de crisis")
        crisis_df = analyze_crisis_performance(results.portfolio_returns)
        st.dataframe(crisis_df, use_container_width=True)

        # Equity curve con períodos de crisis sombreados
        cum = (1 + results.portfolio_returns).cumprod()
        fig_crisis = go.Figure()
        fig_crisis.add_trace(go.Scatter(x=cum.index, y=cum.values,
                                        name="Portfolio", line=dict(color="#1f77b4", width=2)))
        colors = ["rgba(255,0,0,0.1)", "rgba(255,140,0,0.1)", "rgba(128,0,128,0.1)", "rgba(0,128,0,0.1)"]
        for (name, (s, e)), color in zip(CRISIS_PERIODS.items(), colors):
            fig_crisis.add_vrect(x0=s, x1=e, fillcolor=color, line_width=0,
                                 annotation_text=name, annotation_position="top left")
        fig_crisis.update_layout(title="Equity Curve con Períodos de Crisis", height=380)
        st.plotly_chart(fig_crisis, use_container_width=True)

    with tab3:
        st.subheader("Walk-Forward Analysis")
        with st.spinner("Calculando walk-forward..."):
            wf_df = walk_forward(returns, config)
        if not wf_df.empty:
            st.dataframe(wf_df.round(2), use_container_width=True)
            fig_wf = px.bar(wf_df, x="test_start", y="sharpe",
                            color=wf_df["sharpe"].apply(lambda x: "pos" if x >= 0 else "neg"),
                            color_discrete_map={"pos": "steelblue", "neg": "salmon"},
                            title="Sharpe Out-of-Sample por ventana")
            fig_wf.add_hline(y=0, line_dash="dash", line_color="black")
            st.plotly_chart(fig_wf, use_container_width=True)

        st.subheader("In-Sample vs Out-of-Sample")
        with st.spinner("Calculando expanding window..."):
            oos_df = expanding_window(returns, config)
        st.dataframe(oos_df.round(2), use_container_width=True)

# --- Página 4: Live Portfolio ------------------------------------------------

elif page == "4. Live Portfolio":
    st.title("Live Portfolio — IBKR Paper Trading")

    st.info("Requiere que IBKR TWS esté corriendo con API activada (puerto 7497).")

    if st.button("🔄 Conectar y actualizar"):
        try:
            from src.broker.ibkr import IBKRConnection
            from src.broker.monitor import get_live_portfolio, compute_live_pnl

            broker = config["broker"]
            conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
            conn.connect()

            portfolio_df = get_live_portfolio(conn)
            account = conn.get_account_summary()
            pnl = compute_live_pnl(portfolio_df)
            conn.disconnect()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Net Liquidation",  f"${account.get('NetLiquidation', 0):,.0f}")
            col2.metric("Cash",             f"${account.get('TotalCashValue', 0):,.0f}")
            col3.metric("Unrealized P&L",   f"${pnl.get('total_unrealized_pnl', 0):,.0f}")
            col4.metric("Posiciones",       f"{pnl.get('n_positions', 0)}")

            if not portfolio_df.empty:
                st.subheader("Posiciones abiertas")
                # Exposición por asset class
                portfolio_df["asset_class"] = portfolio_df["ticker"].map(ETF_UNIVERSE)
                ac_exposure = portfolio_df.groupby("asset_class")["market_value"].sum()
                fig_pie = px.pie(ac_exposure.reset_index(), values="market_value",
                                 names="asset_class", title="Exposición por Asset Class")
                col_pie, col_tbl = st.columns([1, 2])
                col_pie.plotly_chart(fig_pie, use_container_width=True)
                col_tbl.dataframe(
                    portfolio_df[["ticker", "qty", "market_price", "market_value", "weight", "unrealized_pnl"]]
                    .sort_values("market_value", ascending=False)
                    .style.format({"weight": "{:.1%}", "market_value": "${:,.0f}", "unrealized_pnl": "${:,.0f}"}),
                    use_container_width=True,
                )
            else:
                st.warning("Sin posiciones abiertas en la cuenta paper.")
        except Exception as e:
            st.error(f"Error al conectar con IBKR TWS: {e}")
            st.info("Verificá que TWS esté abierto y la API esté habilitada en puerto 7497.")
    else:
        st.markdown("""
        **Cómo activar la API en TWS:**
        1. Abrir TWS -> Edit -> Global Configuration -> API -> Settings
        2. ✅ Enable ActiveX and Socket Clients
        3. Puerto: **7497** (paper) — **7496** (real)
        4. Agregar `127.0.0.1` en Trusted IPs
        5. Hacer clic en **Conectar y actualizar** arriba
        """)

# --- Página 5: Trade Log -----------------------------------------------------

elif page == "5. Trade Log":
    st.title("Trade Log")

    log_path = os.path.join(ROOT, "logs", "trades.csv")

    if os.path.exists(log_path) and os.path.getsize(log_path) > 1:
        trades_df = pd.read_csv(log_path)
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])

        col1, col2, col3 = st.columns(3)
        col1.metric("Total órdenes", len(trades_df))
        col2.metric("Compras",       len(trades_df[trades_df["action"] == "BUY"]))
        col3.metric("Ventas",        len(trades_df[trades_df["action"] == "SELL"]))

        # Filtros
        st.subheader("Filtrar")
        col_f1, col_f2 = st.columns(2)
        tickers_filter = col_f1.multiselect("Ticker", sorted(trades_df["ticker"].unique()))
        action_filter  = col_f2.multiselect("Acción", ["BUY", "SELL"])

        df_filtered = trades_df.copy()
        if tickers_filter:
            df_filtered = df_filtered[df_filtered["ticker"].isin(tickers_filter)]
        if action_filter:
            df_filtered = df_filtered[df_filtered["action"].isin(action_filter)]

        st.dataframe(
            df_filtered.sort_values("timestamp", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

        # Actividad por mes
        trades_df["month"] = trades_df["timestamp"].dt.to_period("M").astype(str)
        monthly_count = trades_df.groupby("month").size().reset_index(name="count")
        fig_bar = px.bar(monthly_count, x="month", y="count",
                         title="Número de órdenes por mes")
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No hay trades registrados todavía. "
                "Ejecutá `python main.py execute` para registrar operaciones.")
