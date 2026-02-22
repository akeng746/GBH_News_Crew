# Gateway Cities – Foreign-Born & Economic Trends Dashboard  
**CityHack – GBH Gateway Cities Challenge Submission**

---
## Inspiration

Developed for GBH News during the Civic Hacks 2026 Hackathon, this project facilitates deep-dive reporting on Massachusetts Gateway Cities: urban centers with populations between 35,000 and 250,000 where income and graduation rates fall below the state average. By visualizing American Community Survey (ACS) data, journalists can track how foreign-born population trends intersect with shifting economic and housing characteristics over time. This tool is designed to move beyond statewide statistics and pinpoint localized data that can inform reporting.

## 1. Project Overview

This project synthesizes **U.S. Census American Community Survey (ACS) 5-Year Estimates (2010–2024)** to analyze demographic and economic trends across:

- 26 Massachusetts Gateway Cities (MassINC definition)
- Comparison cities: Boston, Cambridge, Weymouth, Marlborough
- Massachusetts statewide totals (baseline)

The dashboard is built in **Streamlit** and designed for:

- Investigative journalists (GBH News)
- Civic data teams
- Policy analysts
- Public-interest reporting projects

The objective is to convert raw ACS tables into:

- Clear civic insights  
- Trend detection across time  
- Identification of outliers  
- Fact-checkable, source-documented findings  
- Visual artifacts ready for journalistic integration  

---

## 2. Research Focus

Primary emphasis: **Foreign-born population trends and economic conditions**

### Core Questions

1. Which Gateway Cities are experiencing the fastest growth in foreign-born population?
2. How do origin countries differ across cities, and how are those patterns changing?
3. Are changes in foreign-born population correlated with:
   - Median household income?
   - Poverty rate?
   - Housing burden?
   - Employment trends?

---

## 3. Data Sources

All data is sourced from the **U.S. Census Bureau – American Community Survey (ACS) 5-Year Estimates**.

Primary source:  
https://www.census.gov/programs-surveys/acs/data.html

Reference tools used:
- https://data.census.gov
- https://censusreporter.org
- https://buspark.io/documentation/project-guides/census_tutorial

---

## 4. ACS Tables Used

### Demographics & Immigration
- **B05006** – Place of Birth (Foreign-Born by Country)
- **B05015** – Year of Entry
- **B01003** – Total Population

### Income & Economic Indicators
- **S1901** – Income
- **S1701** – Poverty Status
- **B19083** – Gini Index
- **B23025** – Employment Status
- **S1501** – Educational Attainment

### Housing
- **B25002** – Occupancy Rate
- **B25003** – Owner vs Renter
- **B25034** – Year Structure Built
- **B25077** – Median Home Value
- **B25070** – Rent as % of Income

### Transportation
- **B08301** – Mode of Transportation to Work
- **B08126** – Travel Time to Work

---

## 5. Time Coverage

- ACS 5-Year Estimates
- 2010–2024 (where available)
- Long-format panel dataset

---

## 6. Data Processing Pipeline

### 6.1 Extraction
- Downloaded ACS CSV files by year and table
- Verified consistent GEOID structure
- Extracted estimate + margin of error (MOE) fields

### 6.2 Cleaning
- Removed embedded duplicate headers
- Dropped trailing unnamed columns
- Standardized column names
- Preserved numeric precision (no unintended coercion)

### 6.3 Restructuring
All tables converted to **long format panel structure**:

**Core schema:**
- `place_fips`
- `geo_id`
- `city_name`
- `acs_end_year`
- `acs_5yr_period`
- `metric`
- `estimate`
- `moe`

Foreign-born by country includes:
- `country_label`

Year of entry includes:
- `entry_cohort`

### 6.4 Integration
All cleaned datasets uploaded into **Supabase (PostgreSQL)**.

Design principles:
- Normalized tables
- Consistent `place_fips` primary key
- Composite uniqueness enforced where appropriate
- Duplicate detection before insert

---

## 7. Database Design

### Primary Key Strategy

Composite keys used for longitudinal uniqueness:

Example:

(place_fips, acs_end_year, metric)

For country-level data:

(place_fips, acs_end_year, country_label)

This prevents:
- Duplicate annual inserts
- Overwriting longitudinal trends
- Inconsistent panel construction

---

## 8. Streamlit Frontend

The dashboard is designed specifically for investigative workflows.

### Core Features

- City selector (Gateway Cities + comparison cities)
- Time-series visualizations (2010–2024)
- Foreign-born % of total population
- Country-of-origin ranking tables
- Growth-rate detection
- Outlier identification
- Cross-metric correlation views
- Downloadable CSV exports

### Journalist-Focused Functionality

- Clearly labeled data sources
- Margin-of-error transparency
- Methodology notes embedded
- Shareable chart exports
- Structured narrative prompts

---

## 9. Outlier & Trend Identification

The system flags:

- Cities with highest % change in foreign-born population
- Cities with fastest income growth vs immigrant growth
- Significant divergence from statewide averages
- Top origin-country concentration shifts

Outliers are defined via:
- Relative % growth
- Z-score deviation from statewide mean
- Multi-year slope analysis

---

## 10. Ethical & Responsible Data Use

### 10.1 Transparency
- All tables documented
- All sources publicly verifiable
- MOE preserved and available
- No suppression of inconvenient findings

### 10.2 Fairness
- Avoids causal claims without statistical testing
- Avoids stigmatizing language
- Separates correlation from interpretation

### 10.3 Privacy
- All data is aggregated public ACS data
- No personally identifiable information
- No tract-level microdata used in public interface

### 10.4 Limitations
- ACS 5-year estimates smooth volatility
- Margins of error can be large for small cities
- Changes may reflect sampling variation
- Immigration patterns influenced by external policy shifts

---

## 11. Gateway Cities in Scope

The 26 Gateway Cities (MassINC definition) are included.  
Boston and Cambridge are included for structural comparison.

Statewide Massachusetts totals are used as a baseline reference.

---

## 12. Reproducibility

### Requirements
- Python 3.9+
- pandas
- psycopg2
- SQLAlchemy
- Streamlit

### Run Locally

pip install -r requirements.txt
streamlit run app.py

---

## 13. File Structure

/data_raw
/data_clean
/scripts
combine_b05006.py
combine_b05015.py
combine_s1901.py
...
/database
/app.py
/README.md


---

## 14. Intended Impact

This project aims to:

- Support accountability journalism
- Identify overlooked demographic shifts
- Surface structural economic inequality
- Provide narrative-ready civic data
- Improve transparency around immigration trends in Massachusetts

---

## 15. Prepared for Journalistic Integration

Outputs are designed to:

- Be fact-checkable
- Include documented sources
- Allow rapid query testing
- Export directly into newsroom workflows
- Support investigative framing

---

## 16. Next Steps

- Census tract-level origin mapping
- DP03 economic characteristic cross-analysis
- Automated anomaly detection alerts
- Downloadable story briefs per city
- GBH integration collaboration

---

## 17. Contact

Project Team – CityHack 2026  
Gateway Cities Challenge Submission



