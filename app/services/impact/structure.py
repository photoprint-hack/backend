"""Versioned structural projection; links describe provenance, not causal inference."""

REVISION = "impact-structure-v1"
PROCESSES = {
    "sales": (
        "Продажи",
        {"revenue", "new_customers", "active_customers", "repeat_purchase_rate", "sales_plan_achievement"},
        "crm",
    ),
    "production": ("Производство", {"on_time_orders", "defect_rate", "capacity_utilization"}, "erp"),
    "finance": ("Финансы", {"gross_margin"}, "finance"),
    "support": ("Поддержка", {"support_sla"}, "support"),
    "hr": ("Персонал", {"staffing_coverage"}, "hr"),
}
