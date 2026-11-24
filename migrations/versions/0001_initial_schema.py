"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-11-24 12:11:17.880579
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('api_clients',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('scopes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_clients')),
    sa.UniqueConstraint('key_hash', name=op.f('uq_api_clients_key_hash')),
    sa.UniqueConstraint('name', name=op.f('uq_api_clients_name'))
    )
    op.create_table('incidents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('service', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('severity', sa.Enum('critical', 'high', 'medium', 'low', 'info', name='severity'), nullable=False),
    sa.Column('status', sa.Enum('NEW', 'TRIAGING', 'AWAITING_APPROVAL', 'REMEDIATING', 'VERIFYING', 'MANUAL', 'ESCALATED', 'RESOLVED', 'SUPPRESSED', name='incident_status'), nullable=False),
    sa.Column('tier', sa.Integer(), nullable=True),
    sa.Column('error_class', sa.String(length=255), nullable=True),
    sa.Column('rca_summary', sa.Text(), nullable=True),
    sa.Column('occurrence_count', sa.Integer(), nullable=False),
    sa.Column('reproposal_count', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.String(length=64), nullable=True),
    sa.Column('ticket_url', sa.String(length=500), nullable=True),
    sa.Column('assignee', sa.String(length=255), nullable=True),
    sa.Column('last_signal_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incidents'))
    )
    op.create_index('ix_incidents_created_id', 'incidents', ['created_at', 'id'], unique=False)
    op.create_index('ix_incidents_status_created', 'incidents', ['status', 'created_at'], unique=False)
    op.create_index('uq_incidents_open_fingerprint', 'incidents', ['fingerprint'], unique=True, postgresql_where=sa.text("status IN ('AWAITING_APPROVAL', 'ESCALATED', 'MANUAL', 'NEW', 'REMEDIATING', 'TRIAGING', 'VERIFYING')"), sqlite_where=sa.text("status IN ('AWAITING_APPROVAL', 'ESCALATED', 'MANUAL', 'NEW', 'REMEDIATING', 'TRIAGING', 'VERIFYING')"))
    op.create_table('agent_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('agent', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('prompt_version', sa.String(length=64), nullable=False),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_agent_runs_incident_id_incidents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_runs'))
    )
    op.create_index(op.f('ix_agent_runs_incident_id'), 'agent_runs', ['incident_id'], unique=False)
    op.create_table('alert_signals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.Enum('alertmanager', 'gcp_monitoring', 'generic', name='alert_source'), nullable=False),
    sa.Column('client_name', sa.String(length=255), nullable=False),
    sa.Column('status', sa.Enum('firing', 'resolved', name='signal_status'), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=True),
    sa.Column('service', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('severity', sa.Enum('critical', 'high', 'medium', 'low', 'info', name='severity'), nullable=False),
    sa.Column('trace_id', sa.String(length=255), nullable=True),
    sa.Column('labels', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('raw', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_alert_signals_incident_id_incidents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert_signals'))
    )
    op.create_index(op.f('ix_alert_signals_incident_id'), 'alert_signals', ['incident_id'], unique=False)
    op.create_table('incident_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('from_status', sa.Enum('NEW', 'TRIAGING', 'AWAITING_APPROVAL', 'REMEDIATING', 'VERIFYING', 'MANUAL', 'ESCALATED', 'RESOLVED', 'SUPPRESSED', name='incident_status'), nullable=True),
    sa.Column('to_status', sa.Enum('NEW', 'TRIAGING', 'AWAITING_APPROVAL', 'REMEDIATING', 'VERIFYING', 'MANUAL', 'ESCALATED', 'RESOLVED', 'SUPPRESSED', name='incident_status'), nullable=True),
    sa.Column('actor', sa.String(length=255), nullable=False),
    sa.Column('data', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_incident_events_incident_id_incidents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident_events'))
    )
    op.create_index('ix_incident_events_incident_id_id', 'incident_events', ['incident_id', 'id'], unique=False)
    op.create_table('remediation_actions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('action_type', sa.Enum('restart_deployment', 'scale_deployment', 'delete_pod', 'rollback_deployment', name='action_type'), nullable=False),
    sa.Column('params', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('proposed', 'succeeded', 'dry_run', 'failed', 'cancelled', name='action_status'), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_remediation_actions_incident_id_incidents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_remediation_actions'))
    )
    op.create_index(op.f('ix_remediation_actions_incident_id'), 'remediation_actions', ['incident_id'], unique=False)
    op.create_table('approvals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('action_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'expired', name='approval_status'), nullable=False),
    sa.Column('decided_by', sa.String(length=255), nullable=True),
    sa.Column('rejection_reason', sa.Enum('false_positive', 'handle_manually', 'wrong_action', name='rejection_reason'), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['action_id'], ['remediation_actions.id'], name=op.f('fk_approvals_action_id_remediation_actions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_approvals_incident_id_incidents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals'))
    )
    op.create_index(op.f('ix_approvals_incident_id'), 'approvals', ['incident_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_approvals_incident_id'), table_name='approvals')
    op.drop_table('approvals')
    op.drop_index(op.f('ix_remediation_actions_incident_id'), table_name='remediation_actions')
    op.drop_table('remediation_actions')
    op.drop_index('ix_incident_events_incident_id_id', table_name='incident_events')
    op.drop_table('incident_events')
    op.drop_index(op.f('ix_alert_signals_incident_id'), table_name='alert_signals')
    op.drop_table('alert_signals')
    op.drop_index(op.f('ix_agent_runs_incident_id'), table_name='agent_runs')
    op.drop_table('agent_runs')
    op.drop_index('uq_incidents_open_fingerprint', table_name='incidents', postgresql_where=sa.text("status IN ('AWAITING_APPROVAL', 'ESCALATED', 'MANUAL', 'NEW', 'REMEDIATING', 'TRIAGING', 'VERIFYING')"), sqlite_where=sa.text("status IN ('AWAITING_APPROVAL', 'ESCALATED', 'MANUAL', 'NEW', 'REMEDIATING', 'TRIAGING', 'VERIFYING')"))
    op.drop_index('ix_incidents_status_created', table_name='incidents')
    op.drop_index('ix_incidents_created_id', table_name='incidents')
    op.drop_table('incidents')
    op.drop_table('api_clients')
    for enum_name in (
        "rejection_reason",
        "approval_status",
        "action_status",
        "action_type",
        "signal_status",
        "alert_source",
        "incident_status",
        "severity",
        "tier",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
