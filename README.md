# San Juan Home Sales

Residential sales data for the San Juan metropolitan area of Puerto Rico (San Juan, Guaynabo, Carolina, Bayamón, Cataño, Trujillo Alto and Toa Baja), cleaned and organized for two projects:

1. **A BI project:** a dashboard on prices, volume, deal types and appraisal gaps by municipality and neighborhood.
2. **A data science project:** a model that predicts sale price per square foot from property features.

> **Status:** work in progress. The data pipeline (parsing, cleaning, database) is built. The dashboard and the model are next.

## Data source and privacy

The raw data is about two years of closed-sale records copied by hand from Tasamax pages into `.txt` files. **The raw pages and everything derived from them at the record level are not in this repository.** The pages contain buyer, seller and appraiser names and contact details, and the cleaned data contains street addresses.

- `.gitignore` excludes `*.txt`, `*.csv`, `*.db` and `data/`.
- The parser never writes buyer, seller or appraiser fields, or the free-text description, to its output.
- Only code, queries and (later) aggregated results are published.
- Check the Tasamax terms of use before publishing anything derived from it. <!-- TODO: confirm -->

## How it works

```
data/raw/*.txt  ->  parse_real_estate.py  ->  batch_parse_real_estate.py  ->  build_db.py  ->  SQLite + CSV exports
 (copied pages)       (one page -> rows)      (all pages, dedup, summary)     (tables, views)     (dashboard / model)
```

| Step | Script | What it does |
|---|---|---|
| 1 | `scr/parse_real_estate.py` | Turns one page of copied text into one row per sale: fields, dates, prices, amenities, parking, derived values and quality flags. |
| 2 | `scr/batch_parse_real_estate.py` | Runs the parser on every `.txt` page, removes duplicates, writes `properties.csv`, `duplicate_records.csv` and `parse_errors.csv`, and prints a summary. |
| 3 | `scr/build_db.py` | Loads `properties.csv` into SQLite, builds the analysis views and exports CSVs for BI tools. |
| 4 | `sql/dashboard_queries.sql` | Fourteen queries, one per dashboard page. |

## Repository layout

```
san-juan-home-sales/
├── scr/
│   ├── parse_real_estate.py
│   ├── batch_parse_real_estate.py
│   └── build_db.py
├── sql/
│   └── dashboard_queries.sql
├── data/                  # not in git
│   ├── raw/               # copied Tasamax pages (.txt)
│   └── processed/         # properties.csv, san_juan_sales.db, bi_export/
├── .gitignore
└── README.md
```

## Requirements

Python 3.8 or newer. Everything uses the standard library, so there is nothing to install. The database is SQLite, which ships with Python.

## Usage

Run from the repository root.

```
# 1. Parse every page in data/raw and combine the results
python scr/batch_parse_real_estate.py --input-dir data/raw --output data/processed/properties.csv

# 2. Build the database and the BI exports
python scr/build_db.py --csv data/processed/properties.csv --db data/processed/san_juan_sales.db
```

To test the parser on a single page: `python scr/parse_real_estate.py data/raw/page1.txt -o test.csv`.

**Manual corrections.** If a value is wrong at the source (for example a living area with a lost digit), put the corrected value in `data/overrides.csv` with the columns `property_id,field,value,note` and rerun the batch script. Numeric and price fields are supported, for example `gla_sqft`, `bedrooms`, `appraisal_value`, `sales_price` and `contract_price`. Overridden records get a `manual_override_<field>` flag.

Optional: add `data/neighborhood_map.csv` with columns `raw,clean` to merge spelling variants of a neighborhood. `build_db.py` applies it automatically.

## Outputs

**Tables:** `municipality`, `neighborhood`, `sales`.

**Views:**

| View | Contents |
|---|---|
| `sales_full` | `sales` with municipality and neighborhood names. |
| `analysis_sales` | The clean set used for price analysis (see below). |
| `market_monthly` | Sales count and median price per square foot by municipality and month. |

`data/processed/bi_export/` holds `analysis_sales.csv` and `market_monthly.csv` for Power BI or Tableau, which do not read SQLite directly.

## Key fields

| Field | Meaning |
|---|---|
| `sales_price` | Settled sale price shown in the list header. Present on every record, including registry-only ones. |
| `appraisal_value` | Appraised value shown in the list header. Blank on registry-only records. |
| `contract_price` | The original price in the appraisal's sales contract. Missing on registry-only records. It can be higher than the settled price: when the appraisal comes in low, deals are often renegotiated down. |
| `settled_sale_date` | Date the sale settled. |
| `price_per_sqft` | `sales_price` divided by living area (`gla_sqft`). |
| `net_price` | `sales_price` minus the seller or developer incentive. The government incentive is buyer assistance and is not subtracted. |
| `sales_to_appraisal_ratio` | `sales_price` divided by `appraisal_value`. Appraisals can carry separate as-is and as-repaired values, so a low ratio is common for homes that need repairs. |
| `sold_at_appraisal` | 1 when the settled price equals the appraised value exactly, a sign the price was renegotiated to the appraisal. |
| `price_change_from_contract_pct` | Percent change from contract price to settled price (negative means the price was cut). |
| `sales_type`, `arms_length` | Arms-length, non-arms-length, estate or REO sale. |
| `covered_parking_cars` | Garage plus carport spaces. Driveway spaces are separate. |
| `dedup_key` | Catastro plus contract date, with a fallback for registry-only records. Used to catch the same sale listed under two IDs. |
| `quality_flags` | Semicolon-separated list of problems found on the record. |

## The analysis set

`analysis_sales` keeps a sale only if it is an arms-length sale with a price and a living area, and it has none of these flags: `price_per_sqft_outlier`, `very_low_price`, `gla_suspect`, `registry_derived_data`. Contract-price and contract-date problems are not excluded, because the analysis uses the settled sales price and settled date. Edit `EXCLUDE_FLAGS` at the top of `build_db.py` to change the rule.

## Data quality flags

| Flag | Meaning |
|---|---|
| `registry_source`, `registry_derived_data` | Record comes from the property registry, or its description says the data came from it. Fewer fields and no sales type. |
| `no_sales_type`, `non_arms_length` | Sales type missing, or the sale is estate, REO or non-arms-length. |
| `related_party`, `buyer_is_tenant` | Sale between relatives or acquaintances, or the buyer is the tenant. |
| `no_gla`, `no_contract_price`, `no_condition_code` | Missing living area, contract price or condition code. |
| `contract_gap_unexplained` | Contract and settled prices differ by 10% or more and the settled price is not the appraised value. |
| `contract_price_suspect` | Contract price differs from the settled price by more than a factor of two, almost always a dropped or extra zero. The contract price is blanked and kept in `contract_price_raw`. |
| `gla_suspect`, `gla_very_large` | Living area under 300 sq ft or under 150 sq ft per bedroom (usually a lost digit), or over 6,000 sq ft. Suspect values are excluded from the analysis set. |
| `manual_override_<field>` | The value was corrected from `data/overrides.csv`. |
| `sales_price_far_from_appraisal` | Sales price more than 25% away from appraised value. |
| `appraisal_value_suspect` | Sales price is more than 40% above the appraisal value, usually a bad value in the list header (for example a repair total). The value is blanked and kept in `appraisal_value_raw`. |
| `contract_after_settled_date`, `contract_over_1yr_before_settled`, `bad_<field>` | Date problems. |
| `bad_latitude`, `bad_longitude` | Coordinates outside Puerto Rico; they are blanked. |
| `tax_catastro_mismatch` | Tax code does not start with the catastro number. |
| `price_per_sqft_outlier`, `very_low_price` | Implausible price. |
| `dom_unrecognized`, `garage_unrecognized`, `garage_count_assumed` | Days-on-market or garage text the parser did not recognize, or a parking count it assumed. |
| `encoding_loss` | Name contains `?` from lost accented characters. |

## Known limitations

- Pages were copied by hand, so new text variants appear over time. Unrecognized values are flagged, not guessed.
- Registry-only records have no living area, contract price or sales type, so they cannot be used for pricing analysis.
- About 20% of records have a contract price that differs from the settled price. The settled price is the one used, because the contract price is the original agreement, often renegotiated after the appraisal.
- Neighborhood names come from the source and are only title-cased. Variants may need merging with `neighborhood_map.csv`.
- Sample sizes for small neighborhoods are small. Dashboards show sale counts next to every price.

## Roadmap

- [ ] BI dashboard (Power BI or Tableau) <!-- TODO: add link or screenshots -->
- [ ] Modelling notebook: neighborhood-median baseline, ridge regression and gradient boosting, validated by time
- [ ] Merge neighborhood name variants
- [ ] Geocode records that have no coordinates

## License

<!-- TODO: choose a license for the code -->