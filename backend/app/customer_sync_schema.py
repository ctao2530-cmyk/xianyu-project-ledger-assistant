"""Frozen additive 0046 definition, shared by startup and Alembic."""
from sqlalchemy import inspect

TABLES = {
    'customer_context_sync_states': '''id VARCHAR(64) PRIMARY KEY NOT NULL, scope_json TEXT NOT NULL,
        revision INTEGER NOT NULL, text_version INTEGER NOT NULL, image_version INTEGER NOT NULL,
        text_watermark INTEGER NOT NULL, summary_watermark INTEGER NOT NULL, summary_version INTEGER NOT NULL,
        summary_json TEXT NOT NULL, summary_source TEXT NOT NULL, image_versions_json TEXT NOT NULL,
        last_text_grant VARCHAR(128) NOT NULL, last_image_grant VARCHAR(128) NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL''',
    'customer_context_read_batches': '''id VARCHAR(128) PRIMARY KEY NOT NULL,
        state_id VARCHAR(64) NOT NULL REFERENCES customer_context_sync_states(id), kind VARCHAR(16) NOT NULL,
        base_version INTEGER NOT NULL, status VARCHAR(16) NOT NULL, grant_id VARCHAR(128) NOT NULL,
        payload_json TEXT NOT NULL, image_reads_json TEXT NOT NULL, confirmation_hash VARCHAR(64) NOT NULL,
        summary_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at DATETIME NOT NULL, confirmed_at DATETIME,
        CONSTRAINT uq_customer_context_batch_version UNIQUE(state_id, kind, base_version)''',
}
EXPECTED = {
    'customer_context_sync_states': 'id scope_json revision text_version image_version text_watermark summary_watermark summary_version summary_json summary_source image_versions_json last_text_grant last_image_grant created_at updated_at',
    'customer_context_read_batches': 'id state_id kind base_version status grant_id payload_json image_reads_json confirmation_hash summary_json result_json created_at confirmed_at',
}


def validate_customer_sync_schema(connection):
    inspector = inspect(connection)
    found = set(inspector.get_table_names()).intersection(TABLES)
    if not found:
        return False
    if found != set(TABLES):
        raise RuntimeError('customer sync 0046 incomplete tables')
    for table, columns in EXPECTED.items():
        actual = {c['name']: c for c in inspector.get_columns(table)}
        if not set(columns.split()) <= set(actual):
            raise RuntimeError('customer sync 0046 incomplete columns')
        integer_columns = {'revision', 'text_version', 'image_version', 'text_watermark',
                           'summary_watermark', 'summary_version', 'base_version'}
        for name in columns.split():
            if actual[name]['nullable'] != (name == 'confirmed_at'):
                raise RuntimeError('customer sync 0046 invalid nullability')
            sql_type = str(actual[name]['type']).upper()
            expected_type = 'INT' if name in integer_columns else 'DATE' if name.endswith('_at') else ('CHAR', 'TEXT')
            if not any(t in sql_type for t in (expected_type if isinstance(expected_type, tuple) else (expected_type,))):
                raise RuntimeError('customer sync 0046 invalid column type')
        if inspector.get_pk_constraint(table)['constrained_columns'] != ['id']:
            raise RuntimeError('customer sync 0046 incomplete primary key')
    fks = inspector.get_foreign_keys('customer_context_read_batches')
    if not any(f['constrained_columns'] == ['state_id'] and f['referred_table'] == 'customer_context_sync_states' and f['referred_columns'] == ['id'] for f in fks):
        raise RuntimeError('customer sync 0046 incomplete foreign key')
    if not any(c['column_names'] == ['state_id','kind','base_version'] for c in inspector.get_unique_constraints('customer_context_read_batches')):
        raise RuntimeError('customer sync 0046 incomplete unique constraint')
    return True


def migrate_customer_sync_schema(connection):
    if validate_customer_sync_schema(connection):
        return
    for table, definition in TABLES.items():
        connection.exec_driver_sql(f'CREATE TABLE {table} ({definition})')
    connection.exec_driver_sql('CREATE INDEX ix_customer_context_read_batches_state_id ON customer_context_read_batches(state_id)')
    validate_customer_sync_schema(connection)
