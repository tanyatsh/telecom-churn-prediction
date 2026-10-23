CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE OR REPLACE TABLE raw.telco_churn AS
SELECT *
FROM read_csv(
    '{csv_path}',
    header = true,
    all_varchar = true
);

CREATE OR REPLACE TABLE analytics.customers AS
SELECT
    NULLIF(TRIM("customerID"), '') AS customer_id,
    NULLIF(TRIM("gender"), '') AS gender,
    CASE TRIM("SeniorCitizen")
        WHEN '0' THEN FALSE
        WHEN '1' THEN TRUE
        ELSE NULL
    END AS senior_citizen,
    NULLIF(TRIM("Partner"), '') AS partner,
    NULLIF(TRIM("Dependents"), '') AS dependents,
    TRY_CAST(NULLIF(TRIM("tenure"), '') AS SMALLINT) AS tenure_months,
    NULLIF(TRIM("PhoneService"), '') AS phone_service,
    NULLIF(TRIM("MultipleLines"), '') AS multiple_lines,
    NULLIF(TRIM("InternetService"), '') AS internet_service,
    NULLIF(TRIM("OnlineSecurity"), '') AS online_security,
    NULLIF(TRIM("OnlineBackup"), '') AS online_backup,
    NULLIF(TRIM("DeviceProtection"), '') AS device_protection,
    NULLIF(TRIM("TechSupport"), '') AS tech_support,
    NULLIF(TRIM("StreamingTV"), '') AS streaming_tv,
    NULLIF(TRIM("StreamingMovies"), '') AS streaming_movies,
    NULLIF(TRIM("Contract"), '') AS contract,
    NULLIF(TRIM("PaperlessBilling"), '') AS paperless_billing,
    NULLIF(TRIM("PaymentMethod"), '') AS payment_method,
    TRY_CAST(NULLIF(TRIM("MonthlyCharges"), '') AS DECIMAL(10, 2)) AS monthly_charges,
    TRY_CAST(NULLIF(TRIM("TotalCharges"), '') AS DECIMAL(12, 2)) AS total_charges,
    CASE TRIM("Churn")
        WHEN 'Yes' THEN TRUE
        WHEN 'No' THEN FALSE
        ELSE NULL
    END AS churned,
    CASE
        WHEN TRY_CAST(TRIM("tenure") AS SMALLINT) = 0 THEN '00 months'
        WHEN TRY_CAST(TRIM("tenure") AS SMALLINT) BETWEEN 1 AND 12 THEN '01-12 months'
        WHEN TRY_CAST(TRIM("tenure") AS SMALLINT) BETWEEN 13 AND 24 THEN '13-24 months'
        WHEN TRY_CAST(TRIM("tenure") AS SMALLINT) BETWEEN 25 AND 48 THEN '25-48 months'
        WHEN TRY_CAST(TRIM("tenure") AS SMALLINT) BETWEEN 49 AND 60 THEN '49-60 months'
        WHEN TRY_CAST(TRIM("tenure") AS SMALLINT) BETWEEN 61 AND 72 THEN '61-72 months'
        ELSE 'Unknown'
    END AS tenure_band,
    CASE
        WHEN TRY_CAST(TRIM("MonthlyCharges") AS DECIMAL(10, 2)) < 30 THEN '<30'
        WHEN TRY_CAST(TRIM("MonthlyCharges") AS DECIMAL(10, 2)) < 60 THEN '30-<60'
        WHEN TRY_CAST(TRIM("MonthlyCharges") AS DECIMAL(10, 2)) < 90 THEN '60-<90'
        WHEN TRY_CAST(TRIM("MonthlyCharges") AS DECIMAL(10, 2)) IS NOT NULL THEN '90+'
        ELSE 'Unknown'
    END AS monthly_charge_band
FROM raw.telco_churn;

CREATE UNIQUE INDEX IF NOT EXISTS customers_customer_id_uidx
    ON analytics.customers (customer_id);

CREATE OR REPLACE VIEW analytics.numeric_summary AS
SELECT
    variable,
    non_null_count,
    null_count,
    minimum,
    q1,
    mean,
    median,
    q3,
    maximum,
    standard_deviation
FROM (
    SELECT
        'tenure_months' AS variable,
        COUNT(tenure_months) AS non_null_count,
        COUNT(*) - COUNT(tenure_months) AS null_count,
        MIN(tenure_months)::DOUBLE AS minimum,
        QUANTILE_CONT(tenure_months, 0.25)::DOUBLE AS q1,
        AVG(tenure_months)::DOUBLE AS mean,
        MEDIAN(tenure_months)::DOUBLE AS median,
        QUANTILE_CONT(tenure_months, 0.75)::DOUBLE AS q3,
        MAX(tenure_months)::DOUBLE AS maximum,
        STDDEV_SAMP(tenure_months)::DOUBLE AS standard_deviation
    FROM analytics.customers
    UNION ALL
    SELECT
        'monthly_charges', COUNT(monthly_charges), COUNT(*) - COUNT(monthly_charges),
        MIN(monthly_charges)::DOUBLE, QUANTILE_CONT(monthly_charges, 0.25)::DOUBLE,
        AVG(monthly_charges)::DOUBLE, MEDIAN(monthly_charges)::DOUBLE,
        QUANTILE_CONT(monthly_charges, 0.75)::DOUBLE, MAX(monthly_charges)::DOUBLE,
        STDDEV_SAMP(monthly_charges)::DOUBLE
    FROM analytics.customers
    UNION ALL
    SELECT
        'total_charges', COUNT(total_charges), COUNT(*) - COUNT(total_charges),
        MIN(total_charges)::DOUBLE, QUANTILE_CONT(total_charges, 0.25)::DOUBLE,
        AVG(total_charges)::DOUBLE, MEDIAN(total_charges)::DOUBLE,
        QUANTILE_CONT(total_charges, 0.75)::DOUBLE, MAX(total_charges)::DOUBLE,
        STDDEV_SAMP(total_charges)::DOUBLE
    FROM analytics.customers
);

CREATE OR REPLACE VIEW analytics.churn_by_segment AS
WITH segments AS (
    SELECT 'contract' AS segment, COALESCE(contract, 'Unknown') AS segment_value, churned FROM analytics.customers
    UNION ALL SELECT 'tenure_band', COALESCE(tenure_band, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'payment_method', COALESCE(payment_method, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'internet_service', COALESCE(internet_service, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'monthly_charge_band', COALESCE(monthly_charge_band, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'gender', COALESCE(gender, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'senior_citizen', CASE WHEN senior_citizen THEN 'Yes' WHEN NOT senior_citizen THEN 'No' ELSE 'Unknown' END, churned FROM analytics.customers
    UNION ALL SELECT 'partner', COALESCE(partner, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'dependents', COALESCE(dependents, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'paperless_billing', COALESCE(paperless_billing, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'tech_support', COALESCE(tech_support, 'Unknown'), churned FROM analytics.customers
    UNION ALL SELECT 'online_security', COALESCE(online_security, 'Unknown'), churned FROM analytics.customers
)
SELECT
    segment,
    segment_value,
    COUNT(*) AS group_size,
    COUNT(*) FILTER (WHERE churned) AS churned_customers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE churned) / COUNT(*), 3) AS churn_rate_pct
FROM segments
GROUP BY segment, segment_value;

CREATE OR REPLACE VIEW analytics.churn_by_tenure_month AS
SELECT
    tenure_months,
    COUNT(*) AS group_size,
    COUNT(*) FILTER (WHERE churned) AS churned_customers,
    ROUND(100.0 * COUNT(*) FILTER (WHERE churned) / COUNT(*), 3) AS churn_rate_pct
FROM analytics.customers
GROUP BY tenure_months;
