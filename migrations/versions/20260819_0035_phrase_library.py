"""Add the manual global phrase library.

Revision ID: 20260819_0035
Revises: 20260819_0034
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_0035"
down_revision = "20260819_0034"
branch_labels = None
depends_on = None


TABLE_COLUMNS = {
    "phrase_library_states": {"id", "revision", "created_at", "updated_at"},
    "phrase_categories": {
        "id", "category_key", "name", "source", "position", "active",
        "created_at", "updated_at",
    },
    "phrase_snippets": {
        "id", "category_id", "content", "position", "active", "created_at",
        "updated_at",
    },
    "phrase_library_mutation_requests": {
        "request_id", "operation", "payload_hash", "result_json", "created_at",
    },
}

DEFAULT_CATEGORIES = (
    ("phrase-category-initial", "initial_consultation", "初次咨询", 0),
    ("phrase-category-kickoff", "before_kickoff", "开工前", 1),
    ("phrase-category-completion", "after_completion", "完工后", 2),
)

REQUIRED_INDEXES = {
    "ix_phrase_categories_category_key",
    "ix_phrase_categories_source",
    "ix_phrase_categories_active",
    "ix_phrase_snippets_category_id",
    "ix_phrase_snippets_active",
    "idx_phrase_snippets_category_position",
    "ix_phrase_library_mutation_requests_operation",
    "ix_phrase_library_mutation_requests_created_at",
}


def _state(bind) -> tuple[set[str], dict[str, set[str]]]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in TABLE_COLUMNS
        if table in tables
    }
    return tables, columns


def _validate_defaults(bind) -> None:
    rows = {
        str(row[0]): (str(row[1]), int(row[2]), bool(row[3]))
        for row in bind.execute(
            sa.text(
                "SELECT category_key, name, position, active FROM phrase_categories "
                "WHERE source = 'default'"
            )
        )
    }
    expected = {row[1]: (row[2], row[3], True) for row in DEFAULT_CATEGORIES}
    if any(rows.get(key) != value for key, value in expected.items()):
        raise RuntimeError(
            "phrase library schema is partial; default categories differ"
        )
    state = bind.execute(
        sa.text("SELECT revision FROM phrase_library_states WHERE id = 'global'")
    ).first()
    if state is None:
        raise RuntimeError(
            "phrase library schema is partial; missing global revision state"
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables, columns = _state(bind)
    present = set(TABLE_COLUMNS).intersection(tables)
    if present == set(TABLE_COLUMNS):
        incomplete = {
            table: sorted(required - columns.get(table, set()))
            for table, required in TABLE_COLUMNS.items()
            if required - columns.get(table, set())
        }
        if incomplete:
            detail = "; ".join(
                f"{table} missing {', '.join(missing)}"
                for table, missing in sorted(incomplete.items())
            )
            raise RuntimeError(
                "phrase library schema is partial; refusing silent repair " + detail
            )
        inspector = sa.inspect(bind)
        indexes = {
            index["name"]
            for table in ("phrase_categories", "phrase_snippets", "phrase_library_mutation_requests")
            for index in inspector.get_indexes(table)
        }
        missing_indexes = REQUIRED_INDEXES - indexes
        if missing_indexes:
            raise RuntimeError(
                "phrase library schema is partial; missing indexes: "
                + ", ".join(sorted(missing_indexes))
            )
        _validate_defaults(bind)
        return
    if present:
        raise RuntimeError(
            "phrase library schema is partial; missing tables: "
            + ", ".join(sorted(set(TABLE_COLUMNS) - present))
        )

    op.create_table(
        "phrase_library_states",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "phrase_categories",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("category_key", sa.String(128), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="custom"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("category_key", name="uq_phrase_categories_category_key"),
    )
    op.create_index("ix_phrase_categories_category_key", "phrase_categories", ["category_key"], unique=True)
    op.create_index("ix_phrase_categories_source", "phrase_categories", ["source"])
    op.create_index("ix_phrase_categories_active", "phrase_categories", ["active"])
    op.create_table(
        "phrase_snippets",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column(
            "category_id",
            sa.String(128),
            sa.ForeignKey("phrase_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_phrase_snippets_category_id", "phrase_snippets", ["category_id"])
    op.create_index("ix_phrase_snippets_active", "phrase_snippets", ["active"])
    op.create_index(
        "idx_phrase_snippets_category_position",
        "phrase_snippets",
        ["category_id", "position", "created_at"],
    )
    op.create_table(
        "phrase_library_mutation_requests",
        sa.Column("request_id", sa.String(128), primary_key=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_phrase_library_mutation_requests_operation",
        "phrase_library_mutation_requests",
        ["operation"],
    )
    op.create_index(
        "ix_phrase_library_mutation_requests_created_at",
        "phrase_library_mutation_requests",
        ["created_at"],
    )

    bind.execute(
        sa.text(
            "INSERT INTO phrase_library_states "
            "(id, revision, created_at, updated_at) "
            "VALUES ('global', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    for category_id, category_key, name, position in DEFAULT_CATEGORIES:
        bind.execute(
            sa.text(
                "INSERT INTO phrase_categories "
                "(id, category_key, name, source, position, active, created_at, updated_at) "
                "VALUES (:id, :category_key, :name, 'default', :position, 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": category_id,
                "category_key": category_key,
                "name": name,
                "position": position,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_phrase_library_mutation_requests_created_at",
        table_name="phrase_library_mutation_requests",
    )
    op.drop_index(
        "ix_phrase_library_mutation_requests_operation",
        table_name="phrase_library_mutation_requests",
    )
    op.drop_table("phrase_library_mutation_requests")
    op.drop_index("idx_phrase_snippets_category_position", table_name="phrase_snippets")
    op.drop_index("ix_phrase_snippets_active", table_name="phrase_snippets")
    op.drop_index("ix_phrase_snippets_category_id", table_name="phrase_snippets")
    op.drop_table("phrase_snippets")
    op.drop_index("ix_phrase_categories_active", table_name="phrase_categories")
    op.drop_index("ix_phrase_categories_source", table_name="phrase_categories")
    op.drop_index("ix_phrase_categories_category_key", table_name="phrase_categories")
    op.drop_table("phrase_categories")
    op.drop_table("phrase_library_states")
