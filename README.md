# Time Series Momentum Trading System

**Ingeniería Financiera F414 — Universidad de San Andrés (2026)**

Sistema de trading cuantitativo basado en la estrategia **Time Series Momentum (TSMOM)**
sobre un universo de 133 ETFs (curados de 205 por liquidez; equities, bonds, commodities, currencies).

---

## Instalación

```bash
pip install -r requirements.txt
```

## Uso rápido

```bash
# Correr el backtest (usa parámetros de config.yaml)
python main.py backtest

# Lanzar el dashboard interactivo
python main.py dashboard

# Ver las órdenes del próximo rebalanceo (sin ejecutar)
python main.py execute --dry-run

# Todos los comandos disponibles
python main.py --help
```

## Comandos CLI

| Comando | Descripción |
|---------|-------------|
| `python main.py update-data` | Descarga precios actualizados de yfinance |
| `python main.py backtest` | Backtest histórico con métricas de performance |
| `python main.py backtest --lookback 9 --signal strength` | Backtest con parámetros custom |
| `python main.py robustness --test all` | Sensibilidad + stress + out-of-sample |
| `python main.py dashboard` | Dashboard Streamlit en `localhost:8501` |
| `python main.py execute --dry-run` | Simula órdenes del rebalanceo sin ejecutar |
| `python main.py execute` | Ejecuta rebalanceo en IBKR TWS paper |
| `python main.py monitor` | Monitorea el portfolio en tiempo real |

## Estructura del proyecto

```
├── main.py                  # CLI (Click)
├── config.yaml              # Parámetros centrales
├── requirements.txt
├── TP_walkthrough.ipynb     # Documentación completa del proyecto (notebook único)
├── Data/
│   └── etf_prices.parquet   # Precios históricos (2012–hoy)
├── src/
│   ├── data/                # Carga y universo de ETFs
│   ├── strategy/            # Señales TSMOM y vol-scaling
│   ├── backtest/            # Engine, costos y métricas
│   ├── robustness/          # Sensibilidad, stress, OOS
│   ├── broker/              # Integración IBKR (ib_insync)
│   └── dashboard/           # App Streamlit (6 páginas)
└── logs/
    └── trades.csv           # Log de operaciones
```

## Referencias bibliográficas

1. **[L]** Moskowitz, T.J., Ooi, Y.H. & Pedersen, L.H. (2012). *Time Series Momentum*. Journal of Financial Economics, 104(2), 228–250.
2. **[H]** Baz, J., Granger, N., Harvey, C.R., Le Roux, N. & Rattray, S. (2015). *Dissecting Investment Strategies in the Cross Section and Time Series*.
3. Hurst, B., Ooi, Y.H. & Pedersen, L.H. (2017). *A Century of Evidence on Trend-Following Investing*. Journal of Portfolio Management, 44(1), 15–29.
4. Barroso, P. & Santa-Clara, P. (2015). *Momentum Has Its Moments*. Journal of Financial Economics, 116(1), 111–120.

## Conexión a IBKR Paper Trading

1. Abrir TWS → Edit → Global Configuration → API → Settings
2. Activar *Enable ActiveX and Socket Clients*
3. Puerto: **7497** (paper) — nunca usar 7496 (real) para testing
4. Agregar `127.0.0.1` a Trusted IPs
5. `python main.py monitor`
