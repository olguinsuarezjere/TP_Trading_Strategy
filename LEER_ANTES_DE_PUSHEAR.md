# ⚠️ LEER ANTES DE PUSHEAR

> **Regla de oro:** el repo tiene que quedar **limpio y reutilizable por todos**, sin
> datos personales de nadie. Cada uno opera con **su propio TWS y su propia cuenta**;
> el código NO debe arrastrar logs, operaciones ni estado de otra persona.

## ❌ NO subas NUNCA al repo

- **`logs/` completo** — contiene datos personales de TU sesión:
  - `trades.csv`, `rebalances.csv` → tus operaciones
  - `nav_history.csv` → tu P&L
  - `strategy_state.json` → tu estado/enrolamiento de la estrategia
  - `ibkr_validation.csv`, `opt_cache.json` → cachés locales
- Tu **número de cuenta IBKR** ni credenciales (no van en el código; TWS las maneja local).
- Archivos `.env`, `*.local`, `*.bak` (backups).
- **Outputs de notebooks** con datos de tu cuenta (balances, posiciones, nº de cuenta).
  Antes de commitear un `.ipynb`, **limpiá las salidas** (Kernel → Restart & Clear Output).

## ✅ Cómo está protegido (y cómo no romperlo)

- Todo lo de arriba **ya está en `.gitignore`** (`logs/`, `*.bak`, `.env`, `*.local`),
  así que un `git add` normal **NO los sube**. 
- **NO uses `git add -f`** (forzado) sobre esos archivos.
- Cuando hagas `git add .` o `git add -A`, **revisá antes con `git status`** que no estés
  agregando nada de `logs/` ni datos personales.

## ✔️ Checklist rápido antes de cada push

```bash
git status          # ¿aparece algo de logs/ o datos personales? -> NO lo agregues
git diff --cached   # revisá qué estás por commitear
```

Si en `git status` ves algo de `logs/` listado para commitear, **sacalo**:

```bash
git restore --staged logs/      # lo quita del commit (no borra tu archivo local)
```

## 📦 Si compartís la carpeta por ZIP (en vez de git)

El `.gitignore` **no aplica** a un zip. Si pasás la carpeta comprimida,
**borrá `logs/` antes de comprimir**, o vas a estar mandando tus operaciones y P&L.

---

**En resumen:** subí *código*, no *tu data*. Así todos clonamos y arrancamos de cero,
cada uno con su propio TWS, sin pisarnos los logs.
