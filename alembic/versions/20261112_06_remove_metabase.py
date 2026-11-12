"""Remove retired Metabase views without changing application tables.

Keep the original view revision intact for databases that already applied it.
Downgrade restores the previous view definitions; grants are not recreated.
"""

from alembic import op

revision = "20261112_06"
down_revision = "20261112_05"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "DROP VIEW v_capacity_forecast",
    "DROP VIEW v_staffing_coverage",
    "DROP VIEW v_support_sla",
    "DROP VIEW v_production_quality",
    "DROP VIEW v_sales_plan_fact",
    "DROP VIEW v_orders_by_status",
    "DROP VIEW v_revenue_by_day",
    "DROP VIEW v_dashboard_kpi",
)

DOWNGRADE_SQL = (
    "CREATE VIEW v_dashboard_kpi AS SELECT v.id, m.code AS metric_code, m.name AS metric_name, m.unit, m.formula,\nm.source_description AS source, v.department_id, v.product_id, v.period_start, v.period_end,\nv.actual_value AS actual, v.target_value AS target, v.forecast_value AS forecast,\nv.deviation_percent, v.status, v.calculated_at, v.source_updated_at\nFROM metric_values v JOIN metrics m ON m.id=v.metric_id",
    "CREATE VIEW v_revenue_by_day AS SELECT (completed_at AT TIME ZONE 'Europe/Minsk')::date AS event_date,\ndepartment_id, product_id, currency, SUM(amount)::numeric(20,2) AS revenue,\nCOUNT(*)::bigint AS orders_count\nFROM orders WHERE status='completed'\nGROUP BY 1,2,3,4",
    "CREATE VIEW v_orders_by_status AS SELECT (created_at AT TIME ZONE 'Europe/Minsk')::date AS event_date,\ndepartment_id, product_id, status, currency, COUNT(*)::bigint AS orders_count,\nSUM(amount)::numeric(20,2) AS total_amount FROM orders GROUP BY 1,2,3,4,5",
    "CREATE VIEW v_sales_plan_fact AS WITH targets AS (\n SELECT t.plan_date, t.department_id, t.product_id, SUM(t.target_value) AS target\n FROM metric_targets t JOIN metrics m ON t.metric_id=m.id\n WHERE m.code='revenue' GROUP BY 1,2,3\n), facts AS (\n SELECT event_date, department_id, product_id, SUM(revenue) AS actual\n FROM v_revenue_by_day GROUP BY 1,2,3\n)\nSELECT COALESCE(t.plan_date,f.event_date) AS event_date,\nCOALESCE(t.department_id,f.department_id) AS department_id,\nCOALESCE(t.product_id,f.product_id) AS product_id,\nt.target, COALESCE(f.actual,0)::numeric AS actual,\nCASE WHEN t.target<>0 THEN COALESCE(f.actual,0)/t.target*100 END AS achievement_percent,\nCASE WHEN t.target<>0 THEN (COALESCE(f.actual,0)-t.target)/abs(t.target)*100 END AS deviation_percent\nFROM targets t FULL JOIN facts f ON t.plan_date=f.event_date AND t.department_id=f.department_id AND t.product_id=f.product_id",
    "CREATE VIEW v_production_quality AS SELECT production_date AS event_date, department_id, product_id,\nSUM(planned_quantity)::bigint AS planned_quantity,\nSUM(actual_quantity)::bigint AS actual_quantity,\nSUM(defective_quantity)::bigint AS defective_quantity,\nSUM(reprint_quantity)::bigint AS reprint_quantity,\nSUM(downtime_minutes)::bigint AS downtime_minutes,\nSUM(actual_load_hours) AS actual_load_hours,\nAVG(lead_time_hours) AS average_lead_time_hours,\nCASE WHEN SUM(actual_quantity)>0 THEN SUM(defective_quantity)::numeric/SUM(actual_quantity)*100 END AS defect_rate\nFROM production_records GROUP BY 1,2,3",
    "CREATE VIEW v_support_sla AS SELECT (s.closed_at AT TIME ZONE 'Europe/Minsk')::date AS event_date,\ns.department_id,o.product_id, COUNT(*)::bigint AS closed_with_sla,\nCOUNT(*) FILTER(WHERE s.closed_at<=s.sla_deadline)::bigint AS closed_on_time,\nCOUNT(*) FILTER(WHERE s.closed_at<=s.sla_deadline)::numeric/COUNT(*)*100 AS sla_percent\nFROM support_interactions s LEFT JOIN orders o ON s.order_id=o.id\nWHERE s.status='closed' AND s.sla_deadline IS NOT NULL GROUP BY 1,2,3",
    "CREATE VIEW v_staffing_coverage AS SELECT snapshot_date,department_id,planned_headcount,actual_headcount,\navailable_headcount,required_headcount,vacancies_count,absences_count,\nCASE WHEN required_headcount>0 THEN available_headcount::numeric/required_headcount*100 END AS staffing_coverage\nFROM hr_snapshots",
    "CREATE VIEW v_capacity_forecast AS SELECT as_of,department_id,product_id,period_start,period_end,demand,\navailable_capacity,deficit,reserve,method,status,reason,calculated_at FROM forecast_records",
)


def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade():
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
