import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="Turnover Heat Map (Threshold)", layout="wide")

st.title("Turnover Map — radius by Avg HC, color by Turnover vs threshold")

uploaded = st.file_uploader("Upload CSV", type=["csv"])

with st.expander("Expected columns (defaults)", expanded=True):
    st.markdown(
        """
- **lat** (latitude)
- **lon** (longitude)
- **avg_hc** (average headcount; drives point radius)
- **turnover_pct** (turnover; drives color)
- **site** (optional label/id)

Notes:
- `turnover_pct` may be numeric (e.g., `3.2` or `320.0`) **or** a string with `%` (e.g., `320%`).
- If your turnover is in percent units (e.g., `320` meaning 320%), set **Turnover units** to **Percent**.
"""
    )

if not uploaded:
    st.info("Upload a CSV to begin.")
    st.stop()

df_raw = pd.read_csv(uploaded)

# Column selectors (lets you keep your upload schema unchanged)
st.sidebar.header("Column mapping")
col_lat = st.sidebar.selectbox("Latitude column", options=df_raw.columns, index=df_raw.columns.get_loc("lat") if "lat" in df_raw.columns else 0)
col_lon = st.sidebar.selectbox("Longitude column", options=df_raw.columns, index=df_raw.columns.get_loc("lon") if "lon" in df_raw.columns else 0)
col_hc  = st.sidebar.selectbox("Avg HC column", options=df_raw.columns, index=df_raw.columns.get_loc("avg_hc") if "avg_hc" in df_raw.columns else 0)
col_to  = st.sidebar.selectbox("Turnover column", options=df_raw.columns, index=df_raw.columns.get_loc("turnover_pct") if "turnover_pct" in df_raw.columns else 0)
col_site = st.sidebar.selectbox("Site/label column (optional)", options=["(none)"] + list(df_raw.columns), index=(["(none)"] + list(df_raw.columns)).index("site") if "site" in df_raw.columns else 0)

turnover_units = st.sidebar.radio("Turnover units", options=["Decimal (e.g., 3.2 = 320%)", "Percent (e.g., 320 = 320%)"], index=0)

threshold_input = st.sidebar.number_input("Turnover threshold", value=2.0 if turnover_units.startswith("Decimal") else 200.0, step=0.1 if turnover_units.startswith("Decimal") else 10.0)
radius_scale_m = st.sidebar.slider("Radius scale (meters per 1 avg_hc)", min_value=100, max_value=20000, value=4000, step=100)
min_radius = st.sidebar.slider("Min radius (m)", min_value=0, max_value=20000, value=800, step=100)
max_radius = st.sidebar.slider("Max radius (m)", min_value=1000, max_value=80000, value=25000, step=500)

robust_q = st.sidebar.slider("Color scaling robustness (percentile)", min_value=80, max_value=99, value=95, step=1)

# Build working df
df = df_raw.copy()

# Convert lat/lon
df["lat"] = pd.to_numeric(df[col_lat], errors="coerce")
df["lon"] = pd.to_numeric(df[col_lon], errors="coerce")

# Convert avg hc
# remove commas if present
hc_series = df[col_hc].astype(str).str.replace(",", "", regex=False)
df["avg_hc"] = pd.to_numeric(hc_series, errors="coerce")

# Convert turnover
to_series = df[col_to]
if to_series.dtype == object:
    # strip % and commas, keep minus/decimal
    s = to_series.astype(str).str.strip()
    s = s.str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    df["turnover_raw"] = pd.to_numeric(s, errors="coerce")
else:
    df["turnover_raw"] = pd.to_numeric(to_series, errors="coerce")

# Normalize turnover to DECIMAL units internally (e.g., 3.2 means 320%)
if turnover_units.startswith("Decimal"):
    df["turnover"] = df["turnover_raw"]
    threshold = float(threshold_input)
else:
    # percent -> decimal
    df["turnover"] = df["turnover_raw"] / 100.0
    threshold = float(threshold_input) / 100.0

# Optional label
if col_site != "(none)":
    df["site"] = df[col_site].astype(str)
else:
    df["site"] = ""

# Drop rows without coordinates
df = df.dropna(subset=["lat", "lon"])
mapped_rows = len(df)

# Data quality sidebar stats
st.subheader("Data quality")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Rows mapped", f"{mapped_rows:,}")
c2.metric("Turnover mean", f"{(df['turnover'].mean()*100 if mapped_rows else float('nan')):.2f}%")
c3.metric("Avg HC mean", f"{df['avg_hc'].mean() if mapped_rows else float('nan'):.2f}")
c4.metric("Threshold", f"{threshold*100:.2f}%")

if mapped_rows == 0:
    st.error("No valid lat/lon rows found after parsing. Check column mapping and data types.")
    st.stop()

# Compute radius (meters) from avg_hc
r = df["avg_hc"].fillna(0) * float(radius_scale_m)
r = r.clip(lower=float(min_radius), upper=float(max_radius))
df["radius_m"] = r

# Diverging color: green below threshold, red above threshold
delta = df["turnover"] - threshold
abs_delta = np.abs(delta.dropna())
scale = np.nanquantile(abs_delta, robust_q/100.0) if len(abs_delta) else 1.0
if not np.isfinite(scale) or scale == 0:
    scale = 1.0

t = np.clip(delta / scale, -1, 1)  # [-1,1]
intensity = (np.abs(t) * 255).astype(int)

# RGBA (transparent-ish)
df["color_r"] = np.where(t > 0, intensity, 0)
df["color_g"] = np.where(t < 0, intensity, 0)
df["color_b"] = 0
df["color_a"] = 170

# Tooltip
tooltip = {
    "html": "<b>Site:</b> {site}<br/>"
            "<b>Turnover:</b> {turnover_pct}<br/>"
            "<b>Avg HC:</b> {avg_hc}<br/>"
            "<b>Delta vs threshold:</b> {delta_pct}",
    "style": {"backgroundColor": "white", "color": "black"}
}

df["turnover_pct"] = (df["turnover"] * 100).round(2).astype(str) + "%"
df["delta_pct"] = ((df["turnover"] - threshold) * 100).round(2).astype(str) + "%"

# View state
view_state = pdk.ViewState(
    latitude=float(df["lat"].mean()),
    longitude=float(df["lon"].mean()),
    zoom=4,
    pitch=0
)

layer = pdk.Layer(
    "ScatterplotLayer",
    data=df,
    get_position='[lon, lat]',
    get_radius="radius_m",
    radius_units="meters",
    get_fill_color='[color_r, color_g, color_b, color_a]',
    pickable=True,
    stroked=False
)

deck = pdk.Deck(
    layers=[layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style=None
)

st.subheader("Map")
st.pydeck_chart(deck, use_container_width=True)

with st.expander("Preview data used for mapping"):
    st.dataframe(df[["site", "lat", "lon", "avg_hc", "turnover_pct", "delta_pct", "radius_m"]].head(200))
