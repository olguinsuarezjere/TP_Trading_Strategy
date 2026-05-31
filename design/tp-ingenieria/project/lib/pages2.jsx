/* pages2.jsx — Robustness + Live Portfolio + Trade Log. Exported to window. */
const { useState: useS2, useMemo: useMemo2 } = React;
const TT = window.TSMOM;
const FF = TT.fmt;

function RobustnessPage() {
  const [tab, setTab] = useS2("sens");
  const tabs = [
    { id: "sens", label: "SENSIBILIDAD" },
    { id: "stress", label: "STRESS TEST" },
    { id: "oos", label: "OUT-OF-SAMPLE" },
  ];

  return (
    <div className="page">
      <div className="page-head">
        <h1>Tests de Robustez</h1>
        <div className="page-sub">sensibilidad paramétrica · performance en crisis · validación out-of-sample</div>
      </div>

      <div className="tabbar">
        {tabs.map((t) => (
          <button key={t.id} className={`tab ${tab === t.id ? "on" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "sens" && (
        <div className="grid-2-eq">
          <Panel title="SHARPE POR LOOKBACK" sub="meses · pico en 12m">
            <BarChart data={TT.lookbackSens.map((d) => ({ label: `${d.lookback}`, value: d.sharpe }))}
                      height={240} fmt={(v) => v.toFixed(2)} highlight="12" />
            <div className="chart-note">El Sharpe es estable en el rango 9–18m; degrada con lookbacks muy cortos (ruido) o muy largos (señal rezagada).</div>
          </Panel>

          <Panel title="SHARPE vs COSTOS" sub="spread bid-ask">
            <BarChart data={TT.costSens.map((d) => ({ label: `${d.spread}bp`, value: d.sharpe, color: "var(--accent)" }))}
                      height={240} fmt={(v) => v.toFixed(2)} />
            <div className="chart-note">La estrategia tolera hasta ~20bps de spread antes de erosión material del Sharpe. Turnover mensual ≈ {FF.pct(TT.metrics.turnover, 1)}.</div>
          </Panel>

          <Panel title="SENSIBILIDAD AL TARGET VOL" className="span-2">
            <table className="dtable">
              <thead><tr><th>Target Vol</th><th>Vol Realizada</th><th>Ann Return</th><th>Sharpe</th><th>Tracking</th></tr></thead>
              <tbody>
                {TT.targetVolSens.map((d) => (
                  <tr key={d.target} className={Math.abs(d.target - 0.10) < 1e-6 ? "row-hi" : ""}>
                    <td className="mono">{FF.pct(d.target, 0)}</td>
                    <td className="mono">{FF.pct(d.realized, 1)}</td>
                    <td className="mono pos">{FF.pct(d.annRet, 1)}</td>
                    <td className="mono accent">{d.sharpe.toFixed(2)}</td>
                    <td className="mono dim">{FF.pct(Math.abs(d.realized - d.target), 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      )}

      {tab === "stress" && (
        <>
          <Panel title="EQUITY CURVE — PERÍODOS DE CRISIS SOMBREADOS" sub="escala log">
            <CrisisLineChart dates={TT.dates} values={TT.equityNet} crises={TT.crisisPerf} height={300} />
          </Panel>
          <Panel title="PERFORMANCE DURANTE CRISIS">
            <table className="dtable">
              <thead><tr><th>Período</th><th>Rango</th><th>Meses</th><th>Ann Return</th><th>Volatilidad</th><th>Sharpe</th><th>Max DD</th></tr></thead>
              <tbody>
                {TT.crisisPerf.map((c) => (
                  <tr key={c.name}>
                    <td><b>{c.name}</b></td>
                    <td className="mono dim">{c.start} → {c.end}</td>
                    <td className="mono">{c.months}</td>
                    <td className={`mono ${c.annRet >= 0 ? "pos" : "neg"}`}>{FF.pctSigned(c.annRet, 1)}</td>
                    <td className="mono">{FF.pct(c.vol, 1)}</td>
                    <td className={`mono ${c.sharpe >= 0 ? "accent" : "neg"}`}>{c.sharpe.toFixed(2)}</td>
                    <td className="mono neg">{FF.pct(c.maxDD, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="chart-note">El "crisis alpha" del trend-following es visible en el <b>Rate Shock 2022</b>: mientras equities y bonds caían en simultáneo, las señales cortas en renta fija capturaron el régimen.</div>
          </Panel>
        </>
      )}

      {tab === "oos" && (
        <div className="grid-2-eq">
          <Panel title="WALK-FORWARD — SHARPE OOS" sub="ventanas rolling 12m" className="span-2">
            <BarChart data={TT.walkForward.map((d) => ({ label: d.testStart, value: d.sharpe }))}
                      height={240} fmt={(v) => v.toFixed(2)} />
          </Panel>
          <Panel title="VENTANAS WALK-FORWARD">
            <table className="dtable">
              <thead><tr><th>Ventana</th><th>Test Start</th><th>Test End</th><th>Sharpe</th><th>Ann Ret</th></tr></thead>
              <tbody>
                {TT.walkForward.map((d) => (
                  <tr key={d.window}>
                    <td><b>{d.window}</b></td>
                    <td className="mono dim">{d.testStart}</td>
                    <td className="mono dim">{d.testEnd}</td>
                    <td className={`mono ${d.sharpe >= 0 ? "accent" : "neg"}`}>{d.sharpe.toFixed(2)}</td>
                    <td className={`mono ${d.annRet >= 0 ? "pos" : "neg"}`}>{FF.pctSigned(d.annRet, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="IN-SAMPLE vs OUT-OF-SAMPLE">
            <div className="oos-compare">
              <div className="oos-col">
                <div className="oos-tag">IN-SAMPLE</div>
                <div className="oos-big mono accent">{TT.oosCompare.inSampleSharpe.toFixed(2)}</div>
                <div className="oos-sub">Sharpe</div>
                <div className="oos-ret mono pos">{FF.pctSigned(TT.oosCompare.inSampleRet, 1)}</div>
              </div>
              <div className="oos-arrow">→</div>
              <div className="oos-col">
                <div className="oos-tag">OUT-OF-SAMPLE</div>
                <div className="oos-big mono accent">{TT.oosCompare.oosSharpe.toFixed(2)}</div>
                <div className="oos-sub">Sharpe</div>
                <div className="oos-ret mono pos">{FF.pctSigned(TT.oosCompare.oosRet, 1)}</div>
              </div>
            </div>
            <div className="chart-note">Decay del Sharpe OOS ≈ <b>{FF.pct(TT.oosCompare.decay, 0)}</b> — consistente con literatura de trend-following; sin sobreajuste evidente.</div>
          </Panel>
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------- Live
function LivePage() {
  const [connected, setConnected] = useS2(false);
  const [connecting, setConnecting] = useS2(false);
  const a = TT.account;

  const connect = () => {
    setConnecting(true);
    setTimeout(() => { setConnecting(false); setConnected(true); }, 1100);
  };

  const acColors = { equity: "var(--accent)", bond: "var(--c2)", commodity: "var(--c3)", currency: "var(--c4)" };
  const donutData = TT.acExposure.map((x) => ({ label: TT.AC_LABEL[x.ac], value: x.value, color: acColors[x.ac] }));

  return (
    <div className="page">
      <div className="page-head">
        <h1>Live Portfolio — <span className="dim">IBKR Paper Trading</span></h1>
        <div className="page-sub">cuenta paper · puerto 7497 · client-id 1</div>
      </div>

      {!connected ? (
        <Panel title="CONEXIÓN TWS">
          <div className="connect">
            <div className="connect-status">
              <span className={`dot ${connecting ? "dot-wait" : "dot-off"}`}></span>
              {connecting ? "ESTABLECIENDO SESIÓN API…" : "DESCONECTADO"}
            </div>
            <ol className="connect-steps">
              <li>TWS → Edit → Global Configuration → API → Settings</li>
              <li>✓ Enable ActiveX and Socket Clients</li>
              <li>Puerto <b>7497</b> (paper) · agregar <b>127.0.0.1</b> a Trusted IPs</li>
            </ol>
            <button className="bigbtn" onClick={connect} disabled={connecting}>
              {connecting ? "▣ CONECTANDO…" : "▶ CONECTAR Y ACTUALIZAR"}
            </button>
          </div>
        </Panel>
      ) : (
        <>
          <div className="kpi-strip k5">
            <Kpi label="NET LIQUIDATION" value={FF.usd(a.netLiq)} delta="USD" big />
            <Kpi label="CASH" value={FF.usd(a.cash)} delta={`${FF.pct(a.cash / a.netLiq, 0)} del NAV`} big />
            <Kpi label="UNREALIZED P&L" value={FF.usdSigned(a.totalUpnl)} delta="open positions" deltaTone={a.totalUpnl >= 0 ? "pos" : "neg"} big />
            <Kpi label="POSICIONES" value={`${a.nPositions}`} delta="activas" big />
            <Kpi label="GROSS EXPOSURE" value={FF.usd(a.grossExposure)} delta={`${(a.grossExposure / a.netLiq).toFixed(2)}× NAV`} big />
          </div>

          <div className="grid-1-2">
            <Panel title="EXPOSICIÓN POR CLASE">
              <div className="donut-wrap">
                <Donut data={donutData} size={168} />
                <div className="donut-legend">
                  {donutData.map((d) => (
                    <div key={d.label} className="dl-row">
                      <span className="dl-dot" style={{ background: d.color }}></span>
                      <span className="dl-name">{d.label}</span>
                      <span className="dl-val mono">{FF.pct(d.value / a.grossExposure, 0)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Panel>

            <Panel title="POSICIONES ABIERTAS" sub={`${TT.livePositions.length} activos`} flush>
              <div className="tbl-scroll">
                <table className="dtable sticky">
                  <thead><tr><th>Ticker</th><th>Clase</th><th>Dir</th><th>Qty</th><th>Precio</th><th>Market Value</th><th>Peso</th><th>uP&L</th></tr></thead>
                  <tbody>
                    {TT.livePositions.map((p) => (
                      <tr key={p.ticker}>
                        <td><b>{p.ticker}</b></td>
                        <td className="dim">{TT.AC_LABEL[p.ac]}</td>
                        <td><span className={`pill ${p.dir === 1 ? "pos" : "neg"}`}>{p.dir === 1 ? "LONG" : "SHORT"}</span></td>
                        <td className="mono">{p.qty.toLocaleString()}</td>
                        <td className="mono">{FF.usd(p.price, 2)}</td>
                        <td className="mono">{FF.usd(Math.abs(p.marketValue))}</td>
                        <td className="mono dim">{FF.pct(Math.abs(p.weight), 1)}</td>
                        <td className={`mono ${p.upnl >= 0 ? "pos" : "neg"}`}>{FF.usdSigned(p.upnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------- Trade Log
function TradesPage() {
  const [tk, setTk] = useS2("");
  const [act, setAct] = useS2("");
  const trades = TT.trades;
  const filtered = useMemo2(() => trades.filter((t) =>
    (!tk || t.ticker === tk) && (!act || t.action === act)), [tk, act, trades]);

  const buys = trades.filter((t) => t.action === "BUY").length;
  const sells = trades.length - buys;
  const monthKeys = Object.keys(TT.monthlyOrderCounts).sort();
  const barData = monthKeys.map((k) => ({ label: k.slice(2), value: TT.monthlyOrderCounts[k], color: "var(--accent)" }));
  const allTickers = [...new Set(trades.map((t) => t.ticker))].sort();
  const fmtTs = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Trade Log</h1>
        <div className="page-sub">logs/trades.csv · órdenes de rebalanceo · últimos 18 meses</div>
      </div>

      <div className="kpi-strip">
        <Kpi label="TOTAL ÓRDENES" value={`${trades.length}`} />
        <Kpi label="COMPRAS" value={`${buys}`} delta="BUY" deltaTone="pos" />
        <Kpi label="VENTAS" value={`${sells}`} delta="SELL" deltaTone="neg" />
        <Kpi label="FILL RATE" value={FF.pct(trades.filter((t) => t.status === "Filled").length / trades.length, 0)} delta="filled" deltaTone="accent" />
      </div>

      <Panel title="ÓRDENES POR MES" sub="conteo">
        <BarChart data={barData} height={170} fmt={(v) => `${v}`} />
      </Panel>

      <Panel title="OPERACIONES" flush
             right={
               <div className="filters">
                 <select value={tk} onChange={(e) => setTk(e.target.value)}>
                   <option value="">TICKER · TODOS</option>
                   {allTickers.map((t) => <option key={t} value={t}>{t}</option>)}
                 </select>
                 <select value={act} onChange={(e) => setAct(e.target.value)}>
                   <option value="">ACCIÓN · TODAS</option>
                   <option value="BUY">BUY</option>
                   <option value="SELL">SELL</option>
                 </select>
                 {(tk || act) && <button className="tbtn" onClick={() => { setTk(""); setAct(""); }}>✕ CLEAR</button>}
               </div>
             }>
        <div className="tbl-scroll tall">
          <table className="dtable sticky">
            <thead><tr><th>Timestamp</th><th>Ticker</th><th>Acción</th><th>Qty</th><th>Tipo</th><th>Limit Price</th><th>Status</th></tr></thead>
            <tbody>
              {filtered.map((t, i) => (
                <tr key={i}>
                  <td className="mono dim">{fmtTs(t.timestamp)}</td>
                  <td><b>{t.ticker}</b></td>
                  <td><span className={`pill ${t.action === "BUY" ? "pos" : "neg"}`}>{t.action}</span></td>
                  <td className="mono">{t.qty.toLocaleString()}</td>
                  <td className="mono dim">{t.orderType}</td>
                  <td className="mono">{t.limitPrice ? FF.usd(t.limitPrice, 2) : "—"}</td>
                  <td><span className={`status ${t.status === "Filled" ? "ok" : "wait"}`}>{t.status}</span></td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan="7" className="empty-row">Sin órdenes para los filtros seleccionados.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="tbl-foot">{filtered.length} de {trades.length} órdenes</div>
      </Panel>
    </div>
  );
}

Object.assign(window, { RobustnessPage, LivePage, TradesPage });
