import json
import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
import branca.colormap as cm
from streamlit_folium import st_folium
from supabase import create_client

st.set_page_config(
    page_title="Gateway Cities: Immigration Trends",
    layout="wide",
)

# ── Supabase ──────────────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

def fetch_all(table, select="*"):
    """Fetch every row, paging past Supabase's 1000-row default limit."""
    client = get_supabase()
    rows, offset, page_size = [], 0, 1000
    while True:
        r = (
            client.table(table)
            .select(select)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows.extend(r.data)
        if len(r.data) < page_size:
            break
        offset += page_size
    return pd.DataFrame(rows)

@st.cache_data(ttl=3600)
def load_data():
    gateway   = fetch_all("gateway_cities")
    fb_total  = fetch_all("foreign_born_total")
    pop       = fetch_all("total_population")
    countries = fetch_all("foreign_born_by_country")
    rent      = fetch_all("rent_burden")

    data_map = {
        "gateway_cities": gateway,
        "foreign_born_total": fb_total,
        "total_population": pop,
        "foreign_born_by_country": countries,
        "rent_burden": rent,
    }

    required_cols = {
        "gateway_cities": ["place_fips", "place_name"],
        "foreign_born_total": ["year", "foreign_born_total", "place_fips", "place_name"],
        "total_population": ["year", "total_pop", "place_fips"],
        "foreign_born_by_country": ["year", "estimate", "place_fips", "country_label"],
        "rent_burden": ["year", "total_renters", "rent_burdened_30plus", "place_fips"],
    }

    # Validate required columns and coerce numeric columns where appropriate
    for table_name, cols in required_cols.items():
        df = data_map.get(table_name)
        if df is None:
            raise Exception(f"Supabase table '{table_name}' returned no data (None).")
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise Exception(
                f"Supabase table '{table_name}' is missing columns: {missing}. "
                f"Found columns: {list(df.columns)}. Ensure the table schema matches expected column names."
            )

    # Coerce numeric columns (only those we expect to be numeric)
    numeric_cols_map = {
        "foreign_born_total": ["year", "foreign_born_total"],
        "total_population": ["year", "total_pop"],
        "foreign_born_by_country": ["year", "estimate"],
        "rent_burden": ["year", "total_renters", "rent_burdened_30plus"],
    }
    for table_name, cols in numeric_cols_map.items():
        df = data_map[table_name]
        for c in cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return gateway, fb_total, pop, countries, rent

def city_label(place_name):
    return place_name.split(",")[0].replace(" city", "").replace(" City", "").strip()

@st.cache_data
def load_geojson():
    path = os.path.join(os.path.dirname(__file__), "Massachusetts_Municipalities_(Feature_Layer).geojson")
    with open(path) as f:
        return json.load(f)

def normalize_for_geo(name):
    """'Barnstable Town' → 'barnstable', 'Fall River' → 'fall river'"""
    return name.lower().replace(" town", "").strip()

# ── Load ──────────────────────────────────────────────────────────────────────

st.title("Gateway Cities: Immigration Trends")
st.caption("ACS 5-Year Estimates · Massachusetts · 2010–2024")

try:
    with st.spinner("Loading data from Supabase..."):
        gateway, fb_total, pop, countries, rent = load_data()
except Exception as e:
    st.error(f"Could not load data: {e}")
    st.info(
        "Make sure SUPABASE_URL and SUPABASE_KEY are set in .streamlit/secrets.toml "
        "and that the tables have been uploaded."
    )
    st.stop()

gateway_fips = set(gateway["place_fips"])
gateway["city"] = gateway["place_name"].apply(city_label)
fips_to_city = dict(zip(gateway["place_fips"], gateway["city"]))

# ── MA benchmark: population-weighted average across all available places ─────
_ma_fb = fb_total.merge(pop[["year", "place_fips", "total_pop"]], on=["year", "place_fips"])
ma_avg_fb = (
    _ma_fb.groupby("year")
    .agg(foreign_born_total=("foreign_born_total", "sum"), total_pop=("total_pop", "sum"))
    .reset_index()
)
ma_avg_fb["fb_pct"] = ma_avg_fb["foreign_born_total"] / ma_avg_fb["total_pop"] * 100
ma_avg_fb["city"] = "Massachusetts (avg)"

ma_avg_burden = (
    rent.groupby("year")
    .agg(rent_burdened_30plus=("rent_burdened_30plus", "sum"), total_renters=("total_renters", "sum"))
    .reset_index()
)
ma_avg_burden["burden_pct"] = ma_avg_burden["rent_burdened_30plus"] / ma_avg_burden["total_renters"] * 100
ma_avg_burden["city"] = "Massachusetts (avg)"

def add_benchmark_style(fig, name="Massachusetts (avg)"):
    """Make the benchmark trace a dashed gray line."""
    fig.for_each_trace(
        lambda t: t.update(line=dict(dash="longdash", color="gray", width=3))
        if t.name == name else ()
    )
    return fig

st.divider()

# Style tabs for better UX: larger, bolder, more spaced
st.markdown("""
<style>
    /* Increase tab button size and spacing */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2rem;
    }
    
    /* Make tab text larger and bolder */
    .stTabs [data-baseweb="tab"] {
        font-size: 16px;
        font-weight: 600;
        padding: 12px 24px;
    }
    
    /* Make active tab stand out more */
    .stTabs [aria-selected="true"] {
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

tab0, tab1, tab2, tab3 = st.tabs([
    "Explore the Map",
    " Population Growth Trends",
    " Origin Countries",
    " Housing & Economics",
])

# ── Tab 0: Map ────────────────────────────────────────────────────────────────
with tab0:
    st.header("Foreign-Born Population across Massachusetts")

    geojson_data = load_geojson()

    # Most recent year fb_pct for all places
    latest_year = int(fb_total["year"].max())
    fb_latest = (
        fb_total[fb_total["year"] == latest_year]
        .merge(pop[pop["year"] == latest_year][["place_fips", "total_pop"]], on="place_fips")
    ).copy()
    fb_latest["fb_pct"] = fb_latest["foreign_born_total"] / fb_latest["total_pop"] * 100
    fb_latest["norm_name"] = fb_latest["place_name"].apply(lambda n: normalize_for_geo(city_label(n)))

    name_to_fb    = dict(zip(fb_latest["norm_name"], fb_latest["fb_pct"]))
    name_to_count = dict(zip(fb_latest["norm_name"], fb_latest["foreign_born_total"].astype(int)))
    gateway_norm  = {normalize_for_geo(city_label(n)) for n in gateway["place_name"]}

    # Annotate GeoJSON features with data (deep-copy to avoid mutating cache)
    import copy
    annotated = copy.deepcopy(geojson_data)
    for feature in annotated["features"]:
        town = feature["properties"]["TOWN"]
        norm = town.lower()
        fb    = name_to_fb.get(norm)
        count = name_to_count.get(norm)
        is_gw = norm in gateway_norm
        feature["properties"]["fb_pct_str"]  = f"{fb:.1f}%" if fb is not None else "No data"
        feature["properties"]["fb_count_str"] = f"{count:,}" if count is not None else "No data"
        feature["properties"]["gateway_str"]  = "★ Gateway City" if is_gw else ""
        feature["properties"]["_fb"]  = fb if fb is not None else -1
        feature["properties"]["_is_gw"] = is_gw

    colormap = cm.LinearColormap(
        ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#084594"],
        vmin=0, vmax=40,
        caption=f"Foreign-Born % of Population ({latest_year})",
    )

    def style_fn(feature):
        fb   = feature["properties"]["_fb"]
        is_gw = feature["properties"]["_is_gw"]
        return {
            "fillColor":   colormap(max(fb, 0)) if fb >= 0 else "#cccccc",
            "fillOpacity": 0.75 if fb >= 0 else 0.3,
            "color":       "#cc0000" if is_gw else "#555555",
            "weight":      1.5     if is_gw else 0.5,
        }

    m = folium.Map(location=[42.2352, -71.0275], zoom_start=8, tiles="CartoDB positron")
    folium.GeoJson(
        annotated,
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=["TOWN", "gateway_str", "fb_pct_str", "fb_count_str"],
            aliases=["Town:", "", "Foreign-born:", "People:"],
            style="font-size: 13px; font-family: sans-serif;",
            localize=True,
        ),
    ).add_to(m)
    colormap.add_to(m)

    st.caption(
        "Gateway Cities outlined in red. Gray = no ACS place-level data (rural/unincorporated areas). "
        f"Data: ACS 5-Year {latest_year}."
    )
    st_folium(m, width="100%", height=600, returned_objects=[])

# ── Tab 1: Growth ─────────────────────────────────────────────────────────────
with tab1:
    st.header("Which Gateway Cities have the fastest growth in foreign-born population?")

    fb_gw  = fb_total[fb_total["place_fips"].isin(gateway_fips)].copy()
    pop_gw = pop[pop["place_fips"].isin(gateway_fips)].copy()

    merged = fb_gw.merge(pop_gw[["year", "place_fips", "total_pop"]], on=["year", "place_fips"])
    merged["fb_pct"] = merged["foreign_born_total"] / merged["total_pop"] * 100
    merged["city"]   = merged["place_fips"].map(fips_to_city)

    min_year = int(merged["year"].min())
    max_year = int(merged["year"].max())

    base = (
        merged[merged["year"] == min_year][["place_fips", "city", "foreign_born_total", "fb_pct"]]
        .rename(columns={"foreign_born_total": "fb_base", "fb_pct": "pct_base"})
    )
    latest = (
        merged[merged["year"] == max_year][["place_fips", "foreign_born_total", "fb_pct"]]
        .rename(columns={"foreign_born_total": "fb_latest", "fb_pct": "pct_latest"})
    )
    growth = base.merge(latest, on="place_fips").dropna()
    growth["pct_change"] = (growth["fb_latest"] - growth["fb_base"]) / growth["fb_base"] * 100
    growth["abs_change"] = growth["fb_latest"] - growth["fb_base"]

    st.subheader("Trends over time")
    all_cities = sorted(growth["city"].dropna().tolist())
    top_5_cities = growth.nlargest(5, "abs_change")["city"].tolist()
    selected_cities = st.multiselect(
        "Select cities to compare", all_cities, default=top_5_cities, key="tab1_cities"
    )
    if selected_cities:
        sel_fips = growth[growth["city"].isin(selected_cities)]["place_fips"].tolist()
        trend = merged[merged["place_fips"].isin(sel_fips)]
        trend_with_avg = pd.concat([trend, ma_avg_fb[["year", "fb_pct", "city"]]], ignore_index=True)
        fig3 = px.line(
            trend_with_avg, x="year", y="fb_pct", color="city",
            title="Foreign-Born as % of Total Population Over Time",
            labels={"fb_pct": "% Foreign-Born", "year": "Year", "city": "City"},
        )
        add_benchmark_style(fig3)
        st.plotly_chart(fig3, use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(
            growth.sort_values("pct_change", ascending=True),
            y="city", x="pct_change", orientation="h",
            title=f"% Change in Foreign-Born Population ({min_year}–{max_year})",
            labels={"pct_change": "% Change", "city": ""},
            color="pct_change", color_continuous_scale="Viridis",
        )
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.bar(
            growth.sort_values("abs_change", ascending=True),
            y="city", x="abs_change", orientation="h",
            title=f"Absolute Change in Foreign-Born Population ({min_year}–{max_year})",
            labels={"abs_change": "Additional People", "city": ""},
            color="abs_change", color_continuous_scale="Blues",
        )
        fig2.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

# ── Tab 2: Origin Countries ───────────────────────────────────────────────────
with tab2:
    st.header("How do origin countries differ across cities, and how is that changing?")

    cntry_gw = countries[countries["place_fips"].isin(gateway_fips)].copy()
    cntry_gw["city"] = cntry_gw["place_fips"].map(fips_to_city)

    city_options = sorted(gateway["city"].dropna().unique().tolist())
    years2 = sorted(cntry_gw["year"].dropna().unique().astype(int).tolist())

    sel_col, yr_col = st.columns([2, 1])
    with sel_col:
        selected_city = st.selectbox("Select a city", city_options)
    with yr_col:
        year2 = st.selectbox("Select year", years2, index=len(years2) - 1, key="tab2_year")

    city_fips_list = gateway[gateway["city"] == selected_city]["place_fips"].tolist()
    city_data = cntry_gw[cntry_gw["place_fips"].isin(city_fips_list)]
    year_data = city_data[city_data["year"] == year2].dropna(subset=["estimate"]).nlargest(15, "estimate")

    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(
            year_data.sort_values("estimate"),
            x="estimate", y="country_label", orientation="h",
            title=f"Top 15 Origin Countries — {selected_city} ({year2})",
            labels={"estimate": "Foreign-Born Residents", "country_label": ""},
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.pie(
            year_data, values="estimate", names="country_label",
            title=f"Share by Country — {selected_city} ({year2})",
            hole=0.35,
        )
        st.plotly_chart(fig2, use_container_width=True)

# ── Tab 3: Housing Burden Correlation ────────────────────────────────────────
with tab3:
    st.header("Are changes in foreign-born population correlated with housing burden?")

    fb_gw2  = fb_total[fb_total["place_fips"].isin(gateway_fips)].copy()
    pop_gw2 = pop[pop["place_fips"].isin(gateway_fips)].copy()
    rent_gw = rent[rent["place_fips"].isin(gateway_fips)].copy()

    fb_m = fb_gw2.merge(pop_gw2[["year", "place_fips", "total_pop"]], on=["year", "place_fips"])
    fb_m["fb_pct"] = fb_m["foreign_born_total"] / fb_m["total_pop"] * 100
    rent_gw["burden_pct"] = rent_gw["rent_burdened_30plus"] / rent_gw["total_renters"] * 100

    combined = fb_m.merge(
        rent_gw[["year", "place_fips", "burden_pct"]], on=["year", "place_fips"]
    ).dropna(subset=["fb_pct", "burden_pct"])
    combined["city"] = combined["place_fips"].map(fips_to_city)

    city3_options = sorted(combined["city"].dropna().unique().tolist())
    sel_city3 = st.selectbox("Select a city", city3_options, key="burden_city")

    city3_data = combined[combined["city"] == sel_city3].sort_values("year")

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=city3_data["year"], y=city3_data["foreign_born_total"],
            name="Foreign-Born Residents", marker_color="#0173B2",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=city3_data["year"], y=city3_data["burden_pct"],
            name="Rent Burden %", mode="lines+markers",
            line=dict(color="black", width=2),
        ),
        secondary_y=True,
    )
    fig.add_trace(
        go.Scatter(
            x=ma_avg_burden["year"], y=ma_avg_burden["burden_pct"],
            name="Massachusetts (avg)", mode="lines",
            line=dict(dash="longdash", color="gray", width=3),
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title=f"Foreign-Born Population & Rent Burden — {sel_city3}",
        xaxis_title="Year",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Foreign-Born Residents", secondary_y=False)
    fig.update_yaxes(title_text="Rent Burden %", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Rent burden = share of renter households spending 30%+ of income on rent (ACS B25070).")
