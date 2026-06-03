"""
Universo de ETFs — única fuente de verdad del proyecto.

Reglas del universo (para que el backtest sea representativo de lo que se puede
ejecutar de verdad en Interactive Brokers):

  1. Todos los ETFs son US-listed y denominados en USD. No se incluyen ETFs
     extranjeros (.MI de Milán, .TO de Toronto, etc.) porque sus retornos
     mezclan el movimiento del activo con el del tipo de cambio EUR/CAD vs USD,
     lo que contamina una estrategia 100% en USD.
  2. Se incluyen ETFs sin importar cuándo arrancaron: cada uno se usa DESDE SU
     INCEPTION. Los meses previos a que existiera quedan NaN y el pipeline los
     trata como "activo inactivo" (peso 0), sin lookahead. El único requisito es
     tener historia mínima para formar señal (data.min_history_months en
     config.yaml). scripts/fetch_missing_etfs.py valida USD + historia mínima;
     lo que no pasa NO entra acá.
  3. La clase de activo de cada ticker se usa para (a) el dashboard y (b) el
     weighting 'class_balanced' (presupuesto igual por clase). Con el default
     'pooled' (1/N global) la clase solo afecta la visualización.
  4. CURACIÓN POR LIQUIDEZ (corr >= 0.95): siguiendo Moskowitz et al. (2012), que
     usa 1 instrumento líquido por mercado, agrupamos los ETFs por correlación de
     retornos mensuales (complete-linkage, corr >= 0.95 = "mismo mercado") y nos
     quedamos con el MÁS LÍQUIDO de cada grupo (mayor dollar-volume). Los 72
     redundantes están en REDUNDANT_TICKERS (con el ticker que los reemplaza) y se
     filtran del universo activo. ETF_UNIVERSE pasa de 205 a 133 mercados distintos.
     Análisis: scripts/universe_redundancy.py · comparación: scripts/compare_universe_backtest.py
     Para volver a los 205, basta vaciar REDUNDANT_TICKERS (los datos siguen en el parquet).

Mantener sincronizado con el parquet: `python main.py data-status` muestra si
universe.py y Data/etf_prices.parquet quedaron desalineados, y
`python main.py update-data` / scripts/fetch_missing_etfs.py descarga lo que
falte.
"""

# Universo crudo (205 ETFs US-listed en USD). ETF_UNIVERSE se deriva de acá
# filtrando los redundantes (ver REDUNDANT_TICKERS más abajo).
_ALL_ETFS: dict[str, str] = {
    # ===================================================================
    # EQUITY
    # ===================================================================
    # --- US large cap / total market ---
    "SPY":  "equity", "IVV":  "equity", "VOO":  "equity", "VTI":  "equity",
    "ITOT": "equity", "QQQ":  "equity", "DIA":  "equity", "OEF":  "equity",
    "RSP":  "equity", "IWB":  "equity",
    # --- US mid / small cap ---
    "IWM":  "equity", "IJR":  "equity", "MDY":  "equity", "IJH":  "equity",
    "VO":   "equity", "VB":   "equity",
    # --- US style (value / growth) ---
    "VTV":  "equity", "VUG":  "equity", "IWD":  "equity", "IWF":  "equity",
    "IWN":  "equity", "IWO":  "equity", "VBR":  "equity", "VBK":  "equity",
    # --- US factors ---
    "MTUM": "equity", "QUAL": "equity", "VLUE": "equity", "USMV": "equity",
    "SIZE": "equity", "SPLV": "equity", "SPHB": "equity", "MOAT": "equity",
    "VIG":  "equity", "VYM":  "equity", "SDY":  "equity", "NOBL": "equity",
    "DGRO": "equity", "SCHD": "equity",
    # --- US sectors (SPDR Select, los 11) ---
    "XLF":  "equity", "XLE":  "equity", "XLK":  "equity", "XLV":  "equity",
    "XLI":  "equity", "XLY":  "equity", "XLP":  "equity", "XLU":  "equity",
    "XLB":  "equity", "XLRE": "equity", "XLC":  "equity",
    # --- US industries / thematic ---
    "SMH":  "equity", "SOXX": "equity", "IBB":  "equity", "XBI":  "equity",
    "KRE":  "equity", "KBE":  "equity", "ITB":  "equity", "XHB":  "equity",
    "KIE":  "equity", "OIH":  "equity", "XOP":  "equity", "XME":  "equity",
    "GDX":  "equity", "GDXJ": "equity", "SIL":  "equity", "URA":  "equity",
    "TAN":  "equity", "ICLN": "equity", "WOOD": "equity", "MOO":  "equity",
    "IYT":  "equity", "ITA":  "equity", "SKYY": "equity", "IGV":  "equity",
    "FDN":  "equity", "XRT":  "equity", "IHI":  "equity", "JETS": "equity",
    "HACK": "equity", "CIBR": "equity", "KWEB": "equity", "BOTZ": "equity",
    "LIT":  "equity", "REMX": "equity", "COPX": "equity",
    # --- US real estate (REIT) ---
    "IYR":  "equity", "VNQ":  "equity", "SCHH": "equity", "REZ":  "equity",
    "REM":  "equity",
    # --- International developed ---
    "EFA":  "equity", "IEFA": "equity", "VEA":  "equity", "VGK":  "equity",
    "EZU":  "equity", "FEZ":  "equity", "EWJ":  "equity", "EWG":  "equity",
    "EWU":  "equity", "EWL":  "equity", "EWP":  "equity", "EWI":  "equity",
    "EWQ":  "equity", "EWD":  "equity", "EWN":  "equity", "EWK":  "equity",
    "EWA":  "equity", "EWC":  "equity", "EWH":  "equity", "EWS":  "equity",
    "EWT":  "equity", "IEV":  "equity",
    # --- Emerging markets ---
    "EEM":  "equity", "IEMG": "equity", "VWO":  "equity", "EWZ":  "equity",
    "MCHI": "equity", "FXI":  "equity", "INDA": "equity", "EPI":  "equity",
    "EWW":  "equity", "EZA":  "equity", "EWM":  "equity", "EWY":  "equity",
    "EPOL": "equity", "TUR":  "equity", "EPHE": "equity", "THD":  "equity",
    "VNM":  "equity", "ILF":  "equity", "AFK":  "equity",

    # ===================================================================
    # BOND
    # ===================================================================
    # --- US treasury (por duración) ---
    "SHY":  "bond", "IEI":  "bond", "IEF":  "bond", "TLH":  "bond",
    "TLT":  "bond", "GOVT": "bond", "SHV":  "bond", "BIL":  "bond",
    "VGSH": "bond", "VGIT": "bond", "VGLT": "bond", "EDV":  "bond",
    "SGOV": "bond",
    # --- US aggregate / investment grade corp ---
    "AGG":  "bond", "BND":  "bond", "LQD":  "bond", "VCIT": "bond",
    "VCSH": "bond", "IGSB": "bond", "IGIB": "bond", "USIG": "bond",
    # --- US high yield / bank loans ---
    "HYG":  "bond", "JNK":  "bond", "SJNK": "bond", "ANGL": "bond",
    "BKLN": "bond", "USHY": "bond",
    # --- US inflation-protected ---
    "TIP":  "bond", "VTIP": "bond", "SCHP": "bond", "STIP": "bond",
    # --- US municipal ---
    "MUB":  "bond", "TFI":  "bond",
    # --- US mortgage-backed ---
    "MBB":  "bond", "VMBS": "bond",
    # --- International / EM bonds ---
    "BNDX": "bond", "BWX":  "bond", "IGOV": "bond", "EMB":  "bond",
    "EMLC": "bond", "PCY":  "bond",

    # ===================================================================
    # COMMODITY
    # ===================================================================
    # --- broad ---
    "DBC":  "commodity", "GSG":  "commodity", "DJP":  "commodity",
    "PDBC": "commodity", "COMT": "commodity", "BCI":  "commodity",
    # --- precious metals ---
    "GLD":  "commodity", "IAU":  "commodity", "SGOL": "commodity",
    "SLV":  "commodity", "SIVR": "commodity", "PPLT": "commodity",
    "PALL": "commodity",
    # --- energy ---
    "USO":  "commodity", "BNO":  "commodity", "UNG":  "commodity",
    "UGA":  "commodity", "DBO":  "commodity", "DBE":  "commodity",
    # --- agriculture ---
    "DBA":  "commodity", "CORN": "commodity", "WEAT": "commodity",
    "SOYB": "commodity", "CANE": "commodity",
    # --- industrial metals ---
    "DBB":  "commodity", "CPER": "commodity",

    # ===================================================================
    # CURRENCY / FX
    # ===================================================================
    "UUP":  "currency", "UDN":  "currency", "FXE":  "currency",
    "FXB":  "currency", "FXY":  "currency", "FXA":  "currency",
    "FXC":  "currency", "FXF":  "currency",
}

# Tickers REDUNDANTES sacados por la curación de liquidez (corr >= 0.95).
# Cada uno se consolida en el ETF más líquido de su grupo (flecha "→ KEPT").
# Quitar una línea de acá = volver a incluir ese ETF en el universo activo.
REDUNDANT_TICKERS: dict[str, str] = {
    # --- equity ---
    "HACK": "→ CIBR",
    "VIG": "→ DIA",
    "IEMG": "→ EEM",
    "VWO": "→ EEM",
    "IEFA": "→ EFA",
    "VEA": "→ EFA",
    "ILF": "→ EWZ",
    "MCHI": "→ FXI",
    "GDXJ": "→ GDX",
    "MDY": "→ IJH",
    "VB": "→ IJH",
    "VBR": "→ IJH",
    "EPI": "→ INDA",
    "XHB": "→ ITB",
    "IJR": "→ IWM",
    "IWN": "→ IWM",
    "VBK": "→ IWO",
    "SCHH": "→ IYR",
    "VNQ": "→ IYR",
    "XLRE": "→ IYR",
    "KBE": "→ KRE",
    "SDY": "→ NOBL",
    "IWF": "→ QQQ",
    "VUG": "→ QQQ",
    "SIZE": "→ RSP",
    "VO": "→ RSP",
    "SOXX": "→ SMH",
    "ITOT": "→ SPY",
    "IVV": "→ SPY",
    "IWB": "→ SPY",
    "OEF": "→ SPY",
    "QUAL": "→ SPY",
    "VOO": "→ SPY",
    "VTI": "→ SPY",
    "EWQ": "→ VGK",
    "EZU": "→ VGK",
    "FEZ": "→ VGK",
    "IEV": "→ VGK",
    "DGRO": "→ VTV",
    "IWD": "→ VTV",
    "VYM": "→ VTV",
    # --- bond ---
    "BND": "→ AGG",
    "IGOV": "→ BWX",
    "PCY": "→ EMB",
    "JNK": "→ HYG",
    "SJNK": "→ HYG",
    "USHY": "→ HYG",
    "IEI": "→ IEF",
    "VGIT": "→ IEF",
    "IGIB": "→ LQD",
    "USIG": "→ LQD",
    "VCIT": "→ LQD",
    "VMBS": "→ MBB",
    "TFI": "→ MUB",
    "BIL": "→ SGOV",
    "SHV": "→ SGOV",
    "VGSH": "→ SHY",
    "SCHP": "→ TIP",
    "EDV": "→ TLT",
    "TLH": "→ TLT",
    "VGLT": "→ TLT",
    "IGSB": "→ VCSH",
    "STIP": "→ VTIP",
    # --- commodity ---
    "DJP": "→ BCI",
    "GSG": "→ BNO",
    "DBE": "→ DBO",
    "IAU": "→ GLD",
    "SGOL": "→ GLD",
    "COMT": "→ PDBC",
    "DBC": "→ PDBC",
    "SIVR": "→ SLV",
    # --- currency ---
    "UDN": "→ FXE",
}

# Universo ACTIVO = crudo menos los redundantes. Única fuente de verdad del backtest.
ETF_UNIVERSE: dict[str, str] = {
    t: c for t, c in _ALL_ETFS.items() if t not in REDUNDANT_TICKERS
}

ASSET_CLASSES = ["equity", "bond", "commodity", "currency"]

# Nombre completo + explicación breve de cada ETF, para el panel del dashboard
# (Overview). Clave = ticker; valor = (nombre, descripción de una línea). Cubre el
# universo crudo entero, así sirve aunque se reactiven redundantes. Si falta un
# ticker, el dashboard cae al ticker + clase como fallback.
ETF_INFO: dict[str, tuple[str, str]] = {
    # ---- equity: US large cap / total market ----
    "SPY":  ("SPDR S&P 500 ETF Trust", "Las 500 mayores empresas de EE.UU. — el benchmark de renta variable americana."),
    "IVV":  ("iShares Core S&P 500 ETF", "S&P 500 de bajo costo de iShares; mismo índice que SPY."),
    "VOO":  ("Vanguard S&P 500 ETF", "S&P 500 en versión Vanguard, ultra bajo costo."),
    "VTI":  ("Vanguard Total Stock Market ETF", "Todo el mercado accionario de EE.UU., de mega a small cap."),
    "ITOT": ("iShares Core S&P Total US Stock Market", "Mercado total de EE.UU. (S&P 1500+)."),
    "QQQ":  ("Invesco QQQ Trust", "Nasdaq-100: las 100 mayores no financieras, sesgo tecnológico."),
    "DIA":  ("SPDR Dow Jones Industrial Average ETF", "Las 30 blue chips del Dow Jones."),
    "OEF":  ("iShares S&P 100 ETF", "Las 100 mega-caps del S&P 100."),
    "RSP":  ("Invesco S&P 500 Equal Weight ETF", "S&P 500 pero con peso igual por empresa, menos sesgo a las gigantes."),
    "IWB":  ("iShares Russell 1000 ETF", "Las 1000 mayores cotizadas de EE.UU. (large + mid cap)."),
    # ---- equity: mid / small cap ----
    "IWM":  ("iShares Russell 2000 ETF", "Small caps de EE.UU. — el benchmark de empresas chicas."),
    "IJR":  ("iShares Core S&P Small-Cap ETF", "Small caps del S&P 600."),
    "MDY":  ("SPDR S&P MidCap 400 ETF", "Empresas medianas del S&P 400."),
    "IJH":  ("iShares Core S&P Mid-Cap ETF", "Mid caps del S&P 400."),
    "VO":   ("Vanguard Mid-Cap ETF", "Empresas medianas de EE.UU. (Vanguard)."),
    "VB":   ("Vanguard Small-Cap ETF", "Empresas chicas de EE.UU. (Vanguard)."),
    # ---- equity: style value / growth ----
    "VTV":  ("Vanguard Value ETF", "Large caps de EE.UU. con sesgo value (baratas por fundamentals)."),
    "VUG":  ("Vanguard Growth ETF", "Large caps de EE.UU. de crecimiento."),
    "IWD":  ("iShares Russell 1000 Value ETF", "Large caps value del Russell 1000."),
    "IWF":  ("iShares Russell 1000 Growth ETF", "Large caps growth del Russell 1000."),
    "IWN":  ("iShares Russell 2000 Value ETF", "Small caps value."),
    "IWO":  ("iShares Russell 2000 Growth ETF", "Small caps de crecimiento."),
    "VBR":  ("Vanguard Small-Cap Value ETF", "Small caps value (Vanguard)."),
    "VBK":  ("Vanguard Small-Cap Growth ETF", "Small caps growth (Vanguard)."),
    # ---- equity: factors ----
    "MTUM": ("iShares MSCI USA Momentum Factor ETF", "Factor momentum: acciones que vienen subiendo."),
    "QUAL": ("iShares MSCI USA Quality Factor ETF", "Factor quality: balances sólidos y ROE alto."),
    "VLUE": ("iShares MSCI USA Value Factor ETF", "Factor value sistemático."),
    "USMV": ("iShares MSCI USA Min Vol Factor ETF", "Acciones de mínima volatilidad."),
    "SIZE": ("iShares MSCI USA Size Factor ETF", "Factor tamaño (sesgo a empresas más chicas)."),
    "SPLV": ("Invesco S&P 500 Low Volatility ETF", "Las 100 acciones menos volátiles del S&P 500."),
    "SPHB": ("Invesco S&P 500 High Beta ETF", "Las 100 acciones de mayor beta del S&P 500."),
    "MOAT": ("VanEck Morningstar Wide Moat ETF", "Empresas con ventaja competitiva durable (\"moat\")."),
    "VIG":  ("Vanguard Dividend Appreciation ETF", "Empresas que aumentan dividendos consistentemente."),
    "VYM":  ("Vanguard High Dividend Yield ETF", "Acciones de alto rendimiento por dividendo."),
    "SDY":  ("SPDR S&P Dividend ETF", "Aristócratas del dividendo (suben dividendo +20 años)."),
    "NOBL": ("ProShares S&P 500 Dividend Aristocrats", "Las del S&P 500 que subieron dividendo +25 años."),
    "DGRO": ("iShares Core Dividend Growth ETF", "Crecimiento de dividendos de calidad."),
    "SCHD": ("Schwab US Dividend Equity ETF", "Alto dividendo con filtro de calidad."),
    # ---- equity: US sectors (SPDR Select) ----
    "XLF":  ("Financial Select Sector SPDR", "Sector financiero del S&P 500 (bancos, aseguradoras)."),
    "XLE":  ("Energy Select Sector SPDR", "Sector energía (petroleras, gas)."),
    "XLK":  ("Technology Select Sector SPDR", "Sector tecnología."),
    "XLV":  ("Health Care Select Sector SPDR", "Sector salud (farma, biotech, equipos)."),
    "XLI":  ("Industrial Select Sector SPDR", "Sector industrial."),
    "XLY":  ("Consumer Discretionary Select Sector SPDR", "Consumo discrecional (autos, retail, ocio)."),
    "XLP":  ("Consumer Staples Select Sector SPDR", "Consumo básico (alimentos, bebidas) — defensivo."),
    "XLU":  ("Utilities Select Sector SPDR", "Servicios públicos (electricidad, agua) — defensivo."),
    "XLB":  ("Materials Select Sector SPDR", "Materiales (químicas, minería, papel)."),
    "XLRE": ("Real Estate Select Sector SPDR", "Sector inmobiliario (REITs) del S&P 500."),
    "XLC":  ("Communication Services Select Sector SPDR", "Telecom y medios (Meta, Google, Netflix)."),
    # ---- equity: industries / thematic ----
    "SMH":  ("VanEck Semiconductor ETF", "Las mayores empresas de semiconductores."),
    "SOXX": ("iShares Semiconductor ETF", "Chips y semiconductores (índice ICE)."),
    "IBB":  ("iShares Biotechnology ETF", "Biotecnología."),
    "XBI":  ("SPDR S&P Biotech ETF", "Biotech con peso igual (más small caps)."),
    "KRE":  ("SPDR S&P Regional Banking ETF", "Bancos regionales de EE.UU."),
    "KBE":  ("SPDR S&P Bank ETF", "Bancos de EE.UU. (peso igual)."),
    "ITB":  ("iShares U.S. Home Construction ETF", "Constructoras de viviendas."),
    "XHB":  ("SPDR S&P Homebuilders ETF", "Homebuilders y cadena de suministro de la vivienda."),
    "KIE":  ("SPDR S&P Insurance ETF", "Aseguradoras."),
    "OIH":  ("VanEck Oil Services ETF", "Servicios petroleros (perforación, equipos)."),
    "XOP":  ("SPDR S&P Oil & Gas Exploration & Production", "Exploración y producción de petróleo y gas."),
    "XME":  ("SPDR S&P Metals & Mining ETF", "Metales y minería."),
    "GDX":  ("VanEck Gold Miners ETF", "Mineras de oro grandes."),
    "GDXJ": ("VanEck Junior Gold Miners ETF", "Mineras de oro chicas (junior), más volátiles."),
    "SIL":  ("Global X Silver Miners ETF", "Mineras de plata."),
    "URA":  ("Global X Uranium ETF", "Uranio y energía nuclear."),
    "TAN":  ("Invesco Solar ETF", "Energía solar."),
    "ICLN": ("iShares Global Clean Energy ETF", "Energía limpia global."),
    "WOOD": ("iShares Global Timber & Forestry ETF", "Madera y forestación."),
    "MOO":  ("VanEck Agribusiness ETF", "Agronegocios (fertilizantes, maquinaria, semillas)."),
    "IYT":  ("iShares U.S. Transportation ETF", "Transporte (aéreo, ferroviario, camiones)."),
    "ITA":  ("iShares U.S. Aerospace & Defense ETF", "Aeroespacial y defensa."),
    "SKYY": ("First Trust Cloud Computing ETF", "Computación en la nube."),
    "IGV":  ("iShares Expanded Tech-Software ETF", "Software."),
    "FDN":  ("First Trust Dow Jones Internet ETF", "Empresas de internet."),
    "XRT":  ("SPDR S&P Retail ETF", "Retail (peso igual)."),
    "IHI":  ("iShares U.S. Medical Devices ETF", "Equipamiento médico."),
    "JETS": ("U.S. Global Jets ETF", "Aerolíneas."),
    "HACK": ("Amplify Cybersecurity ETF", "Ciberseguridad."),
    "CIBR": ("First Trust NASDAQ Cybersecurity ETF", "Ciberseguridad (índice Nasdaq)."),
    "KWEB": ("KraneShares CSI China Internet ETF", "Internet de China (Alibaba, Tencent)."),
    "BOTZ": ("Global X Robotics & AI ETF", "Robótica e inteligencia artificial."),
    "LIT":  ("Global X Lithium & Battery Tech ETF", "Litio y baterías."),
    "REMX": ("VanEck Rare Earth/Strategic Metals ETF", "Tierras raras y metales estratégicos."),
    "COPX": ("Global X Copper Miners ETF", "Mineras de cobre."),
    # ---- equity: real estate (REIT) ----
    "IYR":  ("iShares U.S. Real Estate ETF", "REITs de EE.UU. (inmobiliario cotizado)."),
    "VNQ":  ("Vanguard Real Estate ETF", "REITs de EE.UU. (Vanguard)."),
    "SCHH": ("Schwab U.S. REIT ETF", "REITs de EE.UU. (Schwab)."),
    "REZ":  ("iShares Residential & Multisector RE", "REITs residenciales y de salud."),
    "REM":  ("iShares Mortgage Real Estate ETF", "REITs hipotecarios (mortgage REITs)."),
    # ---- equity: international developed ----
    "EFA":  ("iShares MSCI EAFE ETF", "Mercados desarrollados ex-EE.UU. (Europa, Asia, Lejano Oriente)."),
    "IEFA": ("iShares Core MSCI EAFE ETF", "Desarrollados ex-EE.UU., versión core."),
    "VEA":  ("Vanguard FTSE Developed Markets ETF", "Mercados desarrollados ex-EE.UU. (Vanguard)."),
    "VGK":  ("Vanguard FTSE Europe ETF", "Acciones de Europa."),
    "EZU":  ("iShares MSCI Eurozone ETF", "Acciones de la Eurozona."),
    "FEZ":  ("SPDR EURO STOXX 50 ETF", "Las 50 mayores de la Eurozona."),
    "EWJ":  ("iShares MSCI Japan ETF", "Acciones de Japón."),
    "EWG":  ("iShares MSCI Germany ETF", "Acciones de Alemania."),
    "EWU":  ("iShares MSCI United Kingdom ETF", "Acciones del Reino Unido."),
    "EWL":  ("iShares MSCI Switzerland ETF", "Acciones de Suiza."),
    "EWP":  ("iShares MSCI Spain ETF", "Acciones de España."),
    "EWI":  ("iShares MSCI Italy ETF", "Acciones de Italia."),
    "EWQ":  ("iShares MSCI France ETF", "Acciones de Francia."),
    "EWD":  ("iShares MSCI Sweden ETF", "Acciones de Suecia."),
    "EWN":  ("iShares MSCI Netherlands ETF", "Acciones de Países Bajos."),
    "EWK":  ("iShares MSCI Belgium ETF", "Acciones de Bélgica."),
    "EWA":  ("iShares MSCI Australia ETF", "Acciones de Australia."),
    "EWC":  ("iShares MSCI Canada ETF", "Acciones de Canadá."),
    "EWH":  ("iShares MSCI Hong Kong ETF", "Acciones de Hong Kong."),
    "EWS":  ("iShares MSCI Singapore ETF", "Acciones de Singapur."),
    "EWT":  ("iShares MSCI Taiwan ETF", "Acciones de Taiwán (fuerte en chips)."),
    "IEV":  ("iShares Europe ETF", "Acciones de Europa (S&P Europe 350)."),
    # ---- equity: emerging markets ----
    "EEM":  ("iShares MSCI Emerging Markets ETF", "Mercados emergentes globales."),
    "IEMG": ("iShares Core MSCI Emerging Markets ETF", "Emergentes, versión core de bajo costo."),
    "VWO":  ("Vanguard FTSE Emerging Markets ETF", "Emergentes (Vanguard)."),
    "EWZ":  ("iShares MSCI Brazil ETF", "Acciones de Brasil."),
    "MCHI": ("iShares MSCI China ETF", "Acciones de China."),
    "FXI":  ("iShares China Large-Cap ETF", "Las mayores empresas de China."),
    "INDA": ("iShares MSCI India ETF", "Acciones de India."),
    "EPI":  ("WisdomTree India Earnings ETF", "Acciones de India ponderadas por ganancias."),
    "EWW":  ("iShares MSCI Mexico ETF", "Acciones de México."),
    "EZA":  ("iShares MSCI South Africa ETF", "Acciones de Sudáfrica."),
    "EWM":  ("iShares MSCI Malaysia ETF", "Acciones de Malasia."),
    "EWY":  ("iShares MSCI South Korea ETF", "Acciones de Corea del Sur."),
    "EPOL": ("iShares MSCI Poland ETF", "Acciones de Polonia."),
    "TUR":  ("iShares MSCI Turkey ETF", "Acciones de Turquía."),
    "EPHE": ("iShares MSCI Philippines ETF", "Acciones de Filipinas."),
    "THD":  ("iShares MSCI Thailand ETF", "Acciones de Tailandia."),
    "VNM":  ("VanEck Vietnam ETF", "Acciones de Vietnam."),
    "ILF":  ("iShares Latin America 40 ETF", "Las 40 mayores de Latinoamérica."),
    "AFK":  ("VanEck Africa Index ETF", "Acciones de África."),
    # ---- bond: US treasury (por duración) ----
    "SHY":  ("iShares 1-3 Year Treasury Bond ETF", "Bonos del Tesoro de EE.UU. a 1-3 años (corta duración)."),
    "IEI":  ("iShares 3-7 Year Treasury Bond ETF", "Tesoro de EE.UU. a 3-7 años."),
    "IEF":  ("iShares 7-10 Year Treasury Bond ETF", "Tesoro de EE.UU. a 7-10 años (duración media)."),
    "TLH":  ("iShares 10-20 Year Treasury Bond ETF", "Tesoro de EE.UU. a 10-20 años."),
    "TLT":  ("iShares 20+ Year Treasury Bond ETF", "Tesoro de EE.UU. a 20+ años (larga duración, muy sensible a tasas)."),
    "GOVT": ("iShares U.S. Treasury Bond ETF", "Tesoro de EE.UU. de todos los plazos."),
    "SHV":  ("iShares Short Treasury Bond ETF", "Letras del Tesoro a menos de 1 año (casi cash)."),
    "BIL":  ("SPDR 1-3 Month T-Bill ETF", "Letras del Tesoro a 1-3 meses (proxy de cash)."),
    "VGSH": ("Vanguard Short-Term Treasury ETF", "Tesoro de corto plazo (Vanguard)."),
    "VGIT": ("Vanguard Intermediate-Term Treasury ETF", "Tesoro de plazo intermedio (Vanguard)."),
    "VGLT": ("Vanguard Long-Term Treasury ETF", "Tesoro de largo plazo (Vanguard)."),
    "EDV":  ("Vanguard Extended Duration Treasury ETF", "Tesoro de duración extendida (cupón cero, máxima sensibilidad a tasas)."),
    "SGOV": ("iShares 0-3 Month Treasury Bond ETF", "Letras del Tesoro a 0-3 meses (cash)."),
    # ---- bond: aggregate / IG corp ----
    "AGG":  ("iShares Core U.S. Aggregate Bond ETF", "Todo el mercado de bonos de EE.UU. (Tesoro + corporativos + MBS)."),
    "BND":  ("Vanguard Total Bond Market ETF", "Mercado total de bonos de EE.UU. (Vanguard)."),
    "LQD":  ("iShares iBoxx $ Investment Grade Corporate", "Bonos corporativos investment grade."),
    "VCIT": ("Vanguard Intermediate-Term Corporate Bond", "Corporativos IG de plazo intermedio."),
    "VCSH": ("Vanguard Short-Term Corporate Bond ETF", "Corporativos IG de corto plazo."),
    "IGSB": ("iShares 1-5 Year IG Corporate Bond ETF", "Corporativos IG a 1-5 años."),
    "IGIB": ("iShares 5-10 Year IG Corporate Bond ETF", "Corporativos IG a 5-10 años."),
    "USIG": ("iShares Broad USD IG Corporate Bond ETF", "Corporativos IG en USD, amplio."),
    # ---- bond: high yield / loans ----
    "HYG":  ("iShares iBoxx $ High Yield Corporate Bond", "Bonos corporativos high yield (\"basura\")."),
    "JNK":  ("SPDR Bloomberg High Yield Bond ETF", "Bonos high yield (SPDR)."),
    "SJNK": ("SPDR Bloomberg Short Term High Yield Bond", "High yield de corto plazo."),
    "ANGL": ("VanEck Fallen Angel High Yield Bond ETF", "\"Ángeles caídos\": bonos que perdieron el grado de inversión."),
    "BKLN": ("Invesco Senior Loan ETF", "Préstamos bancarios senior (tasa flotante)."),
    "USHY": ("iShares Broad USD High Yield Corporate", "High yield en USD, amplio."),
    # ---- bond: inflation-protected ----
    "TIP":  ("iShares TIPS Bond ETF", "Bonos del Tesoro indexados a la inflación (TIPS)."),
    "VTIP": ("Vanguard Short-Term Inflation-Protected", "TIPS de corto plazo."),
    "SCHP": ("Schwab U.S. TIPS ETF", "TIPS (Schwab)."),
    "STIP": ("iShares 0-5 Year TIPS Bond ETF", "TIPS a 0-5 años."),
    # ---- bond: municipal ----
    "MUB":  ("iShares National Muni Bond ETF", "Bonos municipales de EE.UU. (exentos de impuestos federales)."),
    "TFI":  ("SPDR Nuveen Bloomberg Municipal Bond ETF", "Bonos municipales (SPDR)."),
    # ---- bond: mortgage-backed ----
    "MBB":  ("iShares MBS ETF", "Bonos respaldados por hipotecas (agency MBS)."),
    "VMBS": ("Vanguard Mortgage-Backed Securities ETF", "MBS de agencias (Vanguard)."),
    # ---- bond: international / EM ----
    "BNDX": ("Vanguard Total International Bond ETF", "Bonos internacionales con cobertura de divisa."),
    "BWX":  ("SPDR Bloomberg International Treasury Bond", "Deuda soberana ex-EE.UU. (sin cobertura)."),
    "IGOV": ("iShares International Treasury Bond ETF", "Deuda soberana de desarrollados ex-EE.UU."),
    "EMB":  ("iShares J.P. Morgan USD Emerging Markets Bond", "Deuda soberana emergente en USD."),
    "EMLC": ("VanEck J.P. Morgan EM Local Currency Bond", "Deuda emergente en moneda local."),
    "PCY":  ("Invesco Emerging Markets Sovereign Debt", "Deuda soberana emergente (Invesco)."),
    # ---- commodity: broad ----
    "DBC":  ("Invesco DB Commodity Index Tracking Fund", "Canasta amplia de commodities (energía, metales, agro)."),
    "GSG":  ("iShares S&P GSCI Commodity-Indexed Trust", "Índice GSCI, fuerte ponderación a energía."),
    "DJP":  ("iPath Bloomberg Commodity Index Total Return", "Canasta amplia de commodities (Bloomberg)."),
    "PDBC": ("Invesco Optimum Yield Diversified Commodity", "Commodities diversificados sin K-1 fiscal."),
    "COMT": ("iShares GSCI Commodity Dynamic Roll Strategy", "Commodities con roll dinámico."),
    "BCI":  ("abrdn Bloomberg All Commodity Strategy", "Canasta amplia de commodities sin K-1."),
    # ---- commodity: precious metals ----
    "GLD":  ("SPDR Gold Shares", "Oro físico — el ETF de oro de referencia."),
    "IAU":  ("iShares Gold Trust", "Oro físico (iShares, más barato que GLD)."),
    "SGOL": ("abrdn Physical Gold Shares ETF", "Oro físico (abrdn)."),
    "SLV":  ("iShares Silver Trust", "Plata física."),
    "SIVR": ("abrdn Physical Silver Shares ETF", "Plata física (abrdn)."),
    "PPLT": ("abrdn Physical Platinum Shares ETF", "Platino físico."),
    "PALL": ("abrdn Physical Palladium Shares ETF", "Paladio físico."),
    # ---- commodity: energy ----
    "USO":  ("United States Oil Fund", "Petróleo crudo WTI (vía futuros)."),
    "BNO":  ("United States Brent Oil Fund", "Petróleo crudo Brent."),
    "UNG":  ("United States Natural Gas Fund", "Gas natural (vía futuros)."),
    "UGA":  ("United States Gasoline Fund", "Gasolina (vía futuros)."),
    "DBO":  ("Invesco DB Oil Fund", "Petróleo WTI con roll optimizado."),
    "DBE":  ("Invesco DB Energy Fund", "Canasta de energía (crudo, gasolina, gas, heating oil)."),
    # ---- commodity: agriculture ----
    "DBA":  ("Invesco DB Agriculture Fund", "Canasta de productos agrícolas."),
    "CORN": ("Teucrium Corn Fund", "Maíz (vía futuros)."),
    "WEAT": ("Teucrium Wheat Fund", "Trigo (vía futuros)."),
    "SOYB": ("Teucrium Soybean Fund", "Soja (vía futuros)."),
    "CANE": ("Teucrium Sugar Fund", "Azúcar (vía futuros)."),
    # ---- commodity: industrial metals ----
    "DBB":  ("Invesco DB Base Metals Fund", "Metales base (aluminio, zinc, cobre)."),
    "CPER": ("United States Copper Index Fund", "Cobre (vía futuros)."),
    # ---- currency / FX ----
    "UUP":  ("Invesco DB US Dollar Index Bullish Fund", "Dólar al alza contra una canasta de divisas (DXY)."),
    "UDN":  ("Invesco DB US Dollar Index Bearish Fund", "Dólar a la baja contra una canasta de divisas."),
    "FXE":  ("Invesco CurrencyShares Euro Trust", "Euro vs dólar."),
    "FXB":  ("Invesco CurrencyShares British Pound", "Libra esterlina vs dólar."),
    "FXY":  ("Invesco CurrencyShares Japanese Yen", "Yen japonés vs dólar."),
    "FXA":  ("Invesco CurrencyShares Australian Dollar", "Dólar australiano vs dólar."),
    "FXC":  ("Invesco CurrencyShares Canadian Dollar", "Dólar canadiense vs dólar."),
    "FXF":  ("Invesco CurrencyShares Swiss Franc", "Franco suizo vs dólar."),
}

# Tickers que estuvieron en el parquet pero se EXCLUYEN del universo a propósito.
# Se documentan acá para que `data-status` no los reporte como sorpresa y para
# dejar registro del motivo. Los .MI/.TO cotizan en EUR/CAD (ruido de FX).
EXCLUDED_TICKERS: dict[str, str] = {
    "COFF.MI": "Café (Milán) — cotiza en EUR, ruido de FX",
    "COTN.MI": "Algodón (Milán) — cotiza en EUR, ruido de FX",
    "NICK.MI": "Níquel (Milán) — cotiza en EUR, ruido de FX",
    "TINM.MI": "Estaño (Milán) — cotiza en EUR, ruido de FX",
    "COW.TO":  "Ganadería (Toronto) — cotiza en CAD, ruido de FX",
}
