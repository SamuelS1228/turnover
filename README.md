# Turnover Map v2 — radius by Avg HC, color by Turnover vs Threshold

## Fixes vs v1
- Adds diagnostics: min/max turnover and count above/below threshold.
- Warns when 0 sites are above threshold (everything will be green).
- Adds sqrt radius scaling (recommended) to prevent the map from becoming a solid blob.
- Adds opacity control.
- Adds explicit turnover unit handling (decimal vs percent vs percent-string).

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```
