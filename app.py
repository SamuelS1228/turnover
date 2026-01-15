import io
import pandas as pd
import streamlit as st
import pydeck as pdk

st.set_page_config(page_title="Turnover Heatmap", layout="wide")

st.title("Turnover Heatmap (weighted by Avg HC)")
st.caption("Upload a CSV with lat, lon, turnover %, and avg headcount. Visualize turnover intensity and optionally weight by headcount.")

# ---------------- Helpers ----------------
def find_col(df_cols, candidates):
    lower = {c.lower(): c for c in df_cols}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None

def to_float(s):
    return pd.to_numeric(s, errors="coerce")

def normalize_turnover(series, is_pct_0_100: bool):
    x = to_float(series)
    if is_pct_0_100:
        return x / 100.0
    return x

def clamp(series, lo, hi):
    return series.clip(lower=lo, upper=hi)

# ---------------- Sidebar ----------------
st.sidebar.header("Upload")
uploaded = st.sidebar.file_uploader("CSV file", type=["csv"])

st.sidebar.markdown("---")
st.sidebar.header("Columns")
lat_col_override = st.sidebar.text_input("Latitude column (optional)", value="")
lon_col_override = st.sidebar.text_input("Longitude column (optional)", value="")
turn_col_override = st.sidebar.text_input("Turnover % column (optional)", value="")
hc_col_override = st.sidebar.text_input("Avg HC column (optional)", value="")

st.sidebar.markdown("---")
st.sidebar.header("Interpretation")
turnover_is_0_100 = st.sidebar.checkbox("Turnover is 0–100 (%)", value=True)

st.sidebar.markdown("---")
st.sidebar.header("Weighting")
weight_mode = st.sidebar.radio(
    "Heat weight",
    options=["Turnover only", "Turnover × Avg HC"],
    index=1
)

hc_cap_enabled = st.sidebar.checkbox("Cap Avg HC (reduces domination by huge sites)", value=True)
hc_cap_value = st.sidebar.number_input("Avg HC cap", min_value=1.0, value=200.0, step=10.0, disabled=not hc_cap_enabled)

st.sidebar.markdown("---")
st.sidebar.header("Map controls")
radius_pixels = st.sidebar.slider("Heat radius (pixels)", 10, 120, 45, step=5)
intensity = st.sidebar.slider("Heat intensity", 1.0, 5.0, 1.6, step=0.1)
threshold = st.sidebar.slider("Heat threshold", 0.0, 1.0, 0.05, step=0.01)

show_points = st.sidebar.checkbox("Show points", value=True)
point_radius = st.sidebar.slider("Point radius (meters)", 1000, 30000, 9000, step=1000)

# ---------------- Main ----------------
if not uploaded:
    st.info("Upload a CSV to begin. Required fields: lat, lon, turnover %, avg hc.")
    st.stop()

try:
    raw = pd.read_csv(uploaded)
except Exception:
    uploaded.seek(0)
    raw = pd.read_csv(io.StringIO(uploaded.getvalue().decode("utf-8", errors="ignore")))

st.subheader("Preview")
st.dataframe(raw.head(25), use_container_width=True)

cols = list(raw.columns)

lat_col = lat_col_override.strip() or find_col(cols, ["lat", "latitude", "y", "site_lat", "store_lat"])
lon_col = lon_col_override.strip() or find_col(cols, ["lon", "long", "lng", "longitude", "x", "site_lon", "store_lon"])
turn_col = turn_col_override.strip() or find_col(cols, ["turnover_pct", "turnover%", "turnover", "attrition_pct", "attrition", "turnover percent", "turnover_percentage"])
hc_col = hc_col_override.strip() or find_col(cols, ["avg_hc", "avg hc", "average_hc", "average hc", "headcount", "hc", "avg_headcount"])

missing = [name for name, col in [("lat", lat_col), ("lon", lon_col), ("turnover", turn_col), ("avg hc", hc_col)] if (col is None or col not in raw.columns)]
if missing:
    st.error(f"Couldn't find required column(s): {', '.join(missing)}. Set them explicitly in the sidebar.")
    st.stop()

df = raw.copy()
df["lat"] = to_float(df[lat_col])
df["lon"] = to_float(df[lon_col])
df["turnover"] = normalize_turnover(df[turn_col], turnover_is_0_100)
df["avg_hc"] = to_float(df[hc_col])

df = df.dropna(subset=["lat", "lon", "turnover", "avg_hc"])

# Basic sanity: turnover as fraction
df["turnover"] = clamp(df["turnover"], 0.0, 1.0)

if hc_cap_enabled:
    df["avg_hc_used"] = clamp(df["avg_hc"], 0.0, float(hc_cap_value))
else:
    df["avg_hc_used"] = df["avg_hc"]

# Weight definition for HeatmapLayer
if weight_mode == "Turnover × Avg HC":
    # Weight is proportional to "headcount exposed to turnover"
    df["weight"] = df["turnover"] * df["avg_hc_used"]
else:
    df["weight"] = df["turnover"]

# Show join/quality stats
st.markdown("### Data quality")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Rows mapped", f"{len(df):,}")
c2.metric("Turnover mean", f"{(df['turnover'].mean() * 100):.1f}%")
c3.metric("Avg HC mean", f"{df['avg_hc'].mean():.1f}")
c4.metric("Weight mean", f"{df['weight'].mean():.3f}")

# Map centering
center_lat = float(df["lat"].mean()) if len(df) else 39.5
center_lon = float(df["lon"].mean()) if len(df) else -98.35

# Layers
heat_layer = pdk.Layer(
    "HeatmapLayer",
    data=df,
    get_position="[lon, lat]",
    get_weight="weight",
    radius_pixels=radius_pixels,
    intensity=intensity,
    threshold=threshold,
    pickable=False,
)

# Points colored by turnover for quick inspection
df["turnover_pct_display"] = df["turnover"] * 100.0

point_layer = pdk.Layer(
    "ScatterplotLayer",
    data=df,
    get_position="[lon, lat]",
    get_radius=point_radius,
    get_fill_color="[255, 80, 80, 120]",
    pickable=True,
)

layers = [heat_layer] + ([point_layer] if show_points else [])

tooltip = {
    "html": (
        "<b>Turnover:</b> {turnover_pct_display}%<br/>"
        "<b>Avg HC:</b> {avg_hc}<br/>"
        "<b>Weight:</b> {weight}"
    ),
    "style": {"backgroundColor": "white", "color": "black"},
}

st.markdown("## Map")
st.pydeck_chart(
    pdk.Deck(
        map_style="mapbox://styles/mapbox/light-v9",
        initial_view_state=pdk.ViewState(
            latitude=center_lat,
            longitude=center_lon,
            zoom=3.6,
        ),
        layers=layers,
        tooltip=tooltip if show_points else None,
    ),
    use_container_width=True,
)

st.markdown("## Download")
out = df.copy()
out["turnover_pct"] = out["turnover"] * 100.0
csv_bytes = out.to_csv(index=False).encode("utf-8")
st.download_button(
    "Download cleaned + computed weights CSV",
    data=csv_bytes,
    file_name="turnover_heatmap_enriched.csv",
    mime="text/csv",
)

with st.expander("What the weighting means"):
    st.write(
        "- **Turnover only**: heat intensity reflects where turnover rates are higher.\n"
        "- **Turnover × Avg HC**: heat intensity reflects where *more people are affected* by turnover (high turnover + high headcount pops).\n"
        "- Use **Avg HC cap** if a few mega-sites drown everything else."
    )
