import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="Turnover Map (Threshold)", layout="wide")
st.title("Turnover Map — radius by Avg HC, color by Turnover vs threshold")

uploaded = st.file_uploader("Upload CSV", type=["csv"])
if not uploaded:
    st.info("Upload a CSV to begin.")
    st.stop()

df_raw = pd.read_csv(uploaded)

# ---- Sidebar controls ----
st.sidebar.header("Column mapping")
def pick(default_name: str):
    return df_raw.columns.get_loc(default_name) if default_name in df_raw.columns else 0

col_lat = st.sidebar.selectbox("Latitude column", options=df_raw.columns, index=pick("lat"))
col_lon = st.sidebar.selectbox("Longitude column", options=df_raw.columns, index=pick("lon"))
col_hc  = st.sidebar.selectbox("Avg HC column", options=df_raw.columns, index=pick("avg_hc"))
col_to  = st.sidebar.selectbox("Turnover column", options=df_raw.columns, index=pick("turnover_pct"))
col_site = st.sidebar.selectbox("Site/label column (optional)", options=["(none)"] + list(df_raw.columns),
                                index=(["(none)"] + list(df_raw.columns)).index("site") if "site" in df_raw.columns else 0)

turnover_units = st.sidebar.radio(
    "Turnover units in file",
    options=["Decimal (0.75 = 75%)", "Percent (75 = 75%)", "Percent string (75%)"],
    index=2 if (col_to and df_raw[col_to].astype(str).str.contains("%").any()) else 1
)

threshold_input = st.sidebar.number_input(
    "Threshold (in SAME units as chosen above)",
    value=0.75 if turnover_units == "Percent string (75%)" else (75.0 if turnover_units.startswith("Percent") else 0.75),
    step=0.05 if turnover_units.startswith("Decimal") else 0.05
)

st.sidebar.subheader("Radius (meters)")
radius_mode = st.sidebar.radio("Radius scaling", options=["Sqrt (recommended)", "Linear"], index=0)
radius_scale_m = st.sidebar.slider("Scale (meters)", min_value=10, max_value=5000, value=120, step=10)
min_radius = st.sidebar.slider("Min radius (m)", min_value=0, max_value=2000, value=0, step=25)
max_radius = st.sidebar.slider("Max radius (m)", min_value=50, max_value=20000, value=900, step=50)

st.sidebar.subheader("Color")
robust_q = st.sidebar.slider("Color scale percentile (robust)", min_value=80, max_value=99, value=95, step=1)
alpha = st.sidebar.slider("Point opacity", min_value=10, max_value=255, value=80, step=5)

# ---- Parse & normalize ----
df = df_raw.copy()
df["lat"] = pd.to_numeric(df[col_lat], errors="coerce")
df["lon"] = pd.to_numeric(df[col_lon], errors="coerce")

hc_series = df[col_hc].astype(str).str.replace(",", "", regex=False)
df["avg_hc"] = pd.to_numeric(hc_series, errors="coerce")

to_series = df[col_to]
if turnover_units == "Percent string (75%)":
    s = to_series.astype(str).str.strip().str.replace(",", "", regex=False).str.replace("%", "", regex=False)
    df["turnover_raw"] = pd.to_numeric(s, errors="coerce")
else:
    if to_series.dtype == object:
        s = to_series.astype(str).str.strip().str.replace(",", "", regex=False)
        df["turnover_raw"] = pd.to_numeric(s, errors="coerce")
    else:
        df["turnover_raw"] = pd.to_numeric(to_series, errors="coerce")

# Normalize turnover to decimal internally (0.75 = 75%)
if turnover_units.startswith("Decimal"):
    df["turnover"] = df["turnover_raw"]
    threshold = float(threshold_input)
else:
    df["turnover"] = df["turnover_raw"] / 100.0
    threshold = float(threshold_input) / 100.0

df["site"] = df[col_site].astype(str) if col_site != "(none)" else ""

df = df.dropna(subset=["lat", "lon"])
mapped_rows = len(df)
if mapped_rows == 0:
    st.error("No valid lat/lon rows after parsing. Check column mapping and data types.")
    st.stop()

# ---- Diagnostics (to catch the 'one blob' problem) ----
lat_min, lat_max = df["lat"].min(), df["lat"].max()
lon_min, lon_max = df["lon"].min(), df["lon"].max()
unique_coords = df[["lat", "lon"]].drop_duplicates().shape[0]

above = (df["turnover"] > threshold).sum()
below = mapped_rows - above
tmin, tmax = df["turnover"].min(), df["turnover"].max()

st.subheader("Data quality")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Rows mapped", f"{mapped_rows:,}")
c2.metric("Turnover mean", f"{df['turnover'].mean()*100:.2f}%")
c3.metric("Turnover min/max", f"{tmin*100:.1f}% / {tmax*100:.1f}%")
c4.metric("Below / Above threshold", f"{below:,} / {above:,}")
c5.metric("Coord unique", f"{unique_coords:,}")
c6.metric("Lat/Lon span", f"{(lat_max-lat_min):.2f} / {(lon_max-lon_min):.2f}")

if unique_coords < max(50, mapped_rows * 0.05):
    st.warning("Most rows share the same coordinates. That will look like a single blob. Check lat/lon columns.")

# ---- Radius ----
hc = df["avg_hc"].fillna(0).clip(lower=0)

if radius_mode.startswith("Sqrt"):
    radius = np.sqrt(hc) * float(radius_scale_m)
else:
    radius = hc * float(radius_scale_m)

df["radius_m"] = np.clip(radius, float(min_radius), float(max_radius))

# ---- Colors (TWO layers to guarantee reds render on top of greens) ----
delta = df["turnover"] - threshold
abs_delta = np.abs(delta.dropna())
scale = np.nanquantile(abs_delta, robust_q/100.0) if len(abs_delta) else 1.0
if not np.isfinite(scale) or scale == 0:
    scale = 1.0

t = np.clip(delta / scale, -1, 1)  # [-1,1]
intensity = (np.abs(t) * 255).astype(int)

df["intensity"] = intensity
df["is_above"] = df["turnover"] > threshold

df["turnover_pct"] = (df["turnover"] * 100).round(2).astype(str) + "%"
df["delta_pct"] = ((df["turnover"] - threshold) * 100).round(2).astype(str) + "%"

df_low = df[~df["is_above"]].copy()
df_high = df[df["is_above"]].copy()

# green layer (below threshold)
df_low["color"] = df_low["intensity"].apply(lambda v: [0, int(v), 0, int(alpha)])
# red layer (above threshold) - rendered last so it shows up
df_high["color"] = df_high["intensity"].apply(lambda v: [int(v), 0, 0, int(alpha)])

tooltip = {
    "html": "<b>Site:</b> {site}<br/>"
            "<b>Turnover:</b> {turnover_pct}<br/>"
            "<b>Avg HC:</b> {avg_hc}<br/>"
            "<b>Delta vs threshold:</b> {delta_pct}",
    "style": {"backgroundColor": "white", "color": "black"}
}

# Fit-ish view: pick zoom based on coordinate span
# crude but effective without extra deps
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
    latitude=float(df["lat"].mean()),
    longitude=float(df["lon"].mean()),
    zoom=zoom,
    pitch=0
)

low_layer = pdk.Layer(
    "ScatterplotLayer",
    data=df_low,
    get_position='[lon, lat]',
    get_radius="radius_m",
    radius_units="meters",
    get_fill_color="color",
    pickable=True,
    stroked=False
)

high_layer = pdk.Layer(
    "ScatterplotLayer",
    data=df_high,
    get_position='[lon, lat]',
    get_radius="radius_m",
    radius_units="meters",
    get_fill_color="color",
    pickable=True,
    stroked=False
)

deck = pdk.Deck(
    layers=[low_layer, high_layer],  # red on top
    initial_view_state=view_state,
    tooltip=tooltip,
    map_style="mapbox://styles/mapbox/light-v10"
)

st.subheader("Map")
st.pydeck_chart(deck, use_container_width=True)

with st.expander("Preview data used for mapping"):
    st.dataframe(df[["site", "lat", "lon", "avg_hc", "turnover_pct", "delta_pct", "radius_m", "is_above"]].head(300))
