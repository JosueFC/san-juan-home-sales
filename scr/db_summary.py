"""Quick health check of the analysis set. Run from the repo root:
    python scr/db_summary.py [--db data/processed/san_juan_sales.db]
Prints counts only (no names or addresses), safe to paste into an issue or chat.
"""
import argparse
import sqlite3

BASE = ("arms_length = 1 AND sales_price IS NOT NULL AND gla_sqft > 0 "
        "AND COALESCE(quality_flags,'') NOT LIKE '%price_per_sqft_outlier%' "
        "AND COALESCE(quality_flags,'') NOT LIKE '%very_low_price%' "
        "AND COALESCE(quality_flags,'') NOT LIKE '%contract_price_suspect%' "
        "AND COALESCE(quality_flags,'') NOT LIKE '%contract_after_settled_date%' "
        "AND COALESCE(quality_flags,'') NOT LIKE '%bad_contract_date%'")


def show(title, rows):
    print(f'\n{title}')
    for r in rows:
        print('  ' + ' | '.join(str(x) for x in r))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default='data/processed/san_juan_sales.db')
    con = sqlite3.connect(ap.parse_args().db)
    q = lambda sql: con.execute(sql).fetchall()

    show('All records vs analysis set, by municipality (total | in analysis set | % kept)', q(
        "SELECT s.municipality, COUNT(*), SUM(a.property_id IS NOT NULL), "
        "ROUND(100.0 * SUM(a.property_id IS NOT NULL) / COUNT(*), 0) "
        "FROM sales_full s LEFT JOIN analysis_sales a USING (property_id) GROUP BY 1 ORDER BY 2 DESC"))

    show('Why records fall out, by municipality (no sales type | non-arms-length | arms-length but no living area | arms-length but data-flagged | kept)', q(
        "SELECT s.municipality, "
        "SUM(COALESCE(s.sales_type,'') = ''), "
        "SUM(COALESCE(s.sales_type,'') <> '' AND s.arms_length = 0), "
        "SUM(s.arms_length = 1 AND (s.gla_sqft IS NULL OR s.gla_sqft <= 0)), "
        "SUM(s.arms_length = 1 AND s.gla_sqft > 0 AND a.property_id IS NULL), "
        "SUM(a.property_id IS NOT NULL) "
        "FROM sales_full s LEFT JOIN analysis_sales a USING (property_id) GROUP BY 1 ORDER BY 2 DESC"))

    show('Settled sale date range in analysis set (first | last)',
         q("SELECT MIN(settled_sale_date), MAX(settled_sale_date) FROM analysis_sales"))

    show('Analysis sales per quarter', q(
        "SELECT settled_quarter, COUNT(*) FROM analysis_sales GROUP BY 1 ORDER BY 1"))

    show('Neighborhoods: total | with 5+ sales | with 8+ sales | with 15+ sales', q(
        "SELECT COUNT(*), SUM(n >= 5), SUM(n >= 8), SUM(n >= 15) FROM "
        "(SELECT COUNT(*) AS n FROM analysis_sales GROUP BY municipality, neighborhood)"))

    show('Sale types across ALL records (type | count)', q(
        "SELECT COALESCE(NULLIF(sales_type,''),'(none)'), COUNT(*) FROM sales GROUP BY 1 ORDER BY 2 DESC"))

    show('Sales excluded ONLY because of registry_derived_data (count)', q(
        f"SELECT COUNT(*) FROM sales_full WHERE {BASE} AND quality_flags LIKE '%registry_derived_data%'"))

    show('Tenant-buyer sales: in analysis set | total', q(
        "SELECT (SELECT COUNT(*) FROM analysis_sales WHERE buyer_is_tenant = 1), "
        "(SELECT COUNT(*) FROM sales WHERE buyer_is_tenant = 1)"))

    show('Contract vs sales price, relative gap in analysis set (bucket | count)', q(
        "SELECT CASE WHEN ABS(contract_minus_sales_price) < 1 THEN '0 equal' "
        "WHEN ABS(contract_minus_sales_price) / sales_price < 0.02 THEN '<2%' "
        "WHEN ABS(contract_minus_sales_price) / sales_price < 0.10 THEN '2-10%' "
        "ELSE '>10%' END AS gap, COUNT(*) FROM analysis_sales WHERE contract_price IS NOT NULL GROUP BY 1 ORDER BY 1"))

    show('Contract vs sales price gap above 10% in analysis set (contract higher | contract lower)', q(
        "SELECT SUM(contract_minus_sales_price > 0), SUM(contract_minus_sales_price < 0) FROM analysis_sales "
        "WHERE contract_price IS NOT NULL AND ABS(contract_minus_sales_price) / sales_price >= 0.10"))

    show('Most extreme price per sqft in analysis set (id | municipality | price | living area | $/sqft)',
         q("SELECT property_id, municipality, sales_price, gla_sqft, ROUND(price_per_sqft,0) FROM (SELECT * FROM analysis_sales ORDER BY price_per_sqft LIMIT 5) "
           "UNION ALL SELECT property_id, municipality, sales_price, gla_sqft, ROUND(price_per_sqft,0) FROM (SELECT * FROM analysis_sales ORDER BY price_per_sqft DESC LIMIT 5)"))

    show('Price per sqft spread (min | max | mean) in analysis set',
         q("SELECT ROUND(MIN(price_per_sqft),0), ROUND(MAX(price_per_sqft),0), ROUND(AVG(price_per_sqft),0) FROM analysis_sales"))


if __name__ == '__main__':
    main()