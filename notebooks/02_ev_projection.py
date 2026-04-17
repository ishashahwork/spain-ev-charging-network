"""
EV Demand Projection — IE × Iberdrola Datathon
===============================================
Mandatory output: total_ev_projected_2027
Source: datos.gob.es DGT registration data (parquets_procesados/)
Method: SARIMA time series forecast (adapted from official datos.gob.es notebook)
"""

import os
import numpy as np
import pandas as pd
import statsmodels.api as sm
import pmdarima as pm
import warnings
import json
warnings.filterwarnings('ignore')

OUTPUT_FILE = "data/processed/ev_projection_results.json"
PARQUET_DIR = "data/raw/parquets_procesados"

# ─────────────────────────────────────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────
print("Loading parquet files...")
dfs = []
for f in sorted(os.listdir(PARQUET_DIR)):
    if f.endswith(".parquet"):
        dfs.append(pd.read_parquet(os.path.join(PARQUET_DIR, f)))
df = pd.concat(dfs, ignore_index=True)
print(f"  Loaded {len(df):,} rows from {len(dfs)} files")

# ─────────────────────────────────────────────────────────────────────────────
# 2. CLEAN & FILTER (mirrors oficial notebook logic)
# ─────────────────────────────────────────────────────────────────────────────
# Parse year and month from FEC_MATRICULA (format: DDMMYYYY)
df['ANO'] = pd.to_numeric(df['FEC_MATRICULA'].str[-4:], errors='coerce').astype('Int64')
df['MES'] = pd.to_numeric(df['FEC_MATRICULA'].str[-6:-4], errors='coerce').astype('Int64')

# Keep only: passenger cars (40), firm registrations (1, 5, B), valid dates
df = df[
    (df['COD_TIPO'] == '40') &
    (df['CLAVE_TRAMITE'].isin(['1', '5', 'B'])) &
    (df['ANO'] >= 2015) & (df['ANO'] <= 2025)
]

# Map propulsion codes to labels
cod_propulsion = {
    '0': 'Gasolina', '1': 'Diesel', '2': 'Eléctrico',
    '3': 'Otros', '4': 'Butano', '5': 'Solar',
    '6': 'Gas Licuado de Petróleo', '7': 'Gas Natural Comprimido',
    '8': 'Gas Natural Licuado', '9': 'Hidrógeno',
    'A': 'Biometano', 'B': 'Etanol', 'C': 'Biodiesel'
}
df['COD_PROPULSION_ITV'] = df['COD_PROPULSION_ITV'].replace(cod_propulsion)
df = df[df['COD_PROPULSION_ITV'].isin(cod_propulsion.values())]

print(f"  After filtering: {len(df):,} passenger car firm registrations (2015-2025)")

# ─────────────────────────────────────────────────────────────────────────────
# 3. HISTORICAL EV FLEET (cumulative registrations 2015–2025)
# ─────────────────────────────────────────────────────────────────────────────
df_ev = df[df['COD_PROPULSION_ITV'] == 'Eléctrico'].copy()

# Monthly EV registrations time series
df_monthly = (
    df_ev.groupby(['ANO', 'MES'])
    .size()
    .reset_index(name='MATRICULACIONES')
)
df_monthly['FECHA'] = pd.to_datetime(
    df_monthly['ANO'].astype(str) + '-' + df_monthly['MES'].astype(str).str.zfill(2)
)
df_monthly = df_monthly.set_index('FECHA').sort_index()['MATRICULACIONES']

total_historical_ev = int(df_monthly.sum())
print(f"\nHistorical EV registrations (2015–2025): {total_historical_ev:,}")
print(f"  Time series: {df_monthly.index[0].strftime('%Y-%m')} → {df_monthly.index[-1].strftime('%Y-%m')}")
print(f"  Monthly range: {df_monthly.min():.0f} – {df_monthly.max():.0f}")
print(f"  Last 12 months avg: {df_monthly[-12:].mean():.0f}/month")

# ─────────────────────────────────────────────────────────────────────────────
# 4. SARIMA FORECAST — 24 months ahead (2026 + 2027)
# ─────────────────────────────────────────────────────────────────────────────
print("\nFitting SARIMA model (this may take ~1 min)...")

# Auto-select SARIMA order (same as oficial notebook)
auto = pm.auto_arima(
    np.log(df_monthly),
    test='adf',
    m=12,
    seasonal=True,
    trace=False,
    error_action='ignore',
    suppress_warnings=True,
    stepwise=True
)
order = auto.order
seasonal_order = auto.seasonal_order
print(f"  Best SARIMA order: {order} x {seasonal_order}")

# Fit final model
model = sm.tsa.statespace.SARIMAX(
    np.log(df_monthly),
    order=order,
    seasonal_order=seasonal_order
)
model_fit = model.fit(disp=False)
print(f"  AIC: {model_fit.aic:.2f}")

# Forecast 24 months ahead
fc = model_fit.get_forecast(steps=24).summary_frame(alpha=0.1)
fc_monthly = np.exp(fc['mean'])

# ─────────────────────────────────────────────────────────────────────────────
# 5. COMPUTE KEY OUTPUTS
# ─────────────────────────────────────────────────────────────────────────────
# Build forecast date index starting from 2026-01
last_date = df_monthly.index[-1]
forecast_dates = pd.date_range(
    start=last_date + pd.offsets.MonthBegin(1),
    periods=24,
    freq='MS'
)
fc_monthly.index = forecast_dates

ev_new_2026 = int(fc_monthly[fc_monthly.index.year == 2026].sum().round())
ev_new_2027 = int(fc_monthly[fc_monthly.index.year == 2027].sum().round())
total_ev_projected_2027 = total_historical_ev + ev_new_2026 + ev_new_2027

print("\n" + "="*50)
print("EV PROJECTION RESULTS")
print("="*50)
print(f"  Historical EV fleet (2015–2025):   {total_historical_ev:>10,}")
print(f"  Forecasted new EVs in 2026:         {ev_new_2026:>10,}")
print(f"  Forecasted new EVs in 2027:         {ev_new_2027:>10,}")
print(f"  ─────────────────────────────────────────")
print(f"  TOTAL EV FLEET projected 2027:      {total_ev_projected_2027:>10,}  ← File 1 KPI")
print("="*50)

# Monthly breakdown
print(f"\nMonthly forecast 2026–2027:")
for date, val in fc_monthly.items():
    print(f"  {date.strftime('%Y-%m')}: {int(round(val)):,} new EVs")

# ─────────────────────────────────────────────────────────────────────────────
# 6. SAVE RESULTS
# ─────────────────────────────────────────────────────────────────────────────
os.makedirs("data/processed", exist_ok=True)

results = {
    "total_ev_projected_2027": total_ev_projected_2027,
    "total_historical_ev_2015_2025": total_historical_ev,
    "ev_new_registrations_2026_forecast": ev_new_2026,
    "ev_new_registrations_2027_forecast": ev_new_2027,
    "sarima_order": list(order),
    "sarima_seasonal_order": list(seasonal_order),
    "monthly_forecast": {
        str(d.date()): int(round(v)) for d, v in fc_monthly.items()
    }
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print(f"\nResults saved to {OUTPUT_FILE}")

# Also save monthly forecast as CSV for use in demand model
fc_df = pd.DataFrame({
    'fecha': forecast_dates,
    'year': forecast_dates.year,
    'month': forecast_dates.month,
    'ev_new_registrations_forecast': fc_monthly.values.round().astype(int),
    'ev_lower_90': np.exp(fc['mean_ci_lower']).values.round().astype(int),
    'ev_upper_90': np.exp(fc['mean_ci_upper']).values.round().astype(int),
})
fc_df.to_csv("data/processed/ev_monthly_forecast_2026_2027.csv", index=False)
print("Monthly forecast saved to data/processed/ev_monthly_forecast_2026_2027.csv")
