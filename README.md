# Turnover Heatmap (Streamlit)

Upload a CSV with:
- `lat` (latitude)
- `lon` / `long` (longitude)
- `turnover %` (either 0–100 or 0–1)
- `avg hc` (average headcount)

The app renders a heatmap and lets you weight each point by Avg HC:
- **Turnover only** (rate hotspots)
- **Turnover × Avg HC** (people-impacted hotspots)

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)
1. Push this repo to GitHub
2. Create a new Streamlit app
3. Set main file path to `app.py`

## Example CSV
See `data/example_turnover_points.csv`
