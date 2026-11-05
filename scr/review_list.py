"""List the records most worth checking by hand, grouped by problem type.

Run from the repo root:
    python scr/review_list.py [--db data/processed/san_juan_sales.db] [--limit 25]

Prints a compact list and writes data/processed/review_list.csv (ignored by git).
Each row has source_file and source_line, so you can open the raw page at the right record.
Contains property IDs, municipality and prices only: no buyer, seller or appraiser data.
"""
import argparse
import csv
import sqlite3
from pathlib import Path

COLS = ("property_id, municipality, neighborhood, settled_sale_date, sales_price, appraisal_value, bedrooms, "
        "contract_price, gla_sqft, ROUND(price_per_sqft, 0) AS price_per_sqft, sales_type, "
        "source_file, CAST(source_line AS INTEGER) AS source_line")

GAP = "(contract_price - sales_price) / sales_price"
CHECKS = [
    # (reason, source view, where, order by)
    ('price_per_sqft_lowest', 'analysis_sales', '1=1', 'price_per_sqft ASC'),
    ('price_per_sqft_highest', 'analysis_sales', '1=1', 'price_per_sqft DESC'),
    ('contract_over_sales_10pct_not_at_appraisal', 'analysis_sales',
     f'contract_price IS NOT NULL AND {GAP} >= 0.10 AND COALESCE(sold_at_appraisal, 0) = 0', f'{GAP} DESC'),
    ('contract_under_sales_by_10pct+', 'analysis_sales', f'contract_price IS NOT NULL AND {GAP} <= -0.10', f'{GAP} ASC'),
    ('sales_far_below_appraisal', 'sales_full', 'sales_to_appraisal_ratio < 0.6', 'sales_to_appraisal_ratio ASC'),
    ('sales_far_above_appraisal', 'sales_full', 'sales_to_appraisal_ratio > 1.4', 'sales_to_appraisal_ratio DESC'),
]
for flag in ('gla_suspect', 'gla_very_large', 'tax_catastro_mismatch', 'price_per_sqft_outlier',
             'contract_price_suspect', 'contract_after_settled_date', 'bad_contract_date', 'dom_unrecognized',
             'bad_latitude', 'bad_longitude', 'mixed_sales_type'):
    CHECKS.append((f'flag:{flag}', 'sales_full', f"COALESCE(quality_flags,'') LIKE '%{flag}%'", 'property_id'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/processed/san_juan_sales.db')
    ap.add_argument('--out', default='data/processed/review_list.csv')
    ap.add_argument('--limit', type=int, default=25, help='max records per problem type')
    args = ap.parse_args()
    con = sqlite3.connect(args.db)

    out_rows, header = [], None
    for reason, src, where, order in CHECKS:
        total = con.execute(f'SELECT COUNT(*) FROM {src} WHERE {where}').fetchone()[0]
        cur = con.execute(f'SELECT {COLS} FROM {src} WHERE {where} ORDER BY {order} LIMIT {args.limit}')
        header = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f'\n{reason}: {total} records' + (f' (showing {len(rows)})' if total > len(rows) else ''))
        for r in rows:
            d = dict(zip(header, r))
            print(f"  {d['property_id']} | {d['municipality']} | sale ${d['sales_price']:,.0f}"
                  f" | appraisal {('$%s' % format(d['appraisal_value'], ',.0f')) if d['appraisal_value'] else '-'}"
                  f" | contract {('$%s' % format(d['contract_price'], ',.0f')) if d['contract_price'] else '-'}"
                  f" | {d['gla_sqft'] or '-'} sqft, {int(d['bedrooms']) if d['bedrooms'] else '-'} bd | {d['source_file']}:{d['source_line']}")
            out_rows.append([reason] + list(r))

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['reason'] + header)
        w.writerows(out_rows)
    print(f'\nWrote {len(out_rows)} rows to {path}')


if __name__ == '__main__':
    main()