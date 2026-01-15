import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="Turnover Map (Binned)", layout="wide")
st.title("Turnover Map — bin & aggregate to avoid blob, radius by Avg HC, color by Turnover vs threshold")

uploaded = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded:
    st.info("Upload a CSV to begin.")
    st.stop()

df_raw = pd.read_csv(uploaded)

# ---------------- Sidebar ----------------
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
turnover_units = st.sidebar.radio(
    "Turnover units in file",
    options=[
        "Percent string (e.g., 3.9%)",
        "Percent number (e.g., 3.9)",
        "Decimal (e.g., 0.039 = 3.9%)",
        "Decimal (e.g., 3.9 = 390%)"
    ],
    index=0
)

threshold_input = st.sidebar.number_input(
    "Threshold (same semantic units as the selected mode)",
    value=0.75,
    step=0.05
)

st.sidebar.subheader("Aggregation (this fixes the blob)")
mode = st.sidebar.radio("Plot mode", options=["Binned (recommended)", "Raw points"], index=0)
bin_precision = st.sidebar.slider("Bin precision (decimal places)", min_value=0, max_value=3, value=1, step=1,
                                  help="Rounding lat/lon to fewer decimals merges nearby sites. 1 ≈ ~11km lat bins; 2 ≈ ~1.1km.")
min_sites_per_bin = st.sidebar.slider("Min sites per bin (filter noise)", min_value=1, max_value=50, value=1, step=1)

st.sidebar.subheader("Radius (meters)")
radius_scale = st.sidebar.slider("Scale", min_value=10, max_value=5000, value=250, step=10)
max_radius = st.sidebar.slider("Max radius", min_value=50, max_value=50000, value=6000, step=50)
min_radius = st.sidebar.slider("Min radius", min_value=0, max_value=2000, value=50, step=25)
radius_power = st.sidebar.selectbox("Radius curve", options=["sqrt(hc)", "hc^(0.30)", "hc^(0.20)"], index=0)

st.sidebar.subheader("Color")
alpha = st.sidebar.slider("Opacity", min_value=10, max_value=255, value=110, step=5)
robust_q = st.sidebar.slider("Color scale percentile (robust)", min_value=80, max_value=99, value=95, step=1)

# ---------------- Parse ----------------
df = df_raw.copy()
df["lat"] = pd.to_numeric(df[col_lat], errors="coerce")
df["lon"] = pd.to_numeric(df[col_lon], errors="coerce")

hc_series = df[col_hc].astype(str).str.replace(",", "", regex=False)
df["avg_hc"] = pd.to_numeric(hc_series, errors="coerce").clip(lower=0)

to_series = df[col_to]

if turnover_units.startswith("Percent string"):
    s = to_series.astype(str).str.strip().str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    turnover_num = pd.to_numeric(s, errors="coerce")
    # interpret as percent number (3.9 means 3.9%)
    df["turnover"] = turnover_num / 100.0
    threshold = float(threshold_input) / 100.0
elif turnover_units.startswith("Percent number"):
    df["turnover"] = pd.to_numeric(to_series, errors="coerce") / 100.0
    threshold = float(threshold_input) / 100.0
elif turnover_units == "Decimal (e.g., 0.039 = 3.9%)":
    df["turnover"] = pd.to_numeric(to_series, errors="coerce")
    threshold = float(threshold_input)
else:
    # 3.9 means 390% -> convert to 3.9
    df["turnover"] = pd.to_numeric(to_series, errors="coerce")
    threshold = float(threshold_input)

df["site"] = df[col_site].astype(str) if col_site != "(none)" else ""

df = df.dropna(subset=["lat", "lon", "turnover", "avg_hc"])
if len(df) == 0:
    st.error("No valid rows after parsing. Check column mappings and turnover parsing mode.")
    st.stop()

# ---------------- Aggregate (key change) ----------------
plot_df = df.copy()

if mode.startswith("Binned"):
    plot_df["lat_bin"] = plot_df["lat"].round(bin_precision)
    plot_df["lon_bin"] = plot_df["lon"].round(bin_precision)

    # Weighted turnover (weights = avg_hc exposure)
    g = plot_df.groupby(["lat_bin", "lon_bin"], as_index=False).agg(
        sites_in_bin=("avg_hc", "size"),
        avg_hc_sum=("avg_hc", "sum"),
        turnover_w=("turnover", lambda s: np.nan),  # placeholder
    )
    # compute weighted turnover safely
    # build sums for numerator/denominator
    tmp = plot_df.assign(to_x_hc=plot_df["turnover"] * plot_df["avg_hc"])
    sums = tmp.groupby(["lat_bin", "lon_bin"], as_index=False).agg(
        to_x_hc=("to_x_hc", "sum"),
        hc=("avg_hc", "sum"),
        sites_in_bin=("avg_hc", "size"),
    )
    sums["turnover"] = np.where(sums["hc"] > 0, sums["to_x_hc"] / sums["hc"], np.nan)

    plot_df = sums.rename(columns={"lat_bin": "lat", "lon_bin": "lon", "hc": "avg_hc"})
    plot_df = plot_df.dropna(subset=["turnover", "avg_hc"])
    plot_df = plot_df[plot_df["sites_in_bin"] >= min_sites_per_bin].copy()

# ---------------- Diagnostics ----------------
mapped_rows = len(df)
plot_rows = len(plot_df)

above = (plot_df["turnover"] > threshold).sum()
below = plot_rows - above

st.subheader("Data quality")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Rows parsed", f"{mapped_rows:,}")
c2.metric("Plotted points", f"{plot_rows:,}")
c3.metric("Turnover min/max", f"{plot_df['turnover'].min()*100:.2f}% / {plot_df['turnover'].max()*100:.2f}%")
c4.metric("Below / Above threshold", f"{below:,} / {above:,}")
c5.metric("Threshold", f"{threshold*100:.2f}%")

# ---------------- Radius ----------------
hc = plot_df["avg_hc"].fillna(0).clip(lower=0)

if radius_power == "sqrt(hc)":
    r = np.sqrt(hc) * float(radius_scale)
elif radius_power == "hc^(0.30)":
    r = np.power(hc, 0.30) * float(radius_scale)
else:
    r = np.power(hc, 0.20) * float(radius_scale)

plot_df["radius_m"] = np.clip(r, float(min_radius), float(max_radius))

# ---------------- Colors (two layers, red on top) ----------------
delta = plot_df["turnover"] - threshold
abs_delta = np.abs(delta)
scale = np.nanquantile(abs_delta, robust_q/100.0) if len(abs_delta) else 1.0
if not np.isfinite(scale) or scale == 0:
    scale = 1.0

t = np.clip(delta / scale, -1, 1)
intensity = (np.abs(t) * 255).astype(int)

plot_df["is_above"] = plot_df["turnover"] > threshold
plot_df["turnover_pct"] = (plot_df["turnover"] * 100).round(2).astype(str) + "%"
plot_df["delta_pct"] = ((plot_df["turnover"] - threshold) * 100).round(2).astype(str) + "%"

if "sites_in_bin" not in plot_df.columns:
    plot_df["sites_in_bin"] = 1

low = plot_df[~plot_df["is_above"]].copy()
high = plot_df[plot_df["is_above"]].copy()

low["color"] = [[0, int(v), 0, int(alpha)] for v in intensity[~plot_df["is_above"]]]
high["color"] = [[int(v), 0, 0, int(alpha)] for v in intensity[plot_df["is_above"]]]

tooltip = {
    "html": "<b>Turnover:</b> {turnover_pct}<br/>"
            "<b>Avg HC (exposure):</b> {avg_hc}<br/>"
            "<b>Delta vs threshold:</b> {delta_pct}<br/>"
            "<b>Sites in point/bin:</b> {sites_in_bin}",
    "style": {"backgroundColor": "white", "color": "black"}
}

# View
lat_min, lat_max = plot_df["lat"].min(), plot_df["lat"].max()
lon_min, lon_max = plot_df["lon"].min(), plot_df["lon"].max()
span = max(lat_max - lat_min, lon_max - lon_min)

if span > 60:
    zoom = 3
elif span > 30:
    zoom = 4
elif span > 15:
    zoom = 5
elif span > 7:
    zoom = 6
else:
    zoom = 7

view_state = pdk.ViewState(
    latitude=float(plot_df["lat"].mean()),
    longitude=float(plot_df["lon"].mean()),
    zoom=zoom
)

low_layer = pdk.Layer(
    "ScatterplotLayer",
    data=low,
    get_position='[lon, lat]',
    get_radius="radius_m",
    radius_units="meters",
    get_fill_color="color",
    pickable=True,
    stroked=False
)

high_layer = pdk.Layer(
    "ScatterplotLayer",
    data=high,
    get_position='[lon, lat]',
    get_radius="radius_m",
    radius_units="meters",
    get_fill_color="color",
    pickable=True,
    stroked=False
)

deck = pdk.Deck(
    layers=[low_layer, high_layer],
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style="mapbox://styles/mapbox/light-v10"
)

st.subheader("Map")
st.pydeck_chart(deck, use_container_width=True)

with st.expander("Preview plotted data"):
    cols = ["lat", "lon", "avg_hc", "turnover_pct", "delta_pct", "radius_m", "sites_in_bin", "is_above"]
    st.dataframe(plot_df[cols].head(400))
