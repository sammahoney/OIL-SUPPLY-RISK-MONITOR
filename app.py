from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import pandas as pd
import altair as alt
from oil import get_oil_price_history
from chokepoints import get_history_table, get_transit_comparison
from polymarket import find_relevant_markets
from spr import get_spr_status, get_spr_history
from eurostat_reserves import get_reserves_history, get_jet_fuel_history
from eurostat_trade import get_import_history, PARTNERS
from gdelt import get_recent_headlines

st.set_page_config(page_title="Oil Supply Data Monitor", layout="wide")

# Streamlit's top header is fixed/absolute by default and can sit on top
# of content. Collapsing it to zero height keeps it out of the way.
st.markdown("""
<style>
header.stAppHeader {
    min-height: 0;
    height: 0;
    z-index: -1;
}
</style>
""", unsafe_allow_html=True)

MONTHS_WINDOW = 9
DAYS_WINDOW = MONTHS_WINDOW * 30

COUNTRY_NAMES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia",
    "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
    "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece",
    "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SK": "Slovakia",
    "SI": "Slovenia", "ES": "Spain", "SE": "Sweden",
}

# Full opacity by default; everything else sits dimmed until hovered.
# DE/FR/IT/ES/PL = five largest EU economies. Croatia stays in the data
# (hoverable like any other country) but isn't emphasized by default.
MAJOR_COUNTRIES = {"DE", "FR", "IT", "ES", "PL"}

title_col, button_col = st.columns([5, 1])
with title_col:
    st.title("OIL SUPPLY DATA MONITOR")


# --- Cached fetchers -------------------------------------------------------

@st.cache_data(ttl=3600 * 6)
def get_cached_price_history():
    return get_oil_price_history(days=365)


@st.cache_data(ttl=1800)
def get_cached_headlines():
    return get_recent_headlines(limit=8)


@st.cache_data(ttl=1800)
def get_cached_polymarket():
    return find_relevant_markets()


@st.cache_data(ttl=3600 * 6)
def get_cached_hormuz_history():
    return get_history_table("Strait of Hormuz", days=DAYS_WINDOW)


@st.cache_data(ttl=3600 * 6)
def get_cached_hormuz_comparison():
    return get_transit_comparison("Strait of Hormuz")


@st.cache_data(ttl=3600 * 6)
def get_cached_spr():
    return get_spr_status()


@st.cache_data(ttl=3600 * 6)
def get_cached_spr_history():
    return get_spr_history(years=3)


@st.cache_data(ttl=3600 * 12)
def get_cached_reserves():
    return get_reserves_history(months=MONTHS_WINDOW)


@st.cache_data(ttl=3600 * 12)
def get_cached_jet_fuel():
    return get_jet_fuel_history(months=MONTHS_WINDOW)


@st.cache_data(ttl=3600 * 12)
def get_cached_imports():
    return get_import_history(months=MONTHS_WINDOW)


with button_col:
    refresh_clicked = st.button("Force refresh now")

if refresh_clicked:
    # Clearing Streamlit's cache alone isn't enough -- several of these
    # sources also have their own disk-based cache underneath (see
    # eurostat_reserves.py, chokepoints.py, spr.py, polymarket.py), which
    # Streamlit's cache.clear() doesn't touch. Explicitly force-refresh
    # each disk cache first, then clear Streamlit's cache so the next
    # render reads the now-fresh disk cache instead of a stale one.
    get_reserves_history(months=MONTHS_WINDOW, force_refresh=True)
    get_jet_fuel_history(months=MONTHS_WINDOW, force_refresh=True)
    get_history_table("Strait of Hormuz", days=DAYS_WINDOW, force_refresh=True)
    get_transit_comparison("Strait of Hormuz", force_refresh=True)
    get_spr_status(force_refresh=True)
    find_relevant_markets(force_refresh=True)

    get_cached_price_history.clear()
    get_cached_headlines.clear()
    get_cached_polymarket.clear()
    get_cached_hormuz_history.clear()
    get_cached_hormuz_comparison.clear()
    get_cached_spr.clear()
    get_cached_spr_history.clear()
    get_cached_reserves.clear()
    get_cached_jet_fuel.clear()
    st.rerun()


def build_country_chart(reserves: dict, y_title: str):
    """
    Shared chart builder for the reserves and jet fuel panels: one line
    per EU country, majors (+ Croatia) at full opacity by default, all
    others dimmed. Hovering a legend entry brings that one country to
    full opacity and dims everyone else, then reverts to the default
    major/minor state when the mouse leaves the legend.
    """
    rows = []
    for geo_code, series in reserves.items():
        country = COUNTRY_NAMES.get(geo_code, geo_code)
        is_major = geo_code in MAJOR_COUNTRIES
        for month, value in series.items():
            rows.append({
                "country": country,
                "date": month,
                "value": value,
                "is_major": is_major,
            })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # Legend order: majors (alphabetical), then Croatia, then everyone
    # else alphabetical -- so Croatia is easy to find even though it's
    # not emphasized by default.
    major_names = sorted(COUNTRY_NAMES[c] for c in MAJOR_COUNTRIES if c in reserves)
    other_codes = [c for c in reserves if c not in MAJOR_COUNTRIES and c != "HR"]
    other_names = sorted(COUNTRY_NAMES.get(c, c) for c in other_codes)
    legend_order = major_names + (["Croatia"] if "HR" in reserves else []) + other_names

    selection = alt.selection_point(
        fields=["country"], on="mouseover", bind="legend",
        nearest=False, empty=False, name="hover_select",
    )

    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=False)),
            color=alt.Color("country:N", title="Country", sort=legend_order),
            opacity=alt.condition(
                selection,
                alt.value(1.0),
                alt.Opacity("default_opacity:Q", legend=None),
            ),
            tooltip=["country", "date", "value"],
        )
        .transform_calculate(default_opacity="datum.is_major ? 1.0 : 0.25")
        .add_params(selection)
        .properties(height=320)
    )

    return chart


row1_col1, row1_col2 = st.columns(2)

with row1_col1:
    with st.container(border=True):
        st.subheader(f"EU oil reserves, days of cover ({MONTHS_WINDOW} months)")
        reserves = get_cached_reserves()

        if not reserves:
            st.info(
                "Not configured yet -- run `python eurostat_reserves.py` "
                "first (see file for setup)."
            )
        else:
            st.altair_chart(build_country_chart(reserves, "Days of cover"),
                             use_container_width=True)
            st.caption(
                "Source: Eurostat (nrg_stk_oem), emergency oil stocks in "
                "days-equivalent of cover. Monthly, multi-month publication "
                "lag. Hover a country in the legend to isolate it."
            )

with row1_col2:
    with st.container(border=True):
        st.subheader(f"Strait of Hormuz tanker transits ({MONTHS_WINDOW} months)")
        hormuz_history = get_cached_hormuz_history()
        comparison = get_cached_hormuz_comparison()

        if not hormuz_history:
            st.write("No data available.")
        else:
            hdf = pd.DataFrame(hormuz_history)
            hdf["date"] = pd.to_datetime(hdf["date"])
            hdf = hdf.sort_values("date")
            hdf["n_tanker_7d_avg"] = hdf["n_tanker"].rolling(7, min_periods=1).mean()

            # Reference line: average over the first 60 days of this window,
            # i.e. the earliest data shown -- a plain "what it looked like
            # at the start of this chart" marker, not a claim about what's
            # "normal" or "safe".
            early_window = hdf.head(60)
            reference_value = early_window["n_tanker"].mean() if not early_window.empty else None

            base = alt.Chart(hdf).mark_line().encode(
                x=alt.X("date:T", title=None),
            )
            tanker_line = base.encode(
                y=alt.Y("n_tanker:Q", title="Tanker transits/day"),
                color=alt.value("#1f77b4"),
            )
            avg_line = base.encode(
                y=alt.Y("n_tanker_7d_avg:Q", title="Tanker transits/day"),
                color=alt.value("#ff7f0e"),
            )
            layers = [tanker_line, avg_line]

            if reference_value is not None:
                ref_df = pd.DataFrame({"y": [reference_value]})
                ref_line = alt.Chart(ref_df).mark_rule(
                    strokeDash=[4, 4], color="#888"
                ).encode(y="y:Q")
                layers.append(ref_line)

            st.altair_chart(alt.layer(*layers).properties(height=320),
                             use_container_width=True)

            caption = "Source: IMF PortWatch, daily tanker transit counts. ~7 day publication lag."
            if reference_value is not None:
                caption += f" Dashed line: average over the first 60 days shown here ({reference_value:.0f}/day)."
            st.caption(caption)

            if comparison and comparison.get("pct_change") is not None:
                st.caption(
                    f"Most recent day: {comparison['latest']} transits, vs "
                    f"{comparison['baseline']} trailing 180-day average "
                    f"({comparison['pct_change']:+.1f}%)."
                )


row2_col1, row2_col2 = st.columns(2)

with row2_col1:
    with st.container(border=True):
        st.subheader("US SPR (3 years)")
        spr = get_cached_spr()
        spr_history = get_cached_spr_history()

        if not spr or not spr_history or not spr_history["series"]:
            st.write("No data available.")
        else:
            sdf = pd.DataFrame(spr_history["series"])
            sdf["date"] = pd.to_datetime(sdf["date"])

            all_time_high = spr_history["all_time_high_million_bbl"]
            all_time_low = spr_history["all_time_low_million_bbl"]

            level_line = alt.Chart(sdf).mark_line().encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("value_million_bbl:Q", title="Million barrels",
                        scale=alt.Scale(zero=False)),
                tooltip=["date", "value_million_bbl"],
            )

            high_df = pd.DataFrame({"y": [all_time_high]})
            low_df = pd.DataFrame({"y": [all_time_low]})
            high_line = alt.Chart(high_df).mark_rule(
                strokeDash=[4, 4], color="#2f855a"
            ).encode(y="y:Q")
            low_line = alt.Chart(low_df).mark_rule(
                strokeDash=[4, 4], color="#c53030"
            ).encode(y="y:Q")

            st.altair_chart(
                alt.layer(level_line, high_line, low_line).properties(height=320),
                use_container_width=True,
            )

            st.caption(
                f"Current: {spr['current_million_bbl']}M bbl "
                f"({spr['utilization_pct']}% of {spr['capacity_million_bbl']}M capacity). "
                f"Green line: all-time high ({all_time_high}M, Dec 2009 -- back when "
                f"authorized capacity was also higher, since reduced to today's 714M). "
                f"Red line: all-time low ({all_time_low}M)."
            )
            if spr.get("week_over_week_million_bbl") is not None:
                direction = "up" if spr["week_over_week_million_bbl"] > 0 else "down"
                st.caption(f"{direction} {abs(spr['week_over_week_million_bbl'])}M bbl vs last week")
            st.caption("Source: EIA Weekly Petroleum Status Report.")

with row2_col2:
    with st.container(border=True):
        st.subheader(f"EU jet fuel stocks, thousand tonnes ({MONTHS_WINDOW} months)")
        jet_fuel = get_cached_jet_fuel()

        if not jet_fuel:
            st.info(
                "Not configured yet -- run `python eurostat_reserves.py` "
                "and check the jet fuel discovery output (see file)."
            )
        else:
            st.altair_chart(build_country_chart(jet_fuel, "Thousand tonnes"),
                             use_container_width=True)
            st.caption(
                "Source: Eurostat (nrg_stk_oilm), kerosene-type jet fuel, "
                "closing stock on national territory. Monthly, multi-month "
                "publication lag. Hover a country in the legend to isolate it."
            )


# --- Row 3: Oil price | EU crude oil imports by source ---------------------
row3_col1, row3_col2 = st.columns(2)

with row3_col1:
    with st.container(border=True):
        st.subheader("WTI Crude Oil Price (12 months)")
        price_history = get_cached_price_history()

        if not price_history:
            st.write("No data available.")
        else:
            pdf = pd.DataFrame(price_history)
            pdf["date"] = pd.to_datetime(pdf["date"])

            # Explicit Altair instead of st.line_chart -- Streamlit's native
            # line_chart has scroll-to-zoom on by default, which here just
            # rescales the same already-loaded data with nothing new to show,
            # a dead-end interaction. Plain alt.Chart has no zoom unless you
            # add .interactive(), so this avoids it entirely.
            price_chart = alt.Chart(pdf).mark_line().encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("price:Q", title="USD/barrel", scale=alt.Scale(zero=False)),
                tooltip=["date", "price"],
            ).properties(height=320)

            st.altair_chart(price_chart, use_container_width=True)
            latest = price_history[-1]
            st.caption(f"Source: EIA (PET.RWTC.D). Latest: ${latest['price']:.2f} on {latest['date']}.")

with row3_col2:
    with st.container(border=True):
        st.subheader(f"EU crude oil imports by source ({MONTHS_WINDOW} months)")
        imports = get_cached_imports()

        if not imports:
            st.write("No data available.")
        else:
            named_codes = [c for c in PARTNERS if c != "TOTAL"]

            rows = []
            for code, series in imports.items():
                if code == "TOTAL":
                    continue
                label = PARTNERS.get(code, code)
                for month, value in series.items():
                    rows.append({"source": label, "date": month, "value": value})

            # "Other sources" = TOTAL minus whatever's covered by the named
            # countries above, for each month TOTAL has data for. This reads
            # as "everyone else combined" instead of a much larger absolute
            # number the person has to mentally subtract from.
            total_series = imports.get("TOTAL", {})
            for month, total_value in total_series.items():
                named_sum = sum(
                    imports.get(code, {}).get(month, 0) for code in named_codes
                )
                rows.append({
                    "source": "Other sources",
                    "date": month,
                    "value": total_value - named_sum,
                })

            idf = pd.DataFrame(rows)
            idf["date"] = pd.to_datetime(idf["date"])

            imports_chart = alt.Chart(idf).mark_line().encode(
                x=alt.X("date:T", title=None),
                y=alt.Y("value:Q", title="Thousand tonnes/month", scale=alt.Scale(zero=False)),
                color=alt.Color("source:N", title="Source"),
                tooltip=["source", "date", "value"],
            ).properties(height=320)

            st.altair_chart(imports_chart, use_container_width=True)
            st.caption(
                "Source: Eurostat (nrg_ti_oilm), crude oil imports by partner "
                "country. 'Other sources' = EU total imports minus the named "
                "countries shown here, not a Eurostat category itself. "
                "Monthly, multi-month publication lag."
            )


# --- News headlines: presented as-is, not scored ---------------------------
st.divider()
st.subheader("Recent Hormuz/Gulf shipping headlines")
st.caption("For a quick sense of current coverage -- not weighted or scored, just a list.")

headlines = get_cached_headlines()

if not headlines:
    st.write("No recent matching headlines found.")
else:
    for h in headlines:
        date_display = h["date"][:8] if h.get("date") else "?"
        st.write(f"**{h['source']}** ({date_display}) -- {h['title']}")


# --- Polymarket: a market-priced probability, presented as-is --------------
st.divider()
st.subheader("Iran/Gulf prediction market pricing (Polymarket)")

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

st.caption("Source: Polymarket Gamma API. A market-priced probability, not a fact.")
