-- Metabase native SQL templates. Every {{parameter}} must be a locked text parameter.
-- department_id='company' means company-wide for privileged roles only;
-- product_id='all' means no product restriction. Backend never gives company to manager.
-- The application verifies which dashboard IDs have these filters wired to EVERY card.

-- COMPANY: daily revenue, department-safe and product-safe.
SELECT event_date, SUM(revenue) AS revenue
FROM v_revenue_by_day
WHERE event_date BETWEEN CAST({{date_from}} AS date) AND CAST({{date_to}} AS date)
  AND ({{department_id}}='company' OR department_id::text={{department_id}})
  AND ({{product_id}}='all' OR product_id::text={{product_id}})
GROUP BY event_date ORDER BY event_date;

-- COMPANY/FINANCE: plan-fact by day. Do not average achievement percentages.
SELECT event_date, SUM(actual) AS actual, SUM(target) AS target,
       CASE WHEN SUM(target)<>0 THEN SUM(actual)/SUM(target)*100 END AS achievement_percent
FROM v_sales_plan_fact
WHERE event_date BETWEEN CAST({{date_from}} AS date) AND CAST({{date_to}} AS date)
  AND ({{department_id}}='company' OR department_id::text={{department_id}})
  AND ({{product_id}}='all' OR product_id::text={{product_id}})
GROUP BY event_date ORDER BY event_date;

-- PRODUCTION: unit-based defect rate.
SELECT event_date, SUM(actual_quantity) AS actual_quantity,
       SUM(defective_quantity) AS defective_quantity,
       CASE WHEN SUM(actual_quantity)>0 THEN SUM(defective_quantity)::numeric/SUM(actual_quantity)*100 END AS defect_rate
FROM v_production_quality
WHERE event_date BETWEEN CAST({{date_from}} AS date) AND CAST({{date_to}} AS date)
  AND ({{department_id}}='company' OR department_id::text={{department_id}})
  AND ({{product_id}}='all' OR product_id::text={{product_id}})
GROUP BY event_date ORDER BY event_date;

-- SUPPORT: closed ticket cohort, SLA weighted by original counts.
SELECT event_date,
       CASE WHEN SUM(closed_with_sla)>0 THEN SUM(closed_on_time)::numeric/SUM(closed_with_sla)*100 END AS sla_percent
FROM v_support_sla
WHERE event_date BETWEEN CAST({{date_from}} AS date) AND CAST({{date_to}} AS date)
  AND ({{department_id}}='company' OR department_id::text={{department_id}})
  AND ({{product_id}}='all' OR product_id::text={{product_id}})
GROUP BY event_date ORDER BY event_date;

-- HR: latest snapshot on/before period end; product filter explicitly not applicable.
WITH ranked AS (
  SELECT *, row_number() OVER(PARTITION BY department_id ORDER BY snapshot_date DESC) AS rn
  FROM v_staffing_coverage
  WHERE snapshot_date<=CAST({{date_to}} AS date)
    AND ({{department_id}}='company' OR department_id::text={{department_id}})
    AND CAST({{date_from}} AS date)<=CAST({{date_to}} AS date)
    AND CAST({{product_id}} AS text) IS NOT NULL
)
SELECT SUM(available_headcount) AS available_headcount,SUM(required_headcount) AS required_headcount,
       CASE WHEN SUM(required_headcount)>0 THEN SUM(available_headcount)::numeric/SUM(required_headcount)*100 END AS staffing_coverage
FROM ranked WHERE rn=1;
