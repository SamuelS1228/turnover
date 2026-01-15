import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Turnover Map (Plotly)", layout="wide")
st.title("Turnover Map — Plotly (size by Avg HC, diverging color by Turnover vs threshold)")

uploaded = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded:
    st.info("Upload a CSV to begin.")
    st.stop()

df_raw = pd.read_csv(uploaded)

# ---- Sidebar: mapping ----
st.sidebar.header("Column mapping")
def pick(default_name: str):
    return df_raw.columns.get_loc(default_name) if default_name in df_raw.columns else 0

col_lat  = st.sidebar.selectbox("Latitude column", options=df_raw.columns, index=pick("lat"))
col_lon  = st.sidebar.selectbox("Longitude column", options=df_raw.columns, index=pick("lon"))
col_hc   = st.sidebar.selectbox("Avg HC column", options=df_raw.columns, index=pick("avg_hc"))
col_to   = st.sidebar.selectbox("Turnover column", options=df_raw.columns, index=pick("turnover_pct"))
col_site = st.sidebar.selectbox("Site/label column (optional)", options=["(none)"] + list(df_raw.columns),
                                index=(["(none)"] + list(df_raw.columns)).index("site") if "site" in df_raw.columns else 0)

st.sidebar.subheader("Turnover parsing")
turnover_mode = st.sidebar.radio(
    "Turnover format in file",
    options=[
        "Percent string (e.g., 3.9%)",
        "Percent number (e.g., 3.9)",
        "Decimal fraction (e.g., 0.039 = 3.9%)",
        "Decimal rate (e.g., 3.2 = 320%)"
    ],
    index=0
)

threshold_input = st.sidebar.number_input("Threshold (same semantic units as chosen above)", value=0.75, step=0.05)

st.sidebar.subheader("Sizing")
size_mode = st.sidebar.radio("Size scaling", options=["sqrt(avg_hc) (recommended)", "linear avg_hc"], index=0)
size_multiplier = st.sidebar.slider("Size multiplier", min_value=1.0, max_value=50.0, value=12.0, step=1.0)
max_size = st.sidebar.slider("Max marker size", min_value=5, max_value=80, value=40, step=1)

st.sidebar.subheader("Map / color")
map_style = st.sidebar.selectbox("Map style", ["carto-positron", "open-street-map", "carto-darkmatter"], index=0)
robust_q = st.sidebar.slider("Color scale robustness (percentile)", min_value=80, max_value=99, value=95, step=1)

# ---- Parse data ----
df = df_raw.copy()
df["lat"] = pd.to_numeric(df[col_lat], errors="coerce")
df["lon"] = pd.to_numeric(df[col_lon], errors="coerce")

hc_series = df[col_hc].astype(str).str.replace(",", "", regex=False)
df["avg_hc"] = pd.to_numeric(hc_series, errors="coerce")

to_series = df[col_to]

if turnover_mode.startswith("Percent string"):
    s = to_series.astype(str).str.strip().str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    tnum = pd.to_numeric(s, errors="coerce")
    # interpret as percent number -> decimal fraction
    df["turnover"] = tnum / 100.0
    threshold = float(threshold_input) / 100.0
elif turnover_mode.startswith("Percent number"):
    df["turnover"] = pd.to_numeric(to_series, errors="coerce") / 100.0
    threshold = float(threshold_input) / 100.0
elif turnover_mode.startswith("Decimal fraction"):
    df["turnover"] = pd.to_numeric(to_series, errors="coerce")
    threshold = float(threshold_input)
else:
    # Decimal rate, e.g. 3.2 means 320% -> keep as 3.2
    df["turnover"] = pd.to_numeric(to_series, errors="coerce")
    threshold = float(threshold_input)

df["site"] = df[col_site].astype(str) if col_site != "(none)" else ""

df = df.dropna(subset=["lat", "lon", "avg_hc", "turnover"])
if len(df) == 0:
    st.error("No valid rows after parsing. Check column mappings and turnover mode.")
    st.stop()

# ---- Compute diverging color value around threshold ----
df["delta"] = df["turnover"] - threshold

# Robust symmetric color range
abs_delta = np.abs(df["delta"].to_numpy())
scale = np.nanquantile(abs_delta, robust_q/100.0) if len(abs_delta) else 1.0
if not np.isfinite(scale) or scale == 0:
    scale = 1.0
df["delta_clipped"] = np.clip(df["delta"], -scale, scale)

# Sizing
hc = df["avg_hc"].clip(lower=0)
if size_mode.startswith("sqrt"):
    df["size"] = np.sqrt(hc) * float(size_multiplier)
else:
    df["size"] = hc * float(size_multiplier)

# cap sizes for readability
df["size"] = df["size"].clip(lower=1, upper=float(max_size))

# Pretty fields
df["turnover_pct"] = (df["turnover"] * 100).round(2).astype(str) + "%"
df["delta_pct"] = (df["delta"] * 100).round(2).astype(str) + "%"

above = int((df["delta"] > 0).sum())
below = int((df["delta"] <= 0).sum())

st.subheader("Data quality")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Rows mapped", f"{len(df):,}")
c2.metric("Turnover mean", f"{df['turnover'].mean()*100:.2f}%")
c3.metric("Turnover min/max", f"{df['turnover'].min()*100:.2f}% / {df['turnover'].max()*100:.2f}%")
c4.metric("Below / Above threshold", f"{below:,} / {above:,}")
c5.metric("Threshold", f"{threshold*100:.2f}%")

# ---- Plotly map ----
# Diverging colorscale: green -> neutral -> red
diverging = [
    [0.0, "rgb(0,120,0)"],   # green
    [0.5, "rgb(245,245,245)"],  # near threshold
    [1.0, "rgb(180,0,0)"],   # red
]

fig = px.scatter_mapbox(
    df,
    lat="lat",
    lon="lon",
    size="size",
    size_max=max_size,
    color="delta_clipped",
    color_continuous_scale=diverging,
    range_color=[-scale, scale],
    hover_name="site" if col_site != "(none)" else None,
    hover_data={
        "turnover_pct": True,
        "avg_hc": True,
        "delta_pct": True,
        "lat": False,
        "lon": False,
        "size": False,
        "delta_clipped": False
    },
    zoom=3,
    height=700
)

fig.update_layout(
    mapbox_style=map_style,
    coloraxis_colorbar=dict(
        title="Δ vs threshold",
        tickformat=".2%"
    ),
    margin=dict(l=0, r=0, t=0, b=0)
)

st.subheader("Map")
st.plotly_chart(fig, use_container_width=True)

with st.expander("Preview data used for mapping"):
    st.dataframe(df[["site", "lat", "lon", "avg_hc", "turnover_pct", "delta_pct", "size"]].head(300))
