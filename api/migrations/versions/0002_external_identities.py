"""external identities: admin-linked Google sign-in and single-use OAuth flows (ADR-019)

Adds two tables and changes nothing that exists:
- user_identities: a Google account (email; subject bound on first use) linked by an admin to an
  existing user. Never created from a sign-in attempt.
- oauth_flows: one in-flight sign-in (SHA-256 of the state, nonce, PKCE verifier, destination),
  deleted when used and refused after it expires.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-30 09:30:00+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('google')", name=op.f("ck_user_identities_known_provider")
        ),
        sa.CheckConstraint(
            "email = lower(email) AND position('@' in email) > 1",
            name=op.f("ck_user_identities_email_format"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_identities")),
        sa.UniqueConstraint("provider", "email", name="uq_user_identities_provider_email"),
    )
    op.create_index(
        "uq_user_identities_provider_subject",
        "user_identities",
        ["provider", "subject"],
        unique=True,
        postgresql_where=sa.text("subject IS NOT NULL"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"], unique=False)
    op.create_table(
        "oauth_flows",
        sa.Column("state_sha256", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("nonce", sa.String(length=128), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("next_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state_sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_oauth_flows_state_sha256_hex")
        ),
        sa.CheckConstraint("provider IN ('google')", name=op.f("ck_oauth_flows_known_provider")),
        sa.CheckConstraint(
            "left(next_path, 1) = '/'", name=op.f("ck_oauth_flows_next_path_relative")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_oauth_flows_expires_after_created")
        ),
        sa.PrimaryKeyConstraint("state_sha256", name=op.f("pk_oauth_flows")),
    )


def downgrade() -> None:
    op.drop_table("oauth_flows")
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_index(
        "uq_user_identities_provider_subject",
        table_name="user_identities",
        postgresql_where=sa.text("subject IS NOT NULL"),
    )
    op.drop_table("user_identities")
