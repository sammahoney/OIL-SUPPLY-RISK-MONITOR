from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd
from shipping_stress import shipping_stress_breakdown, SHIPPING_STRESS_VERSION
from oil import get_oil_price
from risk import risk_score
from chokepoints import get_history_table
from polymarket import find_relevant_markets
from spr import get_spr_status
from eurostat_reserves import get_reserves_history, COUNTRIES as EUROSTAT_COUNTRIES

st.set_page_config(page_title="Oil Supply Risk Monitor", layout="wide")

DAYS_9MO = 270  # fixed window across every historical chart, no selector

COUNTRY_NAMES = {
    "DE": "Germany", "FR": "France", "HR": "Croatia",
    "IT": "Italy", "HU": "Hungary",
}

st.title("OIL SUPPLY RISK MONITOR")
st.caption(f"shipping_stress module: {SHIPPING_STRESS_VERSION}")


# --- Cached fetchers -------------------------------------------------------
# TTLs match how often each underlying source actually updates -- no point
# re-checking monthly/weekly sources every 30 minutes.

@st.cache_data(ttl=1800)
def get_cached_breakdown():
    return shipping_stress_breakdown()


@st.cache_data(ttl=1800)
def get_cached_price():
    return get_oil_price()


@st.cache_data(ttl=1800)
def get_cached_polymarket():
    return find_relevant_markets()


@st.cache_data(ttl=3600 * 6)
def get_cached_hormuz_history():
    return get_history_table("Strait of Hormuz", days=DAYS_9MO)


@st.cache_data(ttl=3600 * 6)
def get_cached_spr():
    return get_spr_status()


@st.cache_data(ttl=3600 * 12)
def get_cached_reserves():
    return get_reserves_history(months=9)


breakdown = get_cached_breakdown()
stress = breakdown["combined"]
price = get_cached_price()
risk = risk_score(stress, price)

if st.button("Force refresh now"):
    get_cached_breakdown.clear()
    get_cached_price.clear()
    get_cached_polymarket.clear()
    get_cached_hormuz_history.clear()
    get_cached_spr.clear()
    get_cached_reserves.clear()
    st.rerun()


# --- Row 1: Croatia vs EU reserves | Hormuz tanker transits ----------------
row1_col1, row1_col2 = st.columns(2)

with row1_col1:
    with st.container(border=True):
        st.subheader("Croatia vs EU oil reserves (9 month view)")
        reserves = get_cached_reserves()

        if not reserves:
            st.info(
                "Not configured yet -- run `python eurostat_reserves.py` to "
                "discover the right Eurostat dimension codes, set them in "
                "the file, then this chart will populate."
            )
        else:
            frames = []
            for geo_code, series in reserves.items():
                s = pd.Series(series, name=COUNTRY_NAMES.get(geo_code, geo_code))
                frames.append(s)
            df = pd.concat(frames, axis=1)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            st.line_chart(df)
            st.caption(
                "Source: Eurostat (nrg_stk_oem), emergency oil stocks in "
                "days-equivalent of cover. Monthly data, published with a "
                "multi-month lag."
            )

with row1_col2:
    with st.container(border=True):
        st.subheader("Strait of Hormuz tankers (9 month view)")
        hormuz_history = get_cached_hormuz_history()

        if not hormuz_history:
            st.write("No data available.")
        else:
            hdf = pd.DataFrame(hormuz_history)
            hdf["date"] = pd.to_datetime(hdf["date"])
            hdf = hdf.set_index("date").sort_index()
            hdf["n_tanker_7d_avg"] = hdf["n_tanker"].rolling(7, min_periods=1).mean()
            st.line_chart(hdf[["n_tanker", "n_tanker_7d_avg"]])
            st.caption(
                "Source: IMF PortWatch, daily tanker transit counts. "
                "~7 day publication lag."
            )


# --- Row 2: US SPR gauge | Polymarket signal -------------------------------
row2_col1, row2_col2 = st.columns(2)

with row2_col1:
    with st.container(border=True):
        st.subheader("US SPR (current)")
        spr = get_cached_spr()

        if not spr:
            st.write("No data available.")
        else:
            low_pct = spr["all_time_low_pct"]
            high_pct = spr["all_time_high_pct"]
            current_pct = spr["utilization_pct"]
            # position of the current marker along the low->high range, as a %
            span = high_pct - low_pct
            marker_pos = ((current_pct - low_pct) / span * 100) if span > 0 else 50
            marker_pos = max(0, min(100, marker_pos))

            st.markdown(f"""
            <div style="font-family:sans-serif;">
              <div style="display:flex; justify-content:space-between; font-size:0.85em; color:#888;">
                <span>All-Time Low: {spr['all_time_low_million_bbl']}M ({low_pct}%)</span>
                <span>All-Time High: {spr['all_time_high_million_bbl']}M ({high_pct}%)</span>
              </div>
              <div style="position:relative; height:18px; background:#eee; border-radius:9px; margin:6px 0;">
                <div style="position:absolute; left:0; top:0; height:100%; width:{marker_pos}%;
                            background:#2b6cb0; border-radius:9px;"></div>
              </div>
              <div style="text-align:center; font-size:1.1em; font-weight:600;">
                {spr['current_million_bbl']}M bbl ({spr['utilization_pct']}% of {spr['capacity_million_bbl']}M capacity)
              </div>
            </div>
            """, unsafe_allow_html=True)

            if spr.get("week_over_week_million_bbl") is not None:
                direction = "up" if spr["week_over_week_million_bbl"] > 0 else "down"
                st.caption(f"{direction} {abs(spr['week_over_week_million_bbl'])}M bbl vs last week")
            st.caption("Source: EIA Weekly Petroleum Status Report.")

with row2_col2:
    with st.container(border=True):
        st.subheader("Iran/Gulf Prediction Market Signal (Polymarket, not scored)")
        polymarket_matches = get_cached_polymarket()

        if not polymarket_matches:
            st.write("No relevant active Polymarket markets found right now.")
        else:
            top = max(polymarket_matches, key=lambda m: m["yes_probability"])
            st.metric(top["market_question"], f"{top['yes_probability']}%")

            with st.expander("All matching markets"):
                df_poly = pd.DataFrame(polymarket_matches).sort_values(
                    "yes_probability", ascending=False
                )
                st.dataframe(
                    df_poly.rename(columns={
                        "market_question": "Market",
                        "yes_probability": "Yes %",
                        "volume_24hr": "24h Volume ($)",
                        "event_title": "Event",
                    }),
                    use_container_width=True,
                )
        st.caption(
            "Source: Polymarket Gamma API. Market-priced probability, "
            "not a stress score -- kept separate from Risk Score."
        )


# --- Bottom: main risk summary hero panel ----------------------------------
st.divider()

if risk is None:
    status_color, status_text = "#666", "NO DATA"
elif risk > 70:
    status_color, status_text = "#c53030", "HIGH RISK REGIME"
elif risk > 40:
    status_color, status_text = "#b7791f", "ELEVATED RISK"
else:
    status_color, status_text = "#2f855a", "STABLE"

vessel_display = breakdown["hormuz_live_vessel_count"] if breakdown["hormuz_live_vessel_count"] is not None else "N/A"
price_display = price if price is not None else "N/A"
risk_display = round(risk, 2) if risk is not None else "N/A"

st.markdown(f"""
<div style="background:#0d1117; padding:24px; border-radius:12px; font-family:sans-serif; color:white;">
  <div style="display:flex; justify-content:space-around; text-align:center;">
    <div>
      <div style="color:#9aa5b1; font-size:0.85em;">Hormuz Live Vessel Count (spot check, not scored)</div>
      <div style="font-size:2.2em; font-weight:700;">{vessel_display}</div>
    </div>
    <div>
      <div style="color:#9aa5b1; font-size:0.85em;">Oil Price</div>
      <div style="font-size:2.2em; font-weight:700;">{price_display}</div>
    </div>
    <div>
      <div style="color:#9aa5b1; font-size:0.85em;">Risk Score</div>
      <div style="font-size:2.2em; font-weight:700;">{risk_display}</div>
    </div>
  </div>
  <div style="background:{status_color}; margin-top:20px; padding:12px; border-radius:8px; text-align:center; font-weight:600;">
    {status_text}
  </div>
</div>
""", unsafe_allow_html=True)

with st.expander("Shipping stress breakdown", expanded=True):
    st.write(f"**Combined shipping stress:** "
             f"{round(stress, 1) if stress is not None else 'N/A'}")
    st.write(f"- Hormuz transit (live, IMF PortWatch): "
             f"{round(breakdown['hormuz_transit_score'], 1) if breakdown['hormuz_transit_score'] is not None else 'N/A'}")
    if breakdown.get("hormuz_transit_latest") is not None:
        st.caption(
            f"  Latest tanker transits: {breakdown['hormuz_transit_latest']} "
            f"vs baseline {breakdown['hormuz_transit_baseline']} "
            f"({breakdown['hormuz_transit_pct_change']:+.1f}%)"
        )
    st.write(f"- News signal (GDELT, Hormuz/Gulf disruption coverage): "
             f"{round(breakdown['news_score'], 1) if breakdown['news_score'] is not None else 'N/A'}")
    st.caption(
        "PortWatch data has a ~7 day publication lag and is cached up to "
        "6 hours. News signal updates roughly every 30 minutes. Freight "
        "rate and Suez transit were dropped from this score in the "
        "redesign -- see shipping_stress.py for the current weighting."
    )
