-- Dashboard queries for san_juan_sales.db (SQLite). Each block feeds one dashboard page.
-- Median in SQLite: rank rows, then average the one or two middle rows.
-- Always show sales_count next to a price: small groups are unreliable.

-- 1. Headline KPIs (analysis set: arms-length, priced, with living area, no hard data flags)
SELECT COUNT(*) AS sales_count,
       ROUND(AVG(sales_price), 0) AS mean_price,
       ROUND(AVG(price_per_sqft), 2) AS mean_price_per_sqft,
       ROUND(AVG(CASE WHEN days_on_market > 0 THEN days_on_market END), 1) AS mean_days_on_market,
       ROUND(AVG(sales_to_appraisal_ratio), 3) AS mean_sales_to_appraisal
FROM analysis_sales;

-- 2. Median price per sqft and sales count by municipality
WITH r AS (
  SELECT municipality, price_per_sqft AS p,
         ROW_NUMBER() OVER (PARTITION BY municipality ORDER BY price_per_sqft) AS rn,
         COUNT(*) OVER (PARTITION BY municipality) AS n
  FROM analysis_sales)
SELECT municipality, n AS sales_count, ROUND(AVG(p), 2) AS median_price_per_sqft
FROM r WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
GROUP BY municipality ORDER BY median_price_per_sqft DESC;

-- 3. Quarterly trend, all municipalities combined
WITH r AS (
  SELECT settled_quarter, price_per_sqft AS p,
         ROW_NUMBER() OVER (PARTITION BY settled_quarter ORDER BY price_per_sqft) AS rn,
         COUNT(*) OVER (PARTITION BY settled_quarter) AS n
  FROM analysis_sales WHERE settled_quarter IS NOT NULL)
SELECT settled_quarter, n AS sales_count, ROUND(AVG(p), 2) AS median_price_per_sqft
FROM r WHERE rn IN ((n + 1) / 2, (n + 2) / 2)
GROUP BY settled_quarter ORDER BY settled_quarter;

-- 4. Monthly market by municipality (ready-made view, also exported to bi_export/market_monthly.csv)
SELECT * FROM market_monthly ORDER BY municipality, settled_month;

-- 5. Neighborhood ranking (only neighborhoods with at least 8 sales)
WITH r AS (
  SELECT municipality, neighborhood, price_per_sqft AS p,
         ROW_NUMBER() OVER (PARTITION BY municipality, neighborhood ORDER BY price_per_sqft) AS rn,
         COUNT(*) OVER (PARTITION BY municipality, neighborhood) AS n
  FROM analysis_sales)
SELECT municipality, neighborhood, n AS sales_count, ROUND(AVG(p), 2) AS median_price_per_sqft
FROM r WHERE n >= 8 AND rn IN ((n + 1) / 2, (n + 2) / 2)
GROUP BY municipality, neighborhood ORDER BY median_price_per_sqft DESC;

-- 6. Deal mix: every sale type, using ALL records (not just the clean analysis set)
SELECT COALESCE(NULLIF(sales_type, ''), 'Unknown (registry-derived)') AS sales_type,
       COUNT(*) AS sales_count,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM sales), 1) AS pct_of_records
FROM sales GROUP BY 1 ORDER BY sales_count DESC;

-- 7. Loan type mix by municipality
SELECT municipality, COALESCE(NULLIF(loan_type, ''), 'Unknown') AS loan_type, COUNT(*) AS sales_count
FROM sales_full GROUP BY 1, 2 ORDER BY municipality, sales_count DESC;

-- 8. Appraisal gap: sales price relative to appraised value, by municipality
SELECT municipality, COUNT(*) AS sales_count,
       ROUND(AVG(sales_to_appraisal_ratio), 3) AS mean_ratio,
       SUM(sales_to_appraisal_ratio > 1) AS sold_above_appraisal,
       SUM(sales_to_appraisal_ratio < 1) AS sold_below_appraisal
FROM analysis_sales WHERE sales_to_appraisal_ratio IS NOT NULL
GROUP BY municipality ORDER BY mean_ratio DESC;

-- 9. Price by property condition and age band
SELECT condition_code,
       CASE WHEN actual_age < 10 THEN '0-9' WHEN actual_age < 30 THEN '10-29'
            WHEN actual_age < 50 THEN '30-49' ELSE '50+' END AS age_band,
       COUNT(*) AS sales_count, ROUND(AVG(price_per_sqft), 2) AS mean_price_per_sqft
FROM analysis_sales WHERE condition_code <> '' AND actual_age IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2;

-- 10. Amenity premium: mean price per sqft with and without each feature
SELECT 'pool' AS amenity, has_pool AS has_it, COUNT(*) AS sales_count, ROUND(AVG(price_per_sqft), 2) AS mean_price_per_sqft FROM analysis_sales GROUP BY has_pool
UNION ALL SELECT 'terrace', has_terrace, COUNT(*), ROUND(AVG(price_per_sqft), 2) FROM analysis_sales GROUP BY has_terrace
UNION ALL SELECT 'generator', has_generator, COUNT(*), ROUND(AVG(price_per_sqft), 2) FROM analysis_sales GROUP BY has_generator
UNION ALL SELECT 'laundry', has_laundry, COUNT(*), ROUND(AVG(price_per_sqft), 2) FROM analysis_sales GROUP BY has_laundry;
-- Averages here ignore size and location, so treat gaps as hints, not premiums; the regression model estimates them properly.

-- 11. Days on market by municipality (listed sales only; 0 days means the home was never listed)
SELECT municipality, COUNT(*) AS sales_count, ROUND(AVG(days_on_market), 1) AS mean_days_on_market
FROM analysis_sales WHERE days_on_market > 0
GROUP BY municipality ORDER BY mean_days_on_market;

-- 12. Data quality page: how many records carry each flag, and how many were excluded
SELECT COUNT(*) AS total_records, (SELECT COUNT(*) FROM analysis_sales) AS in_analysis_set,
       SUM(COALESCE(quality_flags, '') <> '') AS records_with_flags FROM sales;
SELECT quality_flags, COUNT(*) AS records FROM sales WHERE COALESCE(quality_flags, '') <> '' GROUP BY quality_flags ORDER BY records DESC;

-- 14. Renegotiation: how often the final price was cut from the contract price,
--     and how often it landed exactly on the appraised value. price_change_from_contract_pct is negative for cuts.
SELECT municipality,
       COUNT(*) AS sales_with_contract_price,
       SUM(contract_minus_sales_price > 0) AS price_cut,
       SUM(contract_minus_sales_price > 0 AND sold_at_appraisal = 1) AS cut_to_appraisal,
       ROUND(100.0 * SUM(contract_minus_sales_price > 0) / COUNT(*), 1) AS pct_cut,
       ROUND(AVG(CASE WHEN contract_minus_sales_price > 0 THEN price_change_from_contract_pct END), 1) AS avg_cut_pct
FROM analysis_sales WHERE contract_price IS NOT NULL
GROUP BY municipality ORDER BY pct_cut DESC;
