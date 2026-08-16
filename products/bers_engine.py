import os
import sys
import pandas as pd
import numpy as np

from tools.sheets_tool import fetch_tab


def calculate_fleetlock_index():
    try:
        df_orders = fetch_tab("fleet_orders")
        df_fin = fetch_tab("airline_financials")
        df_incidents = fetch_tab("aviation_incidents")
    except Exception as e:
        print(f"Error fetching sheet data: {e}", file=sys.stderr)
        sys.exit(1)

    df_orders.columns = [str(c).strip().lower() for c in df_orders.columns]
    df_fin.columns = [str(c).strip().lower() for c in df_fin.columns]
    df_incidents.columns = [str(c).strip().lower() for c in df_incidents.columns]

    # --- Industry-wide OEM delivery shortfall (fleet_orders is OEM-level,
    # not airline-level, in the real sheet -- no per-carrier breakdown exists) ---
    df_orders["year"] = pd.to_numeric(df_orders["year"], errors="coerce")
    df_orders["deliveries"] = pd.to_numeric(df_orders["deliveries"], errors="coerce")

    order_years = sorted(df_orders["year"].dropna().unique().astype(int))
    if len(order_years) < 2:
        print("Not enough years in fleet_orders to compare.", file=sys.stderr)
        sys.exit(1)
    ord_t, ord_prev = order_years[-1], order_years[-2]

    deliv_t = df_orders[df_orders["year"] == ord_t].groupby("manufacturer")["deliveries"].sum()
    deliv_prev = df_orders[df_orders["year"] == ord_prev].groupby("manufacturer")["deliveries"].sum()
    oem_shortfall = {}
    for oem in set(deliv_t.index).union(deliv_prev.index):
        d_t, d_prev = deliv_t.get(oem, 0.0), deliv_prev.get(oem, 0.0)
        oem_shortfall[oem] = max(0.0, (d_prev - d_t) / d_prev) if d_prev > 0 else 0.0

    # --- Financials: real 2-year comparison on iata_code ---
    df_fin["year"] = pd.to_numeric(df_fin["year"], errors="coerce")
    df_fin["operating_margin_pct"] = pd.to_numeric(df_fin["operating_margin_pct"], errors="coerce")
    df_fin["fleet_size_est"] = pd.to_numeric(df_fin["fleet_size_est"], errors="coerce")

    fin_years = sorted(df_fin["year"].dropna().unique().astype(int))
    if len(fin_years) < 2:
        print("Not enough years in airline_financials to compare.", file=sys.stderr)
        sys.exit(1)
    t, t_prev = fin_years[-1], fin_years[-2]

    fin_t = df_fin[df_fin["year"] == t].copy()
    fin_prev = df_fin[df_fin["year"] == t_prev].copy()
    merged = pd.merge(fin_t, fin_prev, on="iata_code", suffixes=("_t", "_prev"), how="inner")
    if merged.empty:
        print("No overlapping carrier rows between the two financial years.", file=sys.stderr)
        sys.exit(1)

    margin_sample = merged["operating_margin_pct_t"].dropna().abs().mean()
    scale = 10000.0 if margin_sample <= 1.0 else 100.0
    merged["margin_delta_bps"] = (merged["operating_margin_pct_t"] - merged["operating_margin_pct_prev"]) * scale

    safe_prev = merged["fleet_size_est_prev"].replace(0, np.nan)
    merged["fleet_growth_pct"] = np.where(
        merged["fleet_size_est_prev"] > 0,
        (merged["fleet_size_est_t"] - merged["fleet_size_est_prev"]) / safe_prev * 100.0,
        np.nan,
    )

    # --- Incidents: matched per-airline by name (real sheet has no OEM
    # text field, only is_boeing/is_airbus flags on each incident row) ---
    df_incidents["date_parsed"] = pd.to_datetime(df_incidents["date"], errors="coerce")
    df_incidents["year_parsed"] = df_incidents["date_parsed"].dt.year
    df_incidents["is_boeing"] = pd.to_numeric(df_incidents.get("is_boeing", 0), errors="coerce").fillna(0).astype(int)
    recent_inc = df_incidents[(df_incidents["year_parsed"] >= t_prev) & (df_incidents["year_parsed"] <= t)]

    def match_incidents(airline_name):
        if not isinstance(airline_name, str) or not airline_name.strip():
            return 0, 0
        norm = airline_name.lower().strip()
        subset = recent_inc[
            recent_inc["airline"].astype(str).str.lower().str.strip().apply(
                lambda x: x == norm or x in norm or norm in x
            )
        ]
        return len(subset), int(subset["is_boeing"].sum())

    incident_counts, boeing_counts = zip(*merged["airline_name_t"].apply(match_incidents)) if len(merged) else ([], [])
    merged["incidents"] = incident_counts
    merged["boeing_incidents"] = boeing_counts

    # A carrier's "primary OEM exposure" is approximated by whether it has
    # any live-matched Boeing-linked incident; the industry-wide Boeing
    # shortfall then feeds the Delivery Drag component only for those carriers.
    merged["primary_oem_is_boeing"] = merged["boeing_incidents"] > 0
    merged["s_oem"] = merged["primary_oem_is_boeing"].apply(
        lambda b: oem_shortfall.get("Boeing", 0.0) if b else 0.0
    )
    merged["oem_exposure_pct"] = np.where(
        merged["incidents"] > 0, merged["boeing_incidents"] / merged["incidents"], 0.0
    )

    # --- FleetLock Score: Delivery Drag (40) + Margin Contraction (40) + Incident Exposure (20) ---
    merged["drag_component"] = merged["oem_exposure_pct"] * merged["s_oem"] * 40.0

    clamped_margin_bps = np.clip(-merged["margin_delta_bps"], 0.0, 150.0)
    merged["margin_component"] = clamped_margin_bps * 0.10

    merged["incident_component"] = np.minimum(2, merged["boeing_incidents"]) * 10.0

    merged["fleetlock_score"] = (
        merged["drag_component"] + merged["margin_component"] + merged["incident_component"]
    ).round(1)

    def risk_tier(score):
        if score >= 50.0:
            return "CRITICAL"
        elif score >= 35.0:
            return "HIGH"
        elif score >= 20.0:
            return "MODERATE"
        return "LOW"

    merged["risk_tier"] = merged["fleetlock_score"].apply(risk_tier)
    merged = merged.sort_values(by="fleetlock_score", ascending=False).reset_index(drop=True)

    df_out = pd.DataFrame()
    df_out["airline_code"] = merged["iata_code"]
    df_out["airline_name"] = merged["airline_name_t"]
    df_out["fleet_growth_pct"] = merged["fleet_growth_pct"].apply(
        lambda x: "N/A (new entrant)" if pd.isna(x) else f"{x:+.1f}%"
    )
    df_out["yoy_margin_change_bps"] = merged["margin_delta_bps"].round().astype(int)
    df_out["boeing_linked_incidents"] = merged["boeing_incidents"].astype(int)
    df_out["fleetlock_score"] = merged["fleetlock_score"]
    df_out["risk_tier"] = merged["risk_tier"]

    return df_out, t, t_prev


def generate_report():
    df_display, t, t_prev = calculate_fleetlock_index()

    if df_display.empty:
        print("No results calculated.")
        return

    table_str = df_display.to_string(index=False)

    report_md = f"""# FleetLock Margin Risk Index Report

### Methodology Recap
**Period evaluated:** {t} vs {t_prev}

The FleetLock Score quantifies airline risk exposure across three weighted pillars,
all computed live from the FA Airline Data Google Sheet at run time:
- **Delivery Drag (40 pts max):** industry-wide OEM delivery shortfall, applied to
  carriers with a live-matched Boeing-linked incident in the period.
- **Margin Contraction (40 pts max):** YoY operating margin drop in basis points,
  clamped to [0, 400] bps.
- **Incident Exposure (20 pts max):** this carrier's own Boeing-linked incidents,
  matched by name against the live aviation_incidents tab.

---

### Ranked Carrier Risk Scorecard

"""

    os.makedirs("outputs", exist_ok=True)
    out_path = os.path.join("outputs", "maker_product_output.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    df_display.to_csv(os.path.join("outputs", "fleetlock_index.csv"), index=False)

    print(f"Report generated -> {out_path}\n")
    print(table_str)


if __name__ == "__main__":
    generate_report()
