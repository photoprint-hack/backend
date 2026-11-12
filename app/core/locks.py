"""Named PostgreSQL advisory-lock keys shared across the application.

PostgreSQL advisory locks accept arbitrary signed 64-bit integers, so the
names below are the only documentation of what each number guards. The numeric
values are part of deployed database behavior: keep them stable and unique.
"""

# Serializes KPI recalculation and the write paths that can invalidate metrics
# (order create/patch, imports, demo reset and seed), taken before row writes.
RECALCULATION = 178901234

# Serializes read-modify-write transitions of workflow objects (tasks and
# management actions) and data-quality checks that resolve those same issues.
WORKFLOW_ACTION = 178901235

# Serializes the AI-analysis reservation/lease window. The startup migration
# reuses this key as a session-level lock so a migration never races an
# in-flight analysis request.
AI_ANALYSIS = 178901236

# Serializes ingestion of simulated "Mary" events.
MARY_INGEST = 178901237

# Serializes writes to department/metric responsibility assignments.
RESPONSIBILITY = 178901238
