-- name: overall_summary
SELECT
    COUNT(*) AS customers,
    COUNT(*) FILTER (WHERE churned) AS churned_customers,
    COUNT(*) FILTER (WHERE NOT churned) AS retained_customers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE churned) / COUNT(*), 3) AS churn_rate_pct,
    COUNT(*) FILTER (WHERE total_charges IS NULL) AS missing_total_charges
FROM analytics.customers;

-- name: numeric_summary
SELECT *
FROM analytics.numeric_summary
ORDER BY variable;

-- name: churn_by_contract
SELECT segment_value AS contract, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment = 'contract'
ORDER BY churn_rate_pct DESC, group_size DESC;

-- name: churn_by_tenure_band
SELECT segment_value AS tenure_band, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment = 'tenure_band'
ORDER BY tenure_band;

-- name: churn_by_tenure_month
SELECT tenure_months, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_tenure_month
ORDER BY tenure_months;

-- name: churn_by_payment_method
SELECT segment_value AS payment_method, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment = 'payment_method'
ORDER BY churn_rate_pct DESC, group_size DESC;

-- name: churn_by_internet_service
SELECT segment_value AS internet_service, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment = 'internet_service'
ORDER BY churn_rate_pct DESC, group_size DESC;

-- name: churn_by_monthly_charge_band
SELECT segment_value AS monthly_charge_band, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment = 'monthly_charge_band'
ORDER BY CASE monthly_charge_band
    WHEN '<30' THEN 1 WHEN '30-<60' THEN 2 WHEN '60-<90' THEN 3 WHEN '90+' THEN 4 ELSE 5 END;

-- name: churn_by_service_features
SELECT segment, segment_value, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment IN ('tech_support', 'online_security')
ORDER BY segment, churn_rate_pct DESC, group_size DESC;

-- name: churn_by_customer_and_billing_features
SELECT segment, segment_value, group_size, churned_customers, churn_rate_pct
FROM analytics.churn_by_segment
WHERE segment IN ('gender', 'senior_citizen', 'partner', 'dependents', 'paperless_billing')
ORDER BY segment, churn_rate_pct DESC, group_size DESC;
