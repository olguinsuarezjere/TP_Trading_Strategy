/* app.jsx — shell, state, theme/tweaks, mount. */
const { useState: useSA, useEffect: useEffectA } = React;

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "phosphor",
  "density": "regular",
  "scanlines": true,
  "gridlines": true,
  "fontScale": 100
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [page, setPage] = useSA("overview");
  const [params, setParams] = useSA({ lookback: 12, targetVol: 0.10, signal: "binary" });

  useEffectA(() => {
    const r = document.documentElement;
    r.setAttribute("data-theme", t.theme);
    r.setAttribute("data-density", t.density);
    r.setAttribute("data-scanlines", t.scanlines ? "on" : "off");
    r.setAttribute("data-gridlines", t.gridlines ? "on" : "off");
    r.style.setProperty("--font-scale", (t.fontScale / 100).toString());
  }, [t]);

  const PAGES = {
    overview: <OverviewPage params={params} />,
    backtest: <BacktestPage params={params} />,
    robustness: <RobustnessPage />,
    live: <LivePage />,
    trades: <TradesPage />,
  };

  return (
    <div className="shell">
      <StatusBar params={params} />
      <div className="body">
        <Sidebar page={page} setPage={setPage} params={params} setParams={setParams} />
        <main className="content">{PAGES[page]}</main>
      </div>

      <TweaksPanel>
        <TweakSection label="Estilo visual" />
        <TweakRadio label="Tema" value={t.theme}
                    options={["phosphor", "amber", "ice"]}
                    onChange={(v) => setTweak("theme", v)} />
        <div className="theme-hint">
          phosphor = verde fósforo · amber = CRT ámbar · ice = azul hielo
        </div>
        <TweakSection label="Densidad & textura" />
        <TweakRadio label="Densidad" value={t.density}
                    options={["compact", "regular", "comfy"]}
                    onChange={(v) => setTweak("density", v)} />
        <TweakToggle label="Scanlines CRT" value={t.scanlines}
                     onChange={(v) => setTweak("scanlines", v)} />
        <TweakToggle label="Líneas de grilla" value={t.gridlines}
                     onChange={(v) => setTweak("gridlines", v)} />
        <TweakSlider label="Tamaño de fuente" value={t.fontScale} min={85} max={120} step={5} unit="%"
                     onChange={(v) => setTweak("fontScale", v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
