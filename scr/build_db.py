"""Load the parsed properties.csv into a SQLite database for the BI and data science projects.

Run from project root (after batch_parse_real_estate.py):
    python scr/build_db.py --csv data/processed/properties.csv --db data/processed/san_juan_sales.db

Creates:
  municipality, neighborhood, sales      (tables)
  sales_full                             (view: sales + municipality/neighborhood names)
  analysis_sales                         (view: clean arms-length sales used for pricing analysis)
  market_monthly                         (view: monthly KPIs by municipality, with medians)
Also writes analysis_sales.csv and market_monthly.csv to <db folder>/bi_export/ for Power BI / Tableau.

Optional: data/neighborhood_map.csv with columns raw,clean (and optionally municipality) to merge spelling variants
of a neighborhood. scr/suggest_neighborhood_map.py writes a first draft to review.
The database contains street addresses; keep *.db and data/ out of git (see .gitignore).
"""
import argparse
import csv
import re
import sqlite3
from pathlib import Path

# A sale is excluded from pricing analysis when it carries any of these flags (see parser quality_flags).
# Contract-price and contract-date problems are not excluded: the analysis uses the settled sales price and date.
EXCLUDE_FLAGS = ['price_per_sqft_outlier', 'very_low_price', 'gla_suspect', 'registry_derived_data']
FORCE_TEXT = {'property_id', 'tax_code', 'catastro', 'flood_map', 'dedup_key', 'zoning', 'unit', 'street'}


def clean_name(name, muni, mapping):
    name = ' '.join((name or '').split())
    for key in ((muni, name), ('', name)):       # a municipality-specific rule wins over a general one
        if key in mapping:
            return mapping[key]
    return name.title() if name else 'Unknown'


def infer_types(rows, columns):
    types = {}
    for col in columns:
        vals = [r[col] for r in rows if r[col] != '']
        ok = col not in FORCE_TEXT and bool(vals)
        for v in vals:
            try:
                float(v)
            except ValueError:
                ok = False
                break
        types[col] = 'REAL' if ok else 'TEXT'
    return types


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', type=Path, default=Path('data/processed/properties.csv'))
    ap.add_argument('--db', type=Path, default=Path('data/processed/san_juan_sales.db'))
    ap.add_argument('--neighborhood-map', type=Path, default=Path('data/neighborhood_map.csv'))
    args = ap.parse_args()

    with args.csv.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        rows = list(reader)
    mapping = {}
    if args.neighborhood_map.exists():
        with args.neighborhood_map.open(encoding='utf-8-sig', newline='') as f:
            mapping = {((r.get('municipality') or '').strip(), r['raw'].strip()): r['clean'].strip()
                       for r in csv.DictReader(f)}

    types = infer_types(rows, columns)
    sale_cols = [c for c in columns if c not in ('municipality', 'neighborhood')]

    args.db.parent.mkdir(parents=True, exist_ok=True)
    args.db.unlink(missing_ok=True)
    con = sqlite3.connect(args.db)
    cur = con.cursor()
    cur.executescript('''
        CREATE TABLE municipality (municipality_id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE neighborhood (neighborhood_id INTEGER PRIMARY KEY, municipality_id INTEGER REFERENCES municipality,
                                   name_raw TEXT, name_clean TEXT, UNIQUE (municipality_id, name_raw));
    ''')
    col_defs = ', '.join(f'"{c}" {"TEXT PRIMARY KEY" if c == "property_id" else types[c]}' for c in sale_cols)
    cur.execute(f'CREATE TABLE sales ({col_defs}, municipality_id INTEGER REFERENCES municipality, '
                f'neighborhood_id INTEGER REFERENCES neighborhood, settled_year INTEGER, settled_month TEXT, '
                f'settled_quarter TEXT)')

    muni_ids, hood_ids = {}, {}
    for r in rows:
        muni = ' '.join(r['municipality'].split()).title() or 'Unknown'
        if muni not in muni_ids:
            cur.execute('INSERT INTO municipality (name) VALUES (?)', (muni,))
            muni_ids[muni] = cur.lastrowid
        raw = ' '.join(r['neighborhood'].split())
        key = (muni_ids[muni], raw)
        if key not in hood_ids:
            cur.execute('INSERT INTO neighborhood (municipality_id, name_raw, name_clean) VALUES (?,?,?)',
                        (muni_ids[muni], raw, clean_name(raw, muni, mapping)))
            hood_ids[key] = cur.lastrowid
        d = r['settled_sale_date']
        year = int(d[:4]) if re.match(r'\d{4}-\d{2}-\d{2}$', d) else None
        month = d[:7] if year else None
        quarter = f'{d[:4]}-Q{(int(d[5:7]) - 1) // 3 + 1}' if year else None
        # Empty text becomes NULL, except quality_flags: '' means "no problems found" and must stay a string.
        values = [(r[c] if c == 'quality_flags' else None if r[c] == '' else float(r[c]) if types[c] == 'REAL' else r[c])
                  for c in sale_cols]
        cur.execute(f'INSERT INTO sales VALUES ({",".join("?" * (len(sale_cols) + 5))})',
                    values + [muni_ids[muni], hood_ids[key], year, month, quarter])

    excl = ' AND '.join(f"COALESCE(quality_flags, '') NOT LIKE '%{f}%'" for f in EXCLUDE_FLAGS)
    cur.executescript(f'''
        CREATE VIEW sales_full AS
          SELECT s.*, m.name AS municipality, n.name_clean AS neighborhood
          FROM sales s JOIN municipality m USING (municipality_id) JOIN neighborhood n USING (neighborhood_id);

        CREATE VIEW analysis_sales AS
          SELECT * FROM sales_full
          WHERE arms_length = 1 AND sales_price IS NOT NULL AND gla_sqft > 0 AND {excl};

        CREATE VIEW market_monthly AS
          WITH r AS (
            SELECT municipality, settled_month, price_per_sqft AS p, sales_price,
                   ROW_NUMBER() OVER (PARTITION BY municipality, settled_month ORDER BY price_per_sqft) AS rn,
                   COUNT(*) OVER (PARTITION BY municipality, settled_month) AS n
            FROM analysis_sales WHERE settled_month IS NOT NULL)
          SELECT municipality, settled_month, n AS sales_count,
                 ROUND(AVG(p), 2) AS median_price_per_sqft, ROUND(AVG(sales_price), 0) AS mean_price_of_middle_sales
          FROM r WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
          GROUP BY municipality, settled_month;
    ''')
    con.commit()

    export = args.db.parent / 'bi_export'
    export.mkdir(exist_ok=True)
    for view in ('analysis_sales', 'market_monthly'):
        c = con.execute(f'SELECT * FROM {view}')
        with (export / f'{view}.csv').open('w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in c.description])
            w.writerows(c)

    total = con.execute('SELECT COUNT(*) FROM sales').fetchone()[0]
    used = con.execute('SELECT COUNT(*) FROM analysis_sales').fetchone()[0]
    print(f'Loaded {total} sales into {args.db}')
    print(f'analysis_sales (clean, arms-length, priced, with living area): {used} rows ({used / total:.0%})')
    print(f'CSV exports for BI tools: {export}')


if __name__ == '__main__':
    main()
