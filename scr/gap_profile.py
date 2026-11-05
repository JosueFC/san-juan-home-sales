"""Profile the gap between sales price and appraised value.

Run from the repo root:
    python scr/gap_profile.py [--db data/processed/san_juan_sales.db]

Counts and averages only (no names or addresses), safe to paste.
"""
import argparse
import sqlite3

BUCKET = ("CASE WHEN sales_to_appraisal_ratio < 0.6 THEN '1) under 0.60' "
          "WHEN sales_to_appraisal_ratio < 0.8 THEN '2) 0.60-0.79' "
          "WHEN sales_to_appraisal_ratio < 0.95 THEN '3) 0.80-0.94' "
          "WHEN sales_to_appraisal_ratio <= 1.05 THEN '4) 0.95-1.05' "
          "ELSE '5) above 1.05' END")
POOR = "condition_code IN ('C4','C5','C6')"


def show(title, header, rows):
    print(f'\n{title}\n  ' + ' | '.join(header))
    for r in rows:
        print('  ' + ' | '.join('-' if x is None else str(x) for x in r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/processed/san_juan_sales.db')
    con = sqlite3.connect(ap.parse_args().db)
    q = lambda sql: con.execute(sql).fetchall()

    show('By sales-to-appraisal ratio band (analysis set)',
         ['band', 'sales', '% FHA', '% conventional', '% poor condition C4-C6', 'avg age', 'avg price', 'avg $/sqft'],
         q(f"SELECT {BUCKET} AS band, COUNT(*), "
           "ROUND(100.0*AVG(loan_type LIKE 'FHA%'),0), ROUND(100.0*AVG(loan_type = 'Conventional'),0), "
           f"ROUND(100.0*AVG({POOR}),0), ROUND(AVG(actual_age),0), ROUND(AVG(sales_price),0), ROUND(AVG(price_per_sqft),0) "
           "FROM analysis_sales WHERE sales_to_appraisal_ratio IS NOT NULL GROUP BY 1 ORDER BY 1"))

    show('By loan type (loan type | sales | avg ratio | % below 0.80)',
         ['loan type', 'sales', 'avg ratio', '% below 0.80'],
         q("SELECT COALESCE(NULLIF(loan_type,''),'(blank)'), COUNT(*), ROUND(AVG(sales_to_appraisal_ratio),2), "
           "ROUND(100.0*AVG(sales_to_appraisal_ratio < 0.8),0) FROM analysis_sales "
           "WHERE sales_to_appraisal_ratio IS NOT NULL GROUP BY 1 HAVING COUNT(*) >= 10 ORDER BY 2 DESC"))

    show('By condition code', ['condition', 'sales', 'avg ratio', '% below 0.80'],
         q("SELECT COALESCE(NULLIF(condition_code,''),'(blank)'), COUNT(*), ROUND(AVG(sales_to_appraisal_ratio),2), "
           "ROUND(100.0*AVG(sales_to_appraisal_ratio < 0.8),0) FROM analysis_sales "
           "WHERE sales_to_appraisal_ratio IS NOT NULL GROUP BY 1 ORDER BY 1"))

    show('By occupancy', ['occupancy', 'sales', 'avg ratio', '% below 0.80'],
         q("SELECT COALESCE(NULLIF(occupancy,''),'(blank)'), COUNT(*), ROUND(AVG(sales_to_appraisal_ratio),2), "
           "ROUND(100.0*AVG(sales_to_appraisal_ratio < 0.8),0) FROM analysis_sales "
           "WHERE sales_to_appraisal_ratio IS NOT NULL GROUP BY 1 HAVING COUNT(*) >= 10 ORDER BY 2 DESC"))

    show('By municipality', ['municipality', 'sales', 'avg ratio', '% below 0.80'],
         q("SELECT municipality, COUNT(*), ROUND(AVG(sales_to_appraisal_ratio),2), "
           "ROUND(100.0*AVG(sales_to_appraisal_ratio < 0.8),0) FROM analysis_sales "
           "WHERE sales_to_appraisal_ratio IS NOT NULL GROUP BY 1 ORDER BY 3"))

    show('Appraisal value: how often present (analysis set sales | with appraisal value)',
         ['sales', 'with appraisal value'],
         q("SELECT COUNT(*), SUM(appraisal_value IS NOT NULL) FROM analysis_sales"))


if __name__ == '__main__':
    main()