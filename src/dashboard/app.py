import os
import sys
import html
import yaml
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

# Asegurar que el root del proyecto esté en el path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.data.loader import load_returns
from src.data.universe import ETF_UNIVERSE, ASSET_CLASSES
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import (
    sharpe_ratio, sortino_ratio, annualized_return, annualized_volatility,
    max_drawdown, calmar_ratio, hit_rate, turnover,
)
from src.robustness.sensitivity import lookback_sensitivity, target_vol_sensitivity, cost_sensitivity
from src.robustness.stress_test import analyze_crisis_performance, CRISIS_PERIODS
from src.robustness.out_of_sample import walk_forward, expanding_window
from src.strategy.signals import compute_tsmom_signal, compute_signal_strength
from src.strategy.volatility import compute_ex_ante_vol
from src.dashboard import theme as T

# ============================================================ CONFIG / DATA

CONFIG_PATH = os.path.join(ROOT, "config.yaml")
AC_LABEL = {"equity": "Equities", "bond": "Bonds", "commodity": "Commodities", "currency": "Currencies"}


@st.cache_data(show_spinner=False)
def _load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@st.cache_data(show_spinner="Cargando retornos…")
def _load_returns(config_str: str):
    return load_returns(yaml.safe_load(config_str))


@st.cache_data(show_spinner="Corriendo backtest…")
def _run_backtest(config_str: str, signal_type: str):
    config = yaml.safe_load(config_str)
    returns = load_returns(config)
    results = BacktestEngine(config).run(returns, use_signal_strength=(signal_type == "strength"))
    return results, returns


# ============================================================ HELPERS

def pct(x, d=2, signed=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    s = f"{x*100:+.{d}f}%" if signed else f"{x*100:.{d}f}%"
    return s


def num(x, d=2):
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def usd(x, d=0):
    return f"${x:,.{d}f}"


def tone(x):
    return "pos" if x >= 0 else "neg"


def kpi(label, value, delta="", value_cls="", delta_cls="tone-dim"):
    return (f'<div class="kpi"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value {value_cls}">{value}</div>'
            f'<div class="kpi-delta {delta_cls}">{delta}</div></div>')


def sparkline(values, color, width=250, height=54):
    vals = [float(v) for v in values if v is not None and not np.isnan(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = " ".join(
        f"{i/(n-1)*(width-2)+1:.1f},{height-2-((v-lo)/rng)*(height-4):.1f}"
        for i, v in enumerate(vals)
    )
    return (f'<svg width="100%" height="{height}" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
            f'style="display:block">'
            f'<polyline fill="none" stroke="{color}" stroke-width="1.4" points="{pts}"/></svg>')


def topbar(asof, lookback, target_vol, signal_type, sharpe):
    return f"""
    <div class="topbar">
      <div class="tb-left">
        <span class="tb-brand">TSMOM<span>·TERMINAL</span></span>
        <span class="tb-sep">│</span><span class="tb-tag">F414 · UdeSA</span>
        <span class="tb-sep">│</span><span class="tb-muted">Time Series Momentum · {len(ETF_UNIVERSE)} ETFs</span>
      </div>
      <div class="tb-right">
        <span class="tb-chip"><span class="dot"></span>PAPER · IBKR 7497</span>
        <span class="tb-chip">LB <b>{lookback}m</b></span>
        <span class="tb-chip">TV <b>{target_vol*100:.0f}%</b></span>
        <span class="tb-chip">SHARPE <b>{sharpe:.2f}</b></span>
        <span class="tb-chip accent">{signal_type.upper()}</span>
        <span class="tb-sep">│</span><span class="tb-muted">corte {asof}</span>
      </div>
    </div>"""


def panel(title, body, sub="", right=""):
    sub_h = f'<span class="panel-sub">{sub}</span>' if sub else ""
    right_h = f'<div class="panel-sub">{right}</div>' if right else ""
    return (f'<div class="panel"><div class="panel-head">'
            f'<div class="panel-title">{title} {sub_h}</div>{right_h}</div>'
            f'<div class="panel-body">{body}</div></div>')


# ============================================================ APP SHELL

st.set_page_config(page_title="TSMOM Terminal · F414 UdeSA", page_icon="📟",
                   layout="wide", initial_sidebar_state="expanded")

if "theme" not in st.session_state:
    st.session_state.theme = "phosphor"
st.markdown(T.inject(st.session_state.theme), unsafe_allow_html=True)
PAL = T.PALETTES[st.session_state.theme]

with st.sidebar:
    st.markdown(
        '<div class="side-head"><div class="side-logo">◢</div>'
        '<div><div class="side-title">TSMOM</div><div class="side-sub">SYSTEM v2.1</div></div></div>',
        unsafe_allow_html=True)

    page = st.radio("Navegación",
                    ["01 · Overview", "02 · Backtest", "03 · Robustness",
                     "04 · Live Portfolio", "05 · Trade Log"],
                    label_visibility="collapsed")

    st.markdown('<div class="side-label">Parámetros</div>', unsafe_allow_html=True)
    lookback = st.slider("Lookback (meses)", 3, 24, 12, step=1)
    target_vol = st.slider("Target Vol (anual)", 0.05, 0.40, 0.10, step=0.01)
    signal_type = st.radio("Señal", ["binary", "strength"], horizontal=True)

    st.markdown('<div class="side-label">Estilo</div>', unsafe_allow_html=True)
    theme_choice = st.radio("Tema", ["phosphor", "amber", "ice"], horizontal=True,
                            index=["phosphor", "amber", "ice"].index(st.session_state.theme),
                            label_visibility="collapsed")
    if theme_choice != st.session_state.theme:
        st.session_state.theme = theme_choice
        st.rerun()

    config = _load_config()
    config["strategy"]["lookback_months"] = lookback
    config["strategy"]["target_volatility"] = target_vol
    config_str = yaml.dump(config)

    win = f'{config["backtest"]["start_date"][:7]} → {config["backtest"]["end_date"][:7]}'
    st.markdown(
        f'<div class="side-foot">'
        f'<div class="foot-row"><span>UNIVERSO</span><b>{len(ETF_UNIVERSE)} ETF</b></div>'
        f'<div class="foot-row"><span>REBAL</span><b>MENSUAL</b></div>'
        f'<div class="foot-row"><span>VENTANA</span><b>{win}</b></div>'
        f'<div class="foot-row"><span>CAPITAL</span><b>$1.00M</b></div></div>',
        unsafe_allow_html=True)

# Datos compartidos
results, returns = _run_backtest(config_str, signal_type)
r = results.portfolio_returns
equity = (1 + r).cumprod()
sharpe = sharpe_ratio(r)
asof = returns.index[-1].strftime("%Y-%m")

st.markdown(topbar(asof, lookback, target_vol, signal_type, sharpe), unsafe_allow_html=True)


# ============================================================ PÁGINA 1 · OVERVIEW

if page.startswith("01"):
    st.markdown('<div class="page-h1">Time Series Momentum <span class="dim">— Overview</span></div>'
                f'<div class="page-sub">Señales del próximo rebalanceo · corte {asof} · lookback {lookback}m</div>',
                unsafe_allow_html=True)

    strength = compute_signal_strength(returns, lookback=lookback)
    sig_bin = compute_tsmom_signal(returns, lookback=lookback)
    last_str = strength.iloc[-1]
    last_dir = sig_bin.iloc[-1]
    valid = last_dir.dropna()
    n_long = int((valid == 1).sum())
    n_short = int((valid == -1).sum())
    net_exp = (n_long - n_short) / max(len(valid), 1)
    since = equity.iloc[-1] - 1

    strip = "".join([
        kpi("Universo", f"{len(ETF_UNIVERSE)}", "ETFs · 4 clases"),
        kpi("Sharpe (IS)", f"{sharpe:.2f}", "2015–2024", "accent", "tone-accent"),
        kpi("Ret. desde inicio", pct(since, 1, True), "neto de costos", "", f"tone-{tone(since)}"),
        kpi("Net exposure", pct(net_exp, 0, True), f"{n_long}L · {n_short}S", "", f"tone-{tone(net_exp)}"),
        kpi("Posiciones", f"{n_long + n_short}", "todas activas"),
    ])
    st.markdown(f'<div class="kpi-strip">{strip}</div>', unsafe_allow_html=True)

    col_main, col_side = st.columns([2.1, 1])

    with col_main:
        sections = ""
        for ac in ASSET_CLASSES:
            tickers = [t for t in valid.index if ETF_UNIVERSE.get(t) == ac]
            if not tickers:
                continue
            cells = ""
            for tk in sorted(tickers):
                d = last_dir.get(tk, 0)
                s = last_str.get(tk, 0.0)
                s = 0.0 if pd.isna(s) else float(s)
                intn = min(1.0, abs(s) / 3.0)
                side = "sig-pos" if d >= 0 else "sig-neg"
                cells += (f'<div class="sigcell {side}" style="--int:{intn:.2f}">'
                          f'<span class="sig-tk">{tk}</span>'
                          f'<span class="sig-bar"><span style="width:{intn*100:.0f}%"></span></span></div>')
            nl = sum(1 for t in tickers if last_dir.get(t, 0) >= 0)
            sections += (f'<div class="sig-class"><div class="sig-class-head">'
                         f'<span class="sig-class-name">{AC_LABEL[ac]}</span>'
                         f'<span class="sig-class-meta">{len(tickers)} · {nl}L/{len(tickers)-nl}S</span></div>'
                         f'<div class="sig-grid">{cells}</div></div>')
        st.markdown(panel("SEÑAL TSMOM — MATRIZ DE ACTIVOS", sections,
                          sub="intensidad = |fuerza de tendencia|"), unsafe_allow_html=True)

    with col_side:
        spark = sparkline(equity.values, PAL["accent"])
        nav_body = (f'<div class="nav-val">{equity.iloc[-1]:.3f}×</div>'
                    f'<div class="nav-delta tone-{tone(since)}">{pct(since,1,True)}</div>'
                    f'{spark}'
                    f'<div class="nav-foot"><span>vol <b>{pct(annualized_volatility(r),1)}</b></span>'
                    f'<span>maxDD <b class="tone-neg">{pct(max_drawdown(r),1)}</b></span>'
                    f'<span>calmar <b>{num(calmar_ratio(r))}</b></span></div>')
        st.markdown(panel("NAV DESDE INICIO", nav_body, sub="base 1.00×"), unsafe_allow_html=True)

        rows = ""
        for ac in ASSET_CLASSES:
            tickers = [t for t in valid.index if ETF_UNIVERSE.get(t) == ac]
            if not tickers:
                continue
            nl = sum(1 for t in tickers if last_dir.get(t, 0) >= 0)
            ns = len(tickers) - nl
            lp = nl / len(tickers) * 100
            sp = ns / len(tickers) * 100
            rows += (f'<div class="ac-row"><span class="ac-name">{AC_LABEL[ac]}</span>'
                     f'<span class="ac-track"><span class="ac-fill pos" style="width:{lp:.0f}%"></span>'
                     f'<span class="ac-fill neg" style="width:{sp:.0f}%"></span></span>'
                     f'<span class="ac-meta">{nl}/{ns}</span></div>')
        rows += (f'<div class="ac-foot">Net exposure agregado '
                 f'<b class="{tone(net_exp)}">{pct(net_exp,0,True)}</b> · gross 100% · '
                 f'{n_long} long / {n_short} short</div>')
        st.markdown(panel("EXPOSICIÓN POR CLASE", rows), unsafe_allow_html=True)


# ============================================================ PÁGINA 2 · BACKTEST

elif page.startswith("02"):
    st.markdown('<div class="page-h1">Backtest <span class="dim">— Resultados</span></div>'
                f'<div class="page-sub">{config["backtest"]["start_date"][:7]} → {config["backtest"]["end_date"][:7]} · '
                f'{len(r)} meses · costos {config["transaction_costs"]["bid_ask_spread"]*1e4:.0f}bps spread + '
                f'{config["transaction_costs"]["commission_pct"]*1e4:.0f}bps comisión</div>',
                unsafe_allow_html=True)

    strip = "".join([
        kpi("Sharpe Ratio", f"{sharpe:.2f}", "rf = 0", "accent", "tone-accent"),
        kpi("Ann. Return", pct(annualized_return(r), 1), "neto", "", "tone-pos"),
        kpi("Ann. Volatility", pct(annualized_volatility(r), 1), f"target {target_vol*100:.0f}%"),
        kpi("Max Drawdown", pct(max_drawdown(r), 1), "peak-to-trough", "", "tone-neg"),
        kpi("Calmar Ratio", num(calmar_ratio(r)), "ret/maxDD", "accent", "tone-accent"),
    ])
    st.markdown(f'<div class="kpi-strip">{strip}</div>', unsafe_allow_html=True)

    cum_net = equity
    cum_gross = (1 + results.gross_returns).cumprod()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=cum_gross.index, y=cum_gross.values, name="Bruto",
                             line=dict(color=PAL["text-mute"], width=1.3, dash="dot")))
    fig.add_trace(go.Scatter(x=cum_net.index, y=cum_net.values, name="Neto",
                             line=dict(color=PAL["accent"], width=2),
                             fill="tozeroy", fillcolor=T.rgba(PAL["accent"], 0.08)))
    fig.update_yaxes(type="log")
    T.fig_layout(fig, PAL, height=300, legend=True)
    st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">CURVA DE CAPITAL '
                '<span class="panel-sub">escala log · neto vs bruto</span></div></div>', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1.4, 1])
    with c1:
        dd = (cum_net - cum_net.cummax()) / cum_net.cummax()
        fdd = go.Figure()
        fdd.add_trace(go.Scatter(x=dd.index, y=dd.values * 100, fill="tozeroy",
                                 fillcolor=T.rgba(PAL["neg"], 0.15), line=dict(color=PAL["neg"], width=1.3),
                                 name="Drawdown"))
        T.fig_layout(fdd, PAL, height=230)
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">DRAWDOWN '
                    '<span class="panel-sub">underwater %</span></div></div>', unsafe_allow_html=True)
        st.plotly_chart(fdd, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)
    with c2:
        rows = [
            ("Annualized Return", pct(annualized_return(r), 2), "mrow-v tone-pos"),
            ("Annualized Volatility", pct(annualized_volatility(r), 2), "mrow-v"),
            ("Sharpe Ratio", num(sharpe), "mrow-v tone-accent"),
            ("Sortino Ratio", num(sortino_ratio(r)), "mrow-v tone-accent"),
            ("Max Drawdown", pct(max_drawdown(r), 2), "mrow-v tone-neg"),
            ("Calmar Ratio", num(calmar_ratio(r)), "mrow-v"),
            ("Hit Rate", pct(hit_rate(r), 1), "mrow-v"),
            ("Avg Monthly Turnover", pct(turnover(results.weights), 1), "mrow-v"),
            ("Num Months", str(len(r)), "mrow-v"),
        ]
        body = "".join(f'<div class="mrow"><span class="mrow-k">{k}</span>'
                       f'<span class="{cls}">{v}</span></div>' for k, v, cls in rows)
        st.markdown(panel("MÉTRICAS DE PERFORMANCE", f'<div class="mtable">{body}</div>'),
                    unsafe_allow_html=True)

    monthly_df = pd.DataFrame({"year": r.index.year, "month": r.index.month, "ret": r.values})
    pivot = monthly_df.pivot(index="year", columns="month", values="ret")
    pivot = pivot.reindex(columns=range(1, 13))
    pivot.columns = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    fh = go.Figure(go.Heatmap(
        z=pivot.values * 100, x=list(pivot.columns), y=[str(y) for y in pivot.index],
        colorscale=[[0, PAL["neg"]], [0.5, PAL["bg-1"]], [1, PAL["accent"]]], zmid=0,
        text=np.round(pivot.values * 100, 1), texttemplate="%{text}",
        textfont=dict(size=9, family="JetBrains Mono"), showscale=False,
        hovertemplate="%{y} %{x}: %{z:.1f}%<extra></extra>"))
    fh.update_yaxes(autorange="reversed")
    T.fig_layout(fh, PAL, height=300)
    st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">RETORNOS MENSUALES '
                '<span class="panel-sub">% · verde = ganancia</span></div></div>', unsafe_allow_html=True)
    st.plotly_chart(fh, use_container_width=True, config={"displayModeBar": False})
    st.markdown('</div>', unsafe_allow_html=True)


# ============================================================ PÁGINA 3 · ROBUSTNESS

elif page.startswith("03"):
    st.markdown('<div class="page-h1">Tests de Robustez</div>'
                '<div class="page-sub">sensibilidad paramétrica · performance en crisis · validación out-of-sample</div>',
                unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["SENSIBILIDAD", "STRESS TEST", "OUT-OF-SAMPLE"])

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            lb_df = lookback_sensitivity(returns, config)
            flb = go.Figure(go.Bar(x=[str(i) for i in lb_df.index], y=lb_df["sharpe"],
                                   marker_color=[PAL["accent"] if v >= 0 else PAL["neg"] for v in lb_df["sharpe"]]))
            T.fig_layout(flb, PAL, height=250)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">SHARPE POR LOOKBACK '
                        '<span class="panel-sub">meses</span></div></div>', unsafe_allow_html=True)
            st.plotly_chart(flb, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)
        with c2:
            cs_df = cost_sensitivity(returns, config).reset_index()
            xcol = cs_df.columns[0]
            fcs = go.Figure(go.Scatter(x=cs_df[xcol], y=cs_df["sharpe"], mode="lines+markers",
                                       line=dict(color=PAL["accent"], width=2),
                                       marker=dict(color=PAL["accent"], size=7)))
            T.fig_layout(fcs, PAL, height=250)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">SHARPE vs COSTOS '
                        '<span class="panel-sub">spread bid-ask</span></div></div>', unsafe_allow_html=True)
            st.plotly_chart(fcs, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'SENSIBILIDAD AL TARGET VOL</div></div>', unsafe_allow_html=True)
        tv_df = target_vol_sensitivity(returns, config)
        st.dataframe(tv_df.round(3), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        cum = equity
        fc = go.Figure()
        fc.add_trace(go.Scatter(x=cum.index, y=cum.values, name="Portfolio",
                                line=dict(color=PAL["accent"], width=2)))
        for name, (s, e) in CRISIS_PERIODS.items():
            fc.add_vrect(x0=s, x1=e, fillcolor=PAL["neg"], opacity=0.10, line_width=0,
                         annotation_text=name, annotation_position="top left",
                         annotation_font=dict(size=9, color=PAL["text-dim"]))
        fc.update_yaxes(type="log")
        T.fig_layout(fc, PAL, height=300)
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'EQUITY CURVE — CRISIS SOMBREADAS <span class="panel-sub">escala log</span></div></div>',
                    unsafe_allow_html=True)
        st.plotly_chart(fc, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'PERFORMANCE DURANTE CRISIS</div></div>', unsafe_allow_html=True)
        st.dataframe(analyze_crisis_performance(r), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        wf_df = walk_forward(returns, config)
        if not wf_df.empty:
            fw = go.Figure(go.Bar(x=wf_df["test_start"].astype(str), y=wf_df["sharpe"],
                                  marker_color=[PAL["accent"] if v >= 0 else PAL["neg"] for v in wf_df["sharpe"]]))
            fw.add_hline(y=0, line_dash="dash", line_color=PAL["border"])
            T.fig_layout(fw, PAL, height=260)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                        'WALK-FORWARD — SHARPE OUT-OF-SAMPLE</div></div>', unsafe_allow_html=True)
            st.plotly_chart(fw, use_container_width=True, config={"displayModeBar": False})
            st.markdown('</div>', unsafe_allow_html=True)
            st.dataframe(wf_df.round(2), use_container_width=True)

        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'IN-SAMPLE vs OUT-OF-SAMPLE</div></div>', unsafe_allow_html=True)
        st.dataframe(expanding_window(returns, config).round(2), use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)


# ============================================================ PÁGINA 4 · LIVE PORTFOLIO

elif page.startswith("04"):
    import time as _time

    st.markdown('<div class="page-h1">Live Portfolio <span class="dim">— IBKR Paper Trading</span></div>'
                '<div class="page-sub">requiere TWS corriendo con API activada (puerto 7497)</div>',
                unsafe_allow_html=True)

    cb, ca, ci = st.columns([1, 1, 1])
    refresh_now = cb.button("🔄 Conectar y actualizar")
    auto_refresh = ca.toggle("Auto-refresh", value=False)
    interval_secs = ci.number_input("Intervalo (seg)", 10, 300, 30, 10, disabled=not auto_refresh)

    def _show_portfolio():
        from src.broker.ibkr import IBKRConnection
        from src.broker.monitor import get_live_portfolio, compute_live_pnl
        broker = config["broker"]
        conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
        conn.connect()
        portfolio_df = get_live_portfolio(conn)
        account = conn.get_account_summary()
        pnl = compute_live_pnl(portfolio_df)
        conn.disconnect()

        strip = "".join([
            kpi("Net Liquidation", usd(account.get("NetLiquidation", 0))),
            kpi("Cash", usd(account.get("TotalCashValue", 0))),
            kpi("Unrealized P&L", usd(pnl.get("total_unrealized_pnl", 0)), "",
                "", f"tone-{tone(pnl.get('total_unrealized_pnl', 0))}"),
            kpi("Posiciones", f"{pnl.get('n_positions', 0)}"),
            kpi("Buying Power", usd(account.get("NetLiquidation", 0) * 2)),
        ])
        st.markdown(f'<div class="kpi-strip">{strip}</div>', unsafe_allow_html=True)

        if not portfolio_df.empty:
            portfolio_df["asset_class"] = portfolio_df["ticker"].map(ETF_UNIVERSE)
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                        'POSICIONES ABIERTAS</div></div>', unsafe_allow_html=True)
            st.dataframe(
                portfolio_df[["ticker", "qty", "market_price", "market_value", "weight", "unrealized_pnl"]]
                .sort_values("market_value", ascending=False),
                use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning("Sin posiciones abiertas en la cuenta paper.")
        return account

    if refresh_now or auto_refresh:
        try:
            _show_portfolio()
            st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                        'EJECUTAR REBALANCEO TSMOM</div></div>', unsafe_allow_html=True)
            from src.strategy.portfolio import build_portfolio
            weights_df, _ = build_portfolio(returns, config)
            target_weights = weights_df.iloc[-1].dropna()
            target_weights = target_weights[target_weights != 0]
            cd, ce = st.columns(2)
            if cd.button("🔍 Dry Run — Ver órdenes"):
                from src.broker.orders import execute_rebalance
                st.session_state["dry_run_orders"] = execute_rebalance(
                    None, target_weights, capital=1_000_000, dry_run=True)
            if st.session_state.get("dry_run_orders"):
                st.dataframe(pd.DataFrame(st.session_state["dry_run_orders"]),
                             use_container_width=True, hide_index=True)
            st.warning("⚠️ El botón de abajo ejecuta órdenes REALES en tu cuenta paper.")
            if ce.button("🚀 Ejecutar en IBKR", type="primary"):
                from src.broker.ibkr import IBKRConnection
                from src.broker.orders import execute_rebalance
                broker = config["broker"]
                conn = IBKRConnection(broker["host"], broker["port"], broker["client_id"])
                try:
                    conn.connect()
                    capital = conn.get_account_summary().get("NetLiquidation", 1_000_000)
                    execute_rebalance(conn, target_weights, capital=capital, dry_run=False)
                    st.success(f"Rebalanceo ejecutado. Capital: {usd(capital)}")
                    st.session_state.pop("dry_run_orders", None)
                finally:
                    conn.disconnect()
            st.markdown('</div>', unsafe_allow_html=True)
        except Exception as e:
            st.error(f"Error al conectar con IBKR TWS: {e}")
            st.info("Verificá que TWS esté abierto y la API habilitada en puerto 7497.")
        if auto_refresh:
            _time.sleep(interval_secs)
            st.rerun()
    else:
        st.markdown(panel("CÓMO ACTIVAR LA API EN TWS",
                          '<div class="mtable">'
                          '<div class="mrow"><span class="mrow-k">1 · TWS → Edit → Global Configuration → API → Settings</span><span></span></div>'
                          '<div class="mrow"><span class="mrow-k">2 · ✅ Enable ActiveX and Socket Clients</span><span></span></div>'
                          '<div class="mrow"><span class="mrow-k">3 · Puerto</span><span class="mrow-v">7497 paper · 7496 real</span></div>'
                          '<div class="mrow"><span class="mrow-k">4 · Agregar 127.0.0.1 en Trusted IPs</span><span></span></div>'
                          '<div class="mrow"><span class="mrow-k">5 · Clic en «Conectar y actualizar» arriba</span><span></span></div>'
                          '</div>'), unsafe_allow_html=True)


# ============================================================ PÁGINA 5 · TRADE LOG

elif page.startswith("05"):
    st.markdown('<div class="page-h1">Trade Log</div>'
                '<div class="page-sub">registro de órdenes ejecutadas</div>', unsafe_allow_html=True)

    log_path = os.path.join(ROOT, "logs", "trades.csv")
    if os.path.exists(log_path) and os.path.getsize(log_path) > 1:
        trades_df = pd.read_csv(log_path)
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])
        n_buy = int((trades_df["action"] == "BUY").sum())
        n_sell = int((trades_df["action"] == "SELL").sum())
        strip = "".join([
            kpi("Total órdenes", str(len(trades_df))),
            kpi("Compras", str(n_buy), "", "", "tone-pos"),
            kpi("Ventas", str(n_sell), "", "", "tone-neg"),
        ])
        st.markdown(f'<div class="kpi-strip" style="grid-template-columns:repeat(3,1fr)">{strip}</div>',
                    unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        tf = c1.multiselect("Ticker", sorted(trades_df["ticker"].unique()))
        af = c2.multiselect("Acción", ["BUY", "SELL"])
        df = trades_df.copy()
        if tf:
            df = df[df["ticker"].isin(tf)]
        if af:
            df = df[df["action"].isin(af)]
        st.dataframe(df.sort_values("timestamp", ascending=False),
                     use_container_width=True, hide_index=True)

        trades_df["month"] = trades_df["timestamp"].dt.to_period("M").astype(str)
        mc = trades_df.groupby("month").size().reset_index(name="count")
        fb = go.Figure(go.Bar(x=mc["month"], y=mc["count"], marker_color=PAL["accent-dim"]))
        T.fig_layout(fb, PAL, height=240)
        st.markdown('<div class="panel"><div class="panel-head"><div class="panel-title">'
                    'ÓRDENES POR MES</div></div>', unsafe_allow_html=True)
        st.plotly_chart(fb, use_container_width=True, config={"displayModeBar": False})
        st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown(panel("SIN REGISTROS",
                          '<div class="mrow"><span class="mrow-k">No hay trades todavía. '
                          'Ejecutá <b>python main.py execute</b> para registrar operaciones.</span></div>'),
                    unsafe_allow_html=True)
