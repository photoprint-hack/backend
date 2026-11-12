"""Additive v2.0 impact extension; no existing table changes."""

from alembic import op

revision = "20261112_05"
down_revision = "20261112_04"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "CREATE TABLE ai_analyses (\n\tuser_id UUID NOT NULL, \n\tcache_key VARCHAR(64) NOT NULL, \n\trequest_key UUID NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tmodel VARCHAR(200), \n\tpayload JSONB, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\terror_code VARCHAR(64), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_ai_analyses PRIMARY KEY (id), \n\tCONSTRAINT uq_ai_analyses_user_id UNIQUE (user_id, request_key), \n\tCONSTRAINT fk_ai_analyses_user_id_users FOREIGN KEY(user_id) REFERENCES users (id), \n\tCONSTRAINT uq_ai_analyses_cache_key UNIQUE (cache_key)\n)",
    "CREATE INDEX ix_ai_analyses_expires_at ON ai_analyses (expires_at)",
    "CREATE INDEX ix_ai_analyses_user_id ON ai_analyses (user_id)",
    "CREATE TABLE mary_events (\n\texternal_id VARCHAR(200) NOT NULL, \n\tevent_type VARCHAR(64) NOT NULL, \n\toccurred_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdepartment_id UUID NOT NULL, \n\torder_id UUID, \n\tmetadata_safe JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_mary_events PRIMARY KEY (id), \n\tCONSTRAINT ck_mary_events_type CHECK (event_type IN ('conversation_started','conversation_resolved','conversation_handoff','lead_qualified','order_intent_detected')), \n\tCONSTRAINT uq_mary_events_external_id UNIQUE (external_id), \n\tCONSTRAINT fk_mary_events_department_id_departments FOREIGN KEY(department_id) REFERENCES departments (id), \n\tCONSTRAINT fk_mary_events_order_id_orders FOREIGN KEY(order_id) REFERENCES orders (id)\n)",
    "CREATE INDEX ix_mary_events_department_id ON mary_events (department_id)",
    "CREATE INDEX ix_mary_events_occurred_at ON mary_events (occurred_at)",
)


def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE mary_events")
    op.execute("DROP TABLE ai_analyses")
