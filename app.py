import json
import os
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
import branca.colormap as cm
from streamlit_folium import st_folium
from supabase import create_client
from openai import OpenAI

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
ma_avg_fb["city"] = "All MA places (avg)"

ma_avg_burden = (
    rent.groupby("year")
    .agg(rent_burdened_30plus=("rent_burdened_30plus", "sum"), total_renters=("total_renters", "sum"))
    .reset_index()
)
ma_avg_burden["burden_pct"] = ma_avg_burden["rent_burdened_30plus"] / ma_avg_burden["total_renters"] * 100
ma_avg_burden["city"] = "All MA places (avg)"

def add_benchmark_style(fig, name="All MA places (avg)"):
    """Make the benchmark trace a dashed gray line."""
    fig.for_each_trace(
        lambda t: t.update(line=dict(dash="longdash", color="gray", width=3))
        if t.name == name else ()
    )
    return fig

tab0, tab1, tab2, tab3, tab4 = st.tabs([
    "🗺️ Map",
    "📈 Growth",
    "🌍 Origin Countries",
    "🏠 Housing Burden",
    "🔍 Custom Query",
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
            "weight":      2.5     if is_gw else 0.5,
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
    selected_cities = st.multiselect(
        "Select cities to compare", all_cities, default=all_cities[:6], key="tab1_cities"
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
            title=f"% Change in Foreign-Born ({min_year}–{max_year})",
            labels={"pct_change": "% Change", "city": ""},
            color="pct_change", color_continuous_scale="RdYlGn",
        )
        fig.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig2 = px.bar(
            growth.sort_values("abs_change", ascending=True),
            y="city", x="abs_change", orientation="h",
            title=f"Absolute Change in Foreign-Born ({min_year}–{max_year})",
            labels={"abs_change": "Additional People", "city": ""},
            color="abs_change", color_continuous_scale="Blues",
        )
        fig2.update_layout(coloraxis_showscale=False)
        st.plotly_chart(fig2, use_container_width=True)

# ── Tab 2: Origin Countries ───────────────────────────────────────────────────
with tab2:
    try:
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
                x="estimate", y="country", orientation="h",
                title=f"Top 15 Origin Countries — {selected_city} ({year2})",
                labels={"estimate": "Foreign-Born Residents", "country": ""},
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig2 = px.pie(
                year_data, values="estimate", names="country",
                title=f"Share by Country — {selected_city} ({year2})",
                hole=0.35,
            )
            st.plotly_chart(fig2, use_container_width=True)
    except Exception as e:
        st.error(f"Origin Countries tab error: {e}")

# ── Tab 3: Housing Burden Correlation ────────────────────────────────────────
with tab3:
  try:
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
            name="Foreign-Born Residents", marker_color="#c0392b",
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
            name="All MA places (avg)", mode="lines",
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
  except Exception as e:
    st.error(f"Housing Burden tab error: {e}")

# ── Tab 4: Custom Query ───────────────────────────────────────────────────────
with tab4:
    st.header("Want to find something else?")

    CENSUS_VARIABLES = """
## POPULATION
B01003_001E: Total population

## RACE & ETHNICITY
B02001_002E: White alone
B02001_003E: Black or African American alone
B02001_004E: American Indian and Alaska Native alone
B02001_005E: Asian alone
B02001_006E: Native Hawaiian and Other Pacific Islander alone
B02001_007E: Some other race alone
B03002_003E: White alone, not Hispanic or Latino
B03002_012E: Hispanic or Latino (any race)
B03001_003E: Hispanic or Latino total

## NATIVITY & FOREIGN-BORN
B05002_001E: Total population (nativity)
B05002_002E: Native-born population
B05002_013E: Foreign-born population total
B05001_001E: Total population (citizenship)
B05001_005E: U.S. citizen by naturalization
B05001_006E: Not a U.S. citizen
B05002_014E: Foreign-born: naturalized citizen
B05002_021E: Foreign-born: not a citizen

## PLACE OF BIRTH (FOREIGN-BORN)
B05006_001E: Total foreign-born population (place of birth)
B05006_002E: Foreign-born from Europe
B05006_047E: Foreign-born from Asia
B05006_091E: Foreign-born from Africa
B05006_100E: Foreign-born from Oceania
B05006_101E: Foreign-born from Latin America
B05006_123E: Foreign-born from Northern America

## YEAR OF ENTRY
B05005_001E: Total foreign-born (year of entry)
B05005_002E: Entered 2010 or later
B05005_006E: Entered 2000 to 2009
B05005_009E: Entered before 2000

## GEOGRAPHIC MOBILITY (MIGRATION)
B07001_001E: Total population 1 year and over (mobility)
B07001_017E: Lived in same house 1 year ago (did not move)
B07001_033E: Moved within same county
B07001_049E: Moved from different county, same state
B07001_065E: Moved from different state
B07001_081E: Moved from abroad
B07003_004E: Male movers from different state
B07003_007E: Female movers from different state
B07013_001E: Total population in occupied housing units (mobility)
B07013_003E: Moved in same county — renters

## INCOME
B19013_001E: Median household income (all households)
B19013B_001E: Median household income — Black or African American households
B19013D_001E: Median household income — Asian households
B19013H_001E: Median household income — White non-Hispanic households
B19013I_001E: Median household income — Hispanic or Latino households
B19301_001E: Per capita income
B19083_001E: Gini index of income inequality
B19001_001E: Total households (household income distribution)
B19001_002E: Households with income less than $10,000
B19001_011E: Households with income $50,000 to $59,999
B19001_014E: Households with income $100,000 to $124,999
B19001_017E: Households with income $200,000 or more

## POVERTY
B17001_001E: Total population (poverty status)
B17001_002E: Population below poverty level
B17001_031E: Population at or above poverty level
C17002_001E: Total (ratio of income to poverty level)
C17002_002E: Under 0.50 (deep poverty)
C17002_003E: 0.50 to 0.99 (below poverty)
C17002_004E: 1.00 to 1.24 (near poverty)
C17002_008E: 2.00 and over (200%+ of poverty line)

## HOUSING & RENT BURDEN
B25070_001E: Total renter-occupied units (gross rent as % of income)
B25070_007E: Gross rent 30.0 to 34.9% of income (rent burdened)
B25070_008E: Gross rent 35.0 to 39.9% of income
B25070_009E: Gross rent 40.0 to 49.9% of income
B25070_010E: Gross rent 50% or more of income (severely rent burdened)
B25064_001E: Median gross rent (dollars)
B25003_001E: Total occupied housing units (tenure)
B25003_002E: Owner-occupied housing units
B25003_003E: Renter-occupied housing units

## EMPLOYMENT
B23025_001E: Total civilian population 16 years and over
B23025_002E: In labor force
B23025_004E: Employed (civilian labor force)
B23025_005E: Unemployed
B23025_007E: Not in labor force

## EDUCATION
B15003_001E: Total population 25 years and over (educational attainment)
B15003_017E: Population with high school diploma (or equivalent)
B15003_022E: Population with bachelor's degree
B15003_023E: Population with master's degree
B15003_025E: Population with doctorate degree
"""

    GEMINI_SYSTEM_PROMPT = f"""
You are a Census data assistant helping journalists explore Massachusetts data.
Given a plain English question, return ONLY a valid JSON object (no markdown, no explanation) with:

- "variables": list of ACS variable codes to fetch (from the list below)
- "year": integer year (use 2022 unless the user specifies)
- "geo": Census API geo string, one of:
    "county:*&in=state:25"  (all MA counties)
    "place:*&in=state:25"   (all MA cities/towns)
- "chart_type": one of "bar", "line", "scatter", "pie"
- "x_col": column name for x-axis (usually "NAME")
- "y_col": the primary variable code to plot
- "title": a descriptive chart title
- "x_label": x-axis label
- "y_label": y-axis label

Available variables:
{CENSUS_VARIABLES}

Example output:
{{
  "variables": ["B19013_001E"],
  "year": 2022,
  "geo": "county:*&in=state:25",
  "chart_type": "bar",
  "x_col": "NAME",
  "y_col": "B19013_001E",
  "title": "Median Household Income by County in MA (2022)",
  "x_label": "County",
  "y_label": "Median Household Income ($)"
}}

Only use variable codes from the list above. If the question is unrelated to Census data, return:
{{"error": "I can only answer questions about Census data for Massachusetts."}}
"""

    def fetch_census_data(variables, geo, year):
        base_url = f"https://api.census.gov/data/{year}/acs/acs5"
        get_cols = ",".join(variables) + ",NAME"
        # Split "county:*&in=state:25" into {"for": "county:*", "in": "state:25"}
        params = {"get": get_cols}
        for part in geo.split("&"):
            if part.startswith("in="):
                params["in"] = part[3:]
            else:
                params["for"] = part.replace("for=", "")
        census_api_key = st.secrets.get("CENSUS_API_KEY", None)
        if census_api_key:
            params["key"] = census_api_key
        r = requests.get(base_url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        df = pd.DataFrame(data[1:], columns=data[0])
        for v in variables:
            if v in df.columns:
                df[v] = pd.to_numeric(df[v], errors="coerce")
        # Clean up NAME column (e.g. "Suffolk County, Massachusetts" → "Suffolk County")
        if "NAME" in df.columns:
            df["NAME"] = df["NAME"].str.replace(", Massachusetts", "", regex=False)
        return df

    def ask_gemini(question):
        client = OpenAI(
            api_key=st.secrets["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
        )
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": GEMINI_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)

    question = st.text_input(
        "",
        placeholder="e.g. Which counties have the highest median income? Show me migration trends by county.",
    )
    submit = st.button("Search")

    if submit and question:
        with st.spinner("Thinking..."):
            try:
                query = ask_gemini(question)
            except Exception as e:
                st.error(f"Gemini error: {e}")
                query = None

        if query:
            if "error" in query:
                st.warning(query["error"])
            else:
                with st.spinner("Fetching Census data..."):
                    try:
                        df = fetch_census_data(query["variables"], query["geo"], query["year"])
                    except Exception as e:
                        st.error(f"Census API error: {e}")
                        df = None

                if df is not None and not df.empty:
                    x = query.get("x_col", "NAME")
                    y = query.get("y_col", query["variables"][0])
                    title = query.get("title", "Census Data")
                    x_label = query.get("x_label", x)
                    y_label = query.get("y_label", y)
                    chart_type = query.get("chart_type", "bar")

                    df_sorted = df.dropna(subset=[y]).sort_values(y, ascending=True)

                    if chart_type == "bar":
                        fig = px.bar(df_sorted, x=y, y=x, orientation="h",
                                     title=title, labels={y: y_label, x: x_label})
                    elif chart_type == "scatter":
                        fig = px.scatter(df_sorted, x=x, y=y,
                                         title=title, labels={y: y_label, x: x_label},
                                         hover_name=x if x == "NAME" else None)
                    elif chart_type == "pie":
                        fig = px.pie(df_sorted, values=y, names=x, title=title)
                    else:
                        fig = px.line(df_sorted, x=x, y=y,
                                      title=title, labels={y: y_label, x: x_label})

                    st.plotly_chart(fig, use_container_width=True)
                    st.download_button(
                        label="Download CSV",
                        data=df.to_csv(index=False),
                        file_name="census_data.csv",
                        mime="text/csv",
                    )
                elif df is not None:
                    st.warning("No data returned for that query.")
