# TSMOM Terminal — Dashboard

Dashboard interactivo estilo **Bloomberg Terminal** (dark, monospace, verde fósforo)
para la estrategia **Time Series Momentum (TSMOM)** del TP de Ingeniería Financiera
(F414 — UdeSA).

Está **conectado al backend real** del proyecto: lee los precios de
`Data/etf_prices.parquet`, corre el backtest y muestra señales, métricas, robustez,
portfolio en vivo (IBKR paper) y el log de trades.

> ℹ️ Este dashboard fue desarrollado con la asistencia de un **agente de IA
> (Claude Code)**, partiendo de un mockup hecho en Claude Design. El prototipo
> original de referencia (HTML/CSS/JSX + screenshots) quedó guardado en `design/`.

---

## 1. Cómo correrlo

El proyecto necesita **Python 3.13** con `pandas ≥ 2.2`. En las compus del equipo eso
está en el entorno conda **`finance`** (¡ojo!: el `python3`/anaconda base por defecto es
3.11 con pandas viejo y **rompe** el loader por la frecuencia `"ME"`).

```bash
# 1. activar el entorno correcto
conda activate finance

# 2. instalar dependencias (si hace falta)
pip install -r requirements.txt

# 3. levantar el dashboard
streamlit run src/dashboard/app.py
```

Se abre solo en el navegador en **http://localhost:8501**.
Si la pestaña ya estaba abierta, refrescá con `Cmd/Ctrl + R`.

> Si `streamlit run` usa el Python equivocado, corré explícito:
> `python -m streamlit run src/dashboard/app.py` con el `python` del env `finance`.

---

## 2. Estructura del código del dashboard

```
src/dashboard/
├── app.py        # la app Streamlit: layout, 6 páginas, wiring al backend
└── theme.py      # paleta + CSS estilo terminal (3 temas) + helpers de Plotly
.streamlit/
└── config.toml   # tema base oscuro de Streamlit
design/            # prototipo original de Claude Design (referencia visual)
```

### `theme.py` — el look
- `PALETTES`: tokens de color de los 3 temas (`phosphor` verde, `amber` ámbar,
  `ice` azul). Sacados 1:1 del `styles.css` del diseño original.
- `inject(theme)`: devuelve el `<style>` completo (oculta el chrome de Streamlit,
  define la tipografía *IBM Plex Mono*, y estiliza paneles, KPIs, matriz de señales,
  sidebar, tabs, etc.).
- `fig_layout(fig, pal, ...)`: aplica el tema oscuro a cualquier figura Plotly.
- `rgba(hex, alpha)`: convierte un color hex a `rgba(...)` (Plotly no acepta hex de
  8 dígitos para transparencias).

### `app.py` — la app
Arriba define helpers de presentación (`kpi`, `panel`, `topbar`, `sparkline`, formatos
`pct`/`num`/`usd`). Después arma el sidebar (navegación + parámetros + selector de
tema) y enrutado por página. **Toda la data sale del backend real** vía funciones
cacheadas con `@st.cache_data`.

---

## 3. Las 6 páginas y de dónde sale cada dato

| Página | Qué muestra | Funciones del backend que usa |
|--------|-------------|-------------------------------|
| **01 Overview** | Matriz de señales TSMOM por clase de activo (intensidad = fuerza de tendencia), NAV desde inicio + sparkline, exposición por clase. | `compute_tsmom_signal`, `compute_signal_strength`, `BacktestEngine` |
| **02 Backtest** | KPIs (Sharpe, Ann. Return, Vol, MaxDD, Calmar), curva de capital neto vs bruto (log), drawdown, heatmap de retornos mensuales, tabla de métricas. | `BacktestEngine`, `src.backtest.metrics.*` |
| **03 Robustness** | Sensibilidad a lookback / costos / target-vol, equity con crisis sombreadas, walk-forward y comparación in-sample vs out-of-sample. | `lookback_sensitivity`, `cost_sensitivity`, `target_vol_sensitivity`, `analyze_crisis_performance`, `walk_forward`, `expanding_window` |
| **04 Live Portfolio** | Panel de **horario de mercado US** en tiempo real (abierto/extendido/cerrado, sesión regular y extendida en ET + hora local); panel de conexión a IBKR paper (estado, cuenta, servidor, ETFs operables); ciclo de vida de la estrategia (Iniciar / Pausar / Reanudar / Detener); detección de rebalanceo pendiente (catch-up) al reconectar; auto-trade opcional; portafolio en vivo, drift, rebalanceo manual y kill switch (cierra por contrato exacto). | `src.broker.*` (`state`, `runner`, `orders`, `monitor`, `session`, `market_hours`) |
| **05 Trade Log** | Órdenes registradas en `logs/trades.csv` + actividad por mes. | lee `logs/trades.csv` |
| **06 Rebalances** | Historial de cada evento de rebalanceo / corte (`logs/rebalances.csv`) con sus parámetros, y las órdenes de cada uno. | lee `logs/rebalances.csv` + `logs/trades.csv` |

### Parámetros (sidebar)
- **Lookback** (3–24 meses)
- **Target Vol** anual (5%–**40%**)
- **Señal**: `binary` (signo del momentum) o `strength` (continua, normalizada por vol)
- **Tema**: phosphor / amber / ice

---

## 3.1 Operar en vivo: el ciclo de vida de la estrategia (página 04)

El dashboard es solo una **ventana**. Las **posiciones reales viven en IBKR** y la
**intención de la estrategia** (si está corriendo, con qué params, y cuándo rebalanceó
por última vez) vive en `logs/strategy_state.json`. Por eso podés **cerrar el dashboard
y reconectar al día siguiente**: IBKR mantiene tus posiciones y el estado sobrevive en
disco.

**Máquina de estados** (`src/broker/state.py`):

```
   DETENIDA  --Iniciar-->  ACTIVA  <--Reanudar-- PAUSADA
      ^                       |  ^                   ^
      |                   Pausar  \--Reanudar       /
      +--- Detener y cerrar todo (kill) <----------+
```

- **DETENIDA**: no enrolada. Botón **▶ Iniciar estrategia**.
- **ACTIVA**: opera. Rebalanceo **mensual** (señal TSMOM, lookback 12m). Botón **⏸ Pausar**.
- **PAUSADA**: mantiene posiciones pero no opera. Botón **▶ Reanudar**.
- **Kill switch** (⛔ Detener y cerrar todo): cierra todo a mercado y pasa a DETENIDA.

**Rebalanceo mensual + catch-up.** La estrategia rebalancea **una vez por mes** (estándar
de la literatura TSMOM: Moskowitz et al. 2012, Baz et al. 2015, Moreira & Muir 2017,
Daniel & Moskowitz 2016). El dashboard *chequea* seguido (auto-refresh) si toca, pero
*ejecuta* a lo sumo una vez al mes. Si pasó un cambio de mes mientras estabas
desconectado, al reconectar aparece un aviso de **REBALANCEO PENDIENTE** con un botón
para ejecutarlo (catch-up con confirmación).

**Auto-trade (opcional).** El toggle **⚡ Auto-trade** ejecuta el rebalanceo mensual solo
(sin confirmar) cuando empieza un mes nuevo y la estrategia está ACTIVA. Respeta la pausa
y el kill switch. Apagado por default.

**Equivalente por CLI** (mismo backend; apto para un cron a futuro):

```bash
python main.py start-strategy      # enrola (ACTIVA)
python main.py strategy-status     # ver estado / si hay rebalanceo pendiente
python main.py tick                # chequea y, si toca, rebalancea (--force / --dry-run)
python main.py halt                # pausar
python main.py resume              # reanudar
python main.py close-all --execute # kill switch (cierra todo y detiene)
```

---

## 4. Cómo conectar trabajo nuevo del equipo

El dashboard es una **capa de presentación**: consume las funciones de `src/`. Si
mejoran la estrategia, el backtest o la robustez, **el dashboard toma los cambios
automáticamente** mientras se mantengan las firmas de estas funciones:

- `src/data/loader.py::load_returns(config) -> DataFrame`
- `src/strategy/signals.py::compute_tsmom_signal / compute_signal_strength`
- `src/strategy/portfolio.py::build_portfolio(returns, config, ...)`
- `src/backtest/engine.py::BacktestEngine.run(returns, ...) -> BacktestResults`
- `src/robustness/*` (sensibilidad, stress test, out-of-sample)

**Para agregar una visualización nueva** en `app.py`:
1. Conseguí los datos llamando a la función correspondiente de `src/`.
2. Armá la figura con Plotly y pasala por `T.fig_layout(fig, PAL, height=...)`.
3. Usá los helpers `panel(...)`, `kpi(...)` para mantener el estilo terminal.
4. Para rellenos translúcidos usá `T.rgba(PAL["accent"], 0.1)` (no hex de 8 dígitos).

La configuración de la estrategia vive en `config.yaml` (lookback, target vol, costos,
ventana de backtest, datos, broker).

---

## 5. Problemas comunes

- **`ValueError: Invalid frequency: ME`** → estás corriendo con Python 3.11 / pandas
  viejo. Usá el env `finance` (Python 3.13, pandas ≥ 2.2).
- **Las métricas dan distinto / cargan menos activos** → el loader descarta activos sin
  suficiente historia en la ventana 2015–2024. Es esperable según los datos del parquet.
- **No veo los cambios** → Streamlit no auto-recarga; refrescá el navegador o reiniciá
  `streamlit run`.
