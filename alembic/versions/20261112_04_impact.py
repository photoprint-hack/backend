"""Additive v2.0 impact extension; no existing table changes."""

from alembic import op

revision = "20261112_04"
down_revision = "20261112_03"
branch_labels = None
depends_on = None

UPGRADE_SQL = (
    "CREATE TABLE notification_outbox (\n\taction_id UUID NOT NULL, \n\trecipient_id UUID NOT NULL, \n\tkind VARCHAR(64) NOT NULL, \n\tdeduplication_key VARCHAR(250) NOT NULL, \n\tstatus VARCHAR(32) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tavailable_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tlast_error VARCHAR(64), \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_notification_outbox PRIMARY KEY (id), \n\tCONSTRAINT ck_notification_outbox_values CHECK (status IN ('pending','processing','sent','failed') AND attempts>=0), \n\tCONSTRAINT fk_notification_outbox_action_id_management_actions FOREIGN KEY(action_id) REFERENCES management_actions (id), \n\tCONSTRAINT fk_notification_outbox_recipient_id_users FOREIGN KEY(recipient_id) REFERENCES users (id), \n\tCONSTRAINT uq_notification_outbox_deduplication_key UNIQUE (deduplication_key)\n)",
    "CREATE INDEX ix_notification_outbox_action_id ON notification_outbox (action_id)",
    "CREATE INDEX ix_notification_outbox_available_at ON notification_outbox (available_at)",
    "CREATE INDEX ix_notification_outbox_recipient_id ON notification_outbox (recipient_id)",
    "CREATE INDEX ix_notification_outbox_status ON notification_outbox (status)",
    "CREATE TABLE notifications (\n\toutbox_id UUID NOT NULL, \n\taction_id UUID NOT NULL, \n\trecipient_id UUID NOT NULL, \n\tkind VARCHAR(64) NOT NULL, \n\tdelivered_at TIMESTAMP WITH TIME ZONE, \n\tread_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_notifications PRIMARY KEY (id), \n\tCONSTRAINT uq_notifications_outbox_id UNIQUE (outbox_id), \n\tCONSTRAINT fk_notifications_outbox_id_notification_outbox FOREIGN KEY(outbox_id) REFERENCES notification_outbox (id), \n\tCONSTRAINT fk_notifications_action_id_management_actions FOREIGN KEY(action_id) REFERENCES management_actions (id), \n\tCONSTRAINT fk_notifications_recipient_id_users FOREIGN KEY(recipient_id) REFERENCES users (id)\n)",
    "CREATE INDEX ix_notifications_action_id ON notifications (action_id)",
    "CREATE INDEX ix_notifications_recipient_id ON notifications (recipient_id)",
)


def upgrade():
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade():
    op.execute("DROP TABLE notifications")
    op.execute("DROP TABLE notification_outbox")
