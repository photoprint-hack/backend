"""Additive v2.0 impact extension; no existing table changes."""

from alembic import op

revision = "20261112_03"
down_revision = "20261112_02"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "CREATE TABLE department_responsibilities (\n\tdepartment_id UUID NOT NULL, \n\thead_id UUID NOT NULL, \n\tdirector_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_department_responsibilities PRIMARY KEY (id), \n\tCONSTRAINT uq_department_responsibilities_department_id UNIQUE (department_id), \n\tCONSTRAINT fk_department_responsibilities_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), \n\tCONSTRAINT fk_department_responsibilities_head_id_users FOREIGN KEY(head_id) REFERENCES users (id), \n\tCONSTRAINT fk_department_responsibilities_director_id_users FOREIGN KEY(director_id) REFERENCES users (id)\n)",
    "CREATE TABLE metric_responsibilities (\n\tmetric_code VARCHAR(64) NOT NULL, \n\tdepartment_id UUID, \n\towner_id UUID NOT NULL, \n\tversion INTEGER NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_metric_responsibilities PRIMARY KEY (id), \n\tCONSTRAINT fk_metric_responsibilities_metric_code_metrics FOREIGN KEY(metric_code) REFERENCES metrics (code), \n\tCONSTRAINT fk_metric_responsibilities_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), \n\tCONSTRAINT fk_metric_responsibilities_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id)\n)",
    "CREATE UNIQUE INDEX uq_metric_responsibility_scope ON metric_responsibilities (metric_code, department_id) NULLS NOT DISTINCT",
    "CREATE TABLE management_actions (\n\ttype VARCHAR(32) NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tauthor_id UUID NOT NULL, \n\tassignee_id UUID, \n\tdepartment_id UUID NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\ttext TEXT NOT NULL, \n\tpriority VARCHAR(32) NOT NULL, \n\tmetric_code VARCHAR(64), \n\tsource_ref JSONB, \n\tcontext JSONB NOT NULL, \n\tscoped_context JSONB NOT NULL, \n\tdecision_id UUID, \n\talert_id UUID, \n\torder_id UUID, \n\ttask_id UUID, \n\tplanned_deadline TIMESTAMP WITH TIME ZONE, \n\tresponse_due_at TIMESTAMP WITH TIME ZONE, \n\tcalendar_version VARCHAR(64), \n\tassignment_cycle INTEGER NOT NULL, \n\tescalation_level INTEGER NOT NULL, \n\tsent_at TIMESTAMP WITH TIME ZONE, \n\tacknowledged_at TIMESTAMP WITH TIME ZONE, \n\tresolved_at TIMESTAMP WITH TIME ZONE, \n\tverified_at TIMESTAMP WITH TIME ZONE, \n\treviewer_id UUID, \n\tresult TEXT, \n\tresult_refs JSONB NOT NULL, \n\tverification_note TEXT, \n\trouting_issue VARCHAR(64), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_management_actions PRIMARY KEY (id), \n\tCONSTRAINT ck_management_actions_type CHECK (type IN ('reminder','explanation_request','task')), \n\tCONSTRAINT ck_management_actions_status CHECK (status IN ('draft','sent','acknowledged','in_progress','resolved','verified','rejected','cancelled')), \n\tCONSTRAINT ck_management_actions_values CHECK (priority IN ('low','medium','high','critical') AND version>0 AND assignment_cycle>=0), \n\tCONSTRAINT ck_management_actions_recipient CHECK (status='draft' OR assignee_id IS NOT NULL OR status='cancelled'), \n\tCONSTRAINT fk_management_actions_author_id_users FOREIGN KEY(author_id) REFERENCES users (id), \n\tCONSTRAINT fk_management_actions_assignee_id_users FOREIGN KEY(assignee_id) REFERENCES users (id), \n\tCONSTRAINT fk_management_actions_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), \n\tCONSTRAINT fk_management_actions_metric_code_metrics FOREIGN KEY(metric_code) REFERENCES metrics (code), \n\tCONSTRAINT fk_management_actions_decision_id_decisions FOREIGN KEY(decision_id) REFERENCES decisions (id), \n\tCONSTRAINT fk_management_actions_alert_id_alerts FOREIGN KEY(alert_id) REFERENCES alerts (id), \n\tCONSTRAINT fk_management_actions_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id), \n\tCONSTRAINT fk_management_actions_task_id_tasks FOREIGN KEY(task_id) REFERENCES tasks (id), \n\tCONSTRAINT fk_management_actions_reviewer_id_users FOREIGN KEY(reviewer_id) REFERENCES users (id)\n)",
    "CREATE INDEX ix_management_actions_assignee_id ON management_actions (assignee_id)",
    "CREATE INDEX ix_management_actions_department_id ON management_actions (department_id)",
    "CREATE INDEX ix_management_actions_response_due_at ON management_actions (response_due_at)",
    "CREATE INDEX ix_management_actions_status ON management_actions (status)",
    "CREATE INDEX ix_management_actions_task_id ON management_actions (task_id)",
    "CREATE UNIQUE INDEX uq_action_active_task ON management_actions (task_id) WHERE task_id IS NOT NULL AND status NOT IN ('draft','verified','rejected','cancelled')",
)


def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE management_actions")
    op.execute("DROP TABLE metric_responsibilities")
    op.execute("DROP TABLE department_responsibilities")
