/* TSMOM Terminal — synthetic but self-consistent data engine.
   All numbers derive from one seeded monthly return series so metrics
   (Sharpe, Calmar, drawdowns, heatmap, crises) agree with each other.   */
(function () {
  "use strict";

  // --- deterministic PRNG (mulberry32) --------------------------------------
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const rng = mulberry32(20260528);
  // standard normal via Box–Muller
  function randn() {
    let u = 0, v = 0;
    while (u === 0) u = rng();
    while (v === 0) v = rng();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  // --- monthly return series 2015-01 .. 2024-12 (120 months) ----------------
  // Regime drift encodes the trend-following narrative.
  const START_YEAR = 2015;
  const N = 120;
  const dates = [];
  for (let i = 0; i < N; i++) {
    const y = START_YEAR + Math.floor(i / 12);
    const m = (i % 12) + 1;
    dates.push({ y, m, label: `${y}-${String(m).padStart(2, "0")}` });
  }

  function regimeDrift(i) {
    const y = START_YEAR + Math.floor(i / 12);
    if (y <= 2017) return 0.0010;        // choppy, mild — sets up early drawdown
    if (y === 2018) return 0.0050;       // Q4 selloff handled well late
    if (y === 2019) return 0.0060;
    if (y === 2020) return 0.0050;       // COVID whipsaw, modest
    if (y === 2021) return 0.0080;
    if (y === 2022) return 0.0180;       // rate shock — banner year
    if (y === 2023) return 0.0070;
    return 0.0100;                       // 2024
  }
  function regimeVol(i) {
    const y = START_YEAR + Math.floor(i / 12);
    if (y === 2020) return 0.040;        // covid vol spike
    if (y === 2022) return 0.034;
    return 0.026;
  }

  const netRet = [];
  const grossRet = [];
  for (let i = 0; i < N; i++) {
    let r = regimeDrift(i) + randn() * regimeVol(i);
    // a couple of signature months
    if (dates[i].label === "2020-03") r = -0.031;  // covid drawdown
    if (dates[i].label === "2022-06") r = 0.061;    // big trend month
    if (dates[i].label === "2022-09") r = 0.048;
    if (dates[i].label === "2015-08") r = -0.038;   // china deval
    netRet.push(r);
    grossRet.push(r + 0.0011);            // costs drag ~11bps/mo
  }

  // --- metric helpers -------------------------------------------------------
  const mean = (a) => a.reduce((s, x) => s + x, 0) / a.length;
  const std = (a) => {
    const m = mean(a);
    return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1));
  };
  function cumprod(rets) {
    const out = []; let v = 1;
    for (const r of rets) { v *= (1 + r); out.push(v); }
    return out;
  }
  function annReturn(rets) {
    const prod = rets.reduce((p, r) => p * (1 + r), 1);
    return Math.pow(prod, 12 / rets.length) - 1;
  }
  const annVol = (rets) => std(rets) * Math.sqrt(12);
  const sharpe = (rets) => (mean(rets) / std(rets)) * Math.sqrt(12);
  function sortino(rets) {
    const dn = rets.filter((r) => r < 0);
    return (mean(rets) / std(dn)) * Math.sqrt(12);
  }
  function maxDrawdown(rets) {
    const cum = cumprod(rets); let peak = -Infinity, mdd = 0;
    for (const v of cum) { peak = Math.max(peak, v); mdd = Math.min(mdd, (v - peak) / peak); }
    return mdd;
  }
  function ddSeries(rets) {
    const cum = cumprod(rets); let peak = -Infinity; const out = [];
    for (const v of cum) { peak = Math.max(peak, v); out.push((v - peak) / peak); }
    return out;
  }
  const calmar = (rets) => annReturn(rets) / Math.abs(maxDrawdown(rets));
  const hitRate = (rets) => rets.filter((r) => r > 0).length / rets.length;

  const equityNet = cumprod(netRet);
  const equityGross = cumprod(grossRet);
  const drawdown = ddSeries(netRet);

  const metrics = {
    sharpe: sharpe(netRet),
    sortino: sortino(netRet),
    annReturn: annReturn(netRet),
    annVol: annVol(netRet),
    maxDD: maxDrawdown(netRet),
    calmar: calmar(netRet),
    hitRate: hitRate(netRet),
    months: N,
    turnover: 0.182,
  };

  // --- ETF universe (from repo) --------------------------------------------
  const UNIVERSE = {
    SPY: "equity", QQQ: "equity", IWM: "equity", MDY: "equity", DIA: "equity",
    VTI: "equity", IVV: "equity", VOO: "equity", EFA: "equity", EEM: "equity",
    VEA: "equity", VWO: "equity", EWJ: "equity", EWG: "equity", EWU: "equity",
    EWZ: "equity", EWC: "equity", EWA: "equity", EWH: "equity", EWS: "equity",
    EWL: "equity", EWP: "equity", EWI: "equity", EWQ: "equity", EWD: "equity",
    EWN: "equity", EWK: "equity", XLF: "equity", XLE: "equity", XLK: "equity",
    XLV: "equity", XLI: "equity", XLY: "equity", XLP: "equity", XLU: "equity",
    XLB: "equity", XLRE: "equity",
    TLT: "bond", IEF: "bond", SHY: "bond", AGG: "bond", LQD: "bond",
    HYG: "bond", TIP: "bond", BND: "bond", BNDX: "bond", EMB: "bond",
    GLD: "commodity", SLV: "commodity", USO: "commodity", UNG: "commodity",
    DBA: "commodity", DBB: "commodity", DBC: "commodity", PDBC: "commodity",
    CORN: "commodity", WEAT: "commodity", SOYB: "commodity", CANE: "commodity",
    CPER: "commodity",
    UUP: "currency", FXE: "currency", FXB: "currency", FXY: "currency",
    FXA: "currency", FXC: "currency", FXF: "currency",
  };
  const ASSET_CLASSES = ["equity", "bond", "commodity", "currency"];
  const AC_LABEL = { equity: "Equities", bond: "Bonds", commodity: "Commodities", currency: "Currencies" };

  // current signals: strength in [-3,3], direction = sign
  const sigRng = mulberry32(7777);
  const signals = Object.keys(UNIVERSE).map((ticker) => {
    const ac = UNIVERSE[ticker];
    // bias: bonds mostly short (2024 rate regime), commodities mixed, equities long
    let bias = 0;
    if (ac === "equity") bias = 0.9;
    else if (ac === "bond") bias = -0.8;
    else if (ac === "commodity") bias = 0.3;
    else bias = 0.2;
    const raw = bias + (sigRng() - 0.5) * 3.4;
    const strength = Math.max(-3, Math.min(3, raw));
    return { ticker, ac, strength, dir: strength >= 0 ? 1 : -1 };
  });
  const nLong = signals.filter((s) => s.dir === 1).length;
  const nShort = signals.length - nLong;
  const netExposure = (nLong - nShort) / signals.length;

  // --- robustness: lookback sensitivity ------------------------------------
  const lookbackSens = [3, 6, 9, 12, 15, 18, 24].map((lb) => {
    // peak around 12; degrade at extremes
    const base = metrics.sharpe;
    const penalty = Math.abs(lb - 12) * 0.028 + (lb <= 3 ? 0.18 : 0);
    return { lookback: lb, sharpe: +(base - penalty + (lb === 12 ? 0.02 : 0)).toFixed(2) };
  });

  const targetVolSens = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.40].map((tv) => {
    const realized = tv * (0.97 + (rng() - 0.5) * 0.06);
    return {
      target: tv,
      realized: +realized.toFixed(3),
      sharpe: +(metrics.sharpe - Math.abs(tv - 0.10) * 0.9).toFixed(2),
      annRet: +(annReturn(netRet) * (tv / 0.10)).toFixed(3),
    };
  });

  const costSens = [0, 5, 10, 20, 50].map((bps) => ({
    spread: bps,
    sharpe: +(metrics.sharpe - bps * 0.0042).toFixed(2),
  }));

  // crisis windows that intersect 2015-2024
  function windowSlice(startLabel, endLabel) {
    const si = dates.findIndex((d) => d.label >= startLabel);
    let ei = dates.findIndex((d) => d.label > endLabel);
    if (ei === -1) ei = N;
    return { rets: netRet.slice(si, ei), si, ei };
  }
  const CRISES = [
    { name: "China Devaluation", start: "2015-07", end: "2016-02" },
    { name: "Q4 Selloff", start: "2018-10", end: "2018-12" },
    { name: "COVID-19", start: "2020-02", end: "2020-09" },
    { name: "Rate Shock", start: "2022-01", end: "2022-12" },
  ];
  const crisisPerf = CRISES.map((c) => {
    const { rets, si, ei } = windowSlice(c.start, c.end);
    return {
      name: c.name, start: c.start, end: c.end,
      annRet: annReturn(rets), vol: annVol(rets), sharpe: sharpe(rets),
      maxDD: maxDrawdown(rets), months: rets.length, si, ei,
    };
  });

  // walk-forward OOS windows
  const walkForward = [];
  for (let k = 0; k < 6; k++) {
    const startIdx = 36 + k * 12;
    if (startIdx + 12 > N) break;
    const seg = netRet.slice(startIdx, startIdx + 12);
    walkForward.push({
      window: `WF-${k + 1}`,
      testStart: dates[startIdx].label,
      testEnd: dates[startIdx + 11].label,
      sharpe: +sharpe(seg).toFixed(2),
      annRet: +annReturn(seg).toFixed(3),
    });
  }
  const oosCompare = {
    inSampleSharpe: +(metrics.sharpe + 0.14).toFixed(2),
    oosSharpe: +(metrics.sharpe - 0.09).toFixed(2),
    inSampleRet: +(annReturn(netRet) + 0.012).toFixed(3),
    oosRet: +(annReturn(netRet) - 0.008).toFixed(3),
    decay: 0.23,
  };

  // --- live portfolio (simulated IBKR paper) -------------------------------
  const initialCapital = 1000000;
  const navMultiple = equityNet[equityNet.length - 1];
  const netLiq = initialCapital * navMultiple;
  // pick ~26 strongest-conviction names as live positions
  const liveRng = mulberry32(13);
  const livePositions = signals
    .slice()
    .sort((a, b) => Math.abs(b.strength) - Math.abs(a.strength))
    .slice(0, 26)
    .map((s) => {
      const price = +(40 + liveRng() * 380).toFixed(2);
      const targetW = (s.strength / 3) * 0.13;
      const mv = targetW * netLiq;
      const qty = Math.round(mv / price);
      const upnl = mv * (liveRng() - 0.42) * 0.09;
      return {
        ticker: s.ticker, ac: s.ac, dir: s.dir, qty,
        price, marketValue: mv, weight: targetW, upnl,
      };
    })
    .sort((a, b) => Math.abs(b.marketValue) - Math.abs(a.marketValue));
  const totalUpnl = livePositions.reduce((s, p) => s + p.upnl, 0);
  const grossExposure = livePositions.reduce((s, p) => s + Math.abs(p.marketValue), 0);
  const acExposure = ASSET_CLASSES.map((ac) => ({
    ac,
    value: livePositions.filter((p) => p.ac === ac).reduce((s, p) => s + Math.abs(p.marketValue), 0),
  })).filter((x) => x.value > 0);
  const account = {
    netLiq, cash: netLiq - livePositions.reduce((s, p) => s + p.marketValue, 0) * 0.0,
    totalUpnl, nPositions: livePositions.length,
    grossExposure, netExposureUsd: livePositions.reduce((s, p) => s + p.marketValue, 0),
    buyingPower: netLiq * 2,
  };
  account.cash = netLiq * 0.34;

  // --- trade log -----------------------------------------------------------
  const tradeRng = mulberry32(99);
  const tickers = Object.keys(UNIVERSE);
  const trades = [];
  // monthly rebalances over last 18 months, a handful of orders each
  for (let mo = 18; mo >= 1; mo--) {
    const d = new Date(2024, 12 - 1, 1);
    d.setMonth(d.getMonth() - mo + 1);
    const nOrders = 2 + Math.floor(tradeRng() * 5);
    for (let o = 0; o < nOrders; o++) {
      const tk = tickers[Math.floor(tradeRng() * tickers.length)];
      const action = tradeRng() > 0.5 ? "BUY" : "SELL";
      const day = 1 + Math.floor(tradeRng() * 3); // rebalance early in month
      const ts = new Date(d.getFullYear(), d.getMonth(), day, 9 + Math.floor(tradeRng() * 7), Math.floor(tradeRng() * 60));
      const isLmt = tradeRng() > 0.6;
      const price = +(40 + tradeRng() * 380).toFixed(2);
      trades.push({
        timestamp: ts,
        ticker: tk,
        action,
        qty: 50 + Math.floor(tradeRng() * 1200),
        orderType: isLmt ? "LMT" : "MKT",
        limitPrice: isLmt ? price : null,
        status: tradeRng() > 0.08 ? "Filled" : "Submitted",
      });
    }
  }
  trades.sort((a, b) => b.timestamp - a.timestamp);
  const monthlyOrderCounts = {};
  trades.forEach((t) => {
    const k = `${t.timestamp.getFullYear()}-${String(t.timestamp.getMonth() + 1).padStart(2, "0")}`;
    monthlyOrderCounts[k] = (monthlyOrderCounts[k] || 0) + 1;
  });

  // monthly returns matrix for heatmap [year][month]
  const years = [...new Set(dates.map((d) => d.y))];
  const heatmap = years.map((y) => ({
    year: y,
    months: Array.from({ length: 12 }, (_, m) => {
      const idx = dates.findIndex((d) => d.y === y && d.m === m + 1);
      return idx === -1 ? null : netRet[idx];
    }),
  }));

  // --- config (from repo) ---------------------------------------------------
  const config = {
    lookback: 12, targetVol: 0.10, rebalancing: "monthly",
    maxWeight: 0.15, volComMonths: 3, bidAsk: 0.001, commission: 0.0005,
    start: "2015-01-01", end: "2024-12-31", initialCapital: 1000000,
  };

  window.TSMOM = {
    dates, netRet, grossRet, equityNet, equityGross, drawdown, metrics,
    UNIVERSE, ASSET_CLASSES, AC_LABEL, signals, nLong, nShort, netExposure,
    lookbackSens, targetVolSens, costSens, CRISES, crisisPerf, walkForward,
    oosCompare, livePositions, account, acExposure, trades, monthlyOrderCounts,
    heatmap, years, config,
    fmt: {
      pct: (x, d = 2) => `${(x * 100).toFixed(d)}%`,
      pctSigned: (x, d = 2) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(d)}%`,
      num: (x, d = 2) => x.toFixed(d),
      usd: (x, d = 0) => `$${x.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`,
      usdSigned: (x) => `${x >= 0 ? "+" : "−"}$${Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 })}`,
    },
  };
})();
