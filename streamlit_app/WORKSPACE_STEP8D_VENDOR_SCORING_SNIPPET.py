# ===================== Vendor scoring (Step 8D fix) =====================
# Fixes: TypeError: Expected numeric dtype, got object instead.
# Handles blanks/"N/A"/None safely.

import numpy as np
import pandas as pd

# Ensure numeric dtypes (coerce bad values to NaN)
qdf["unit_price"] = pd.to_numeric(qdf.get("unit_price"), errors="coerce")
qdf["lead_time_days"] = pd.to_numeric(qdf.get("lead_time_days"), errors="coerce")

p = qdf["unit_price"]
lt = qdf["lead_time_days"]

def _minmax(s: pd.Series) -> pd.Series:
    s2 = s.astype("float64")
    mn, mx = np.nanmin(s2.values), np.nanmax(s2.values)
    if np.isnan(mn) or np.isnan(mx) or mx == mn:
        return pd.Series([0.0] * len(s2), index=s2.index, dtype="float64")
    return (s2 - mn) / (mx - mn)

# Replace with your own normalization if you already compute p_norm / lt_norm
p_norm = _minmax(p.fillna(np.nan))
lt_norm = _minmax(lt.fillna(np.nan))

# Force float dtype so .round() never fails
p_norm = pd.to_numeric(p_norm, errors="coerce").fillna(0.0).astype("float64")
lt_norm = pd.to_numeric(lt_norm, errors="coerce").fillna(0.0).astype("float64")

alpha = float(alpha) if "alpha" in globals() else 0.35
qdf["weighted_score"] = (p_norm + alpha * lt_norm).astype("float64").round(4)
# ===================== end vendor scoring fix =====================
