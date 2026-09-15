"""Frozen 0045 additive schema, shared by Alembic and startup validation.

No runtime model imports: historical migration meaning cannot drift with ORM edits.
"""
from sqlalchemy import inspect

TABLES = {
    "customer_image_capture_jobs": """archive_id VARCHAR PRIMARY KEY NOT NULL REFERENCES customer_image_archives(id),
        encrypted_media TEXT NOT NULL, status VARCHAR(32) NOT NULL, attempt_count INTEGER NOT NULL,
        next_attempt_at DATETIME, lease_until DATETIME, last_error VARCHAR(64),
        source_item_id INTEGER REFERENCES items(id), source_item_external_id VARCHAR(128), updated_at DATETIME NOT NULL""",
    "customer_conversation_groups": """id VARCHAR(128) PRIMARY KEY NOT NULL, customer_id VARCHAR NOT NULL REFERENCES business_customers(id),
        revision INTEGER NOT NULL, status VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL""",
    "customer_conversation_group_members": """group_id VARCHAR NOT NULL REFERENCES customer_conversation_groups(id),
        conversation_id INTEGER NOT NULL REFERENCES conversations(id), active BOOLEAN NOT NULL, updated_at DATETIME NOT NULL,
        PRIMARY KEY(group_id, conversation_id)""",
    "customer_conversation_group_previews": """token_hash VARCHAR(64) PRIMARY KEY NOT NULL,
        payload_hash VARCHAR(64) NOT NULL, expires_at DATETIME NOT NULL""",
    "customer_conversation_group_mutations": """request_id VARCHAR(128) PRIMARY KEY NOT NULL,
        group_id VARCHAR NOT NULL REFERENCES customer_conversation_groups(id), payload_hash VARCHAR(64) NOT NULL,
        reason TEXT NOT NULL, before_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at DATETIME NOT NULL""",
    "customer_context_group_scopes": """grant_id VARCHAR PRIMARY KEY NOT NULL REFERENCES customer_context_grants(id),
        group_id VARCHAR NOT NULL REFERENCES customer_conversation_groups(id), group_revision INTEGER NOT NULL,
        conversation_ids_json TEXT NOT NULL, created_at DATETIME NOT NULL""",
}
EXPECTED = {
    "customer_image_capture_jobs": "archive_id encrypted_media status attempt_count next_attempt_at lease_until last_error source_item_id source_item_external_id updated_at",
    "customer_conversation_groups": "id customer_id revision status created_at updated_at",
    "customer_conversation_group_members": "group_id conversation_id active updated_at",
    "customer_conversation_group_previews": "token_hash payload_hash expires_at",
    "customer_conversation_group_mutations": "request_id group_id payload_hash reason before_json result_json created_at",
    "customer_context_group_scopes": "grant_id group_id group_revision conversation_ids_json created_at",
}
PRIMARY = {name: [cols.split()[0]] for name, cols in EXPECTED.items()}
PRIMARY["customer_conversation_group_members"] = ["group_id", "conversation_id"]
FOREIGN = {
    "customer_image_capture_jobs": {("archive_id", "customer_image_archives", "id"), ("source_item_id", "items", "id")},
    "customer_conversation_groups": {("customer_id", "business_customers", "id")},
    "customer_conversation_group_members": {("group_id", "customer_conversation_groups", "id"), ("conversation_id", "conversations", "id")},
    "customer_conversation_group_previews": set(),
    "customer_conversation_group_mutations": {("group_id", "customer_conversation_groups", "id")},
    "customer_context_group_scopes": {("grant_id", "customer_context_grants", "id"), ("group_id", "customer_conversation_groups", "id")},
}
INDEXES = {
    "customer_image_capture_jobs": ["status"],
    "customer_conversation_groups": ["customer_id"],
    "customer_conversation_group_mutations": ["group_id"],
    "customer_context_group_scopes": ["group_id"],
}


def validate_customer_workflow_schema(connection):
    inspector = inspect(connection)
    names = set(inspector.get_table_names())
    found = names.intersection(TABLES)
    message_columns = {c["name"] for c in inspector.get_columns("messages")} if "messages" in names else set()
    has_source = "source_item_external_id" in message_columns
    if not found and not has_source:
        return False
    if found != set(TABLES) or not has_source:
        raise RuntimeError("customer workflow 0045 schema is incomplete; refusing partial migration")
    for table, expected in EXPECTED.items():
        if not set(expected.split()) <= {c["name"] for c in inspector.get_columns(table)}:
            raise RuntimeError(f"customer workflow 0045 schema is incomplete: {table} columns")
        if inspector.get_pk_constraint(table).get("constrained_columns") != PRIMARY[table]:
            raise RuntimeError(f"customer workflow 0045 schema is incomplete: {table} primary key")
        foreign = {(f["constrained_columns"][0], f["referred_table"], f["referred_columns"][0]) for f in inspector.get_foreign_keys(table)}
        if not FOREIGN[table] <= foreign:
            raise RuntimeError(f"customer workflow 0045 schema is incomplete: {table} foreign keys")
    return True


def migrate_customer_workflow_schema(connection):
    if validate_customer_workflow_schema(connection):
        return
    if "messages" not in inspect(connection).get_table_names():
        return  # Empty startup: Base.metadata creates everything, then verifies.
    connection.exec_driver_sql("ALTER TABLE messages ADD COLUMN source_item_external_id VARCHAR(128)")
    for name, columns in TABLES.items():
        connection.exec_driver_sql(f"CREATE TABLE {name} ({columns})")
    for table, columns in INDEXES.items():
        for column in columns:
            connection.exec_driver_sql(f"CREATE INDEX ix_{table}_{column} ON {table}({column})")
    validate_customer_workflow_schema(connection)
