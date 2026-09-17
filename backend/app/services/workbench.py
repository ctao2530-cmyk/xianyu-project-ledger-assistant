"""SQLite-only projection of existing facts. No alternative business ownership."""
from datetime import datetime, timezone
from urllib.parse import quote
from sqlalchemy import text

# Read safe scalar metadata only. Never return proposal tokens or message contents.
ACTIONS = """
WITH cases AS (
 SELECT c.id, c.customer_id, c.title, c.status, c.updated_at,
 CASE WHEN json_valid(v.structured_json) AND json_type(v.structured_json, '$.open_questions') = 'array'
 THEN json_array_length(v.structured_json, '$.open_questions') ELSE 0 END questions
 FROM requirement_cases c JOIN business_customers b ON b.id=c.customer_id
 LEFT JOIN requirement_document_versions v ON v.case_id=c.id AND v.version=c.current_version
), proposals AS (
 SELECT json_extract(result_json, '$.customer_id') customer_id, count(*) count,
 max(created_at) updated_at
 FROM ledger_mutation_requests
 WHERE operation='requirement_gpt_proposal' AND json_valid(result_json)
 AND json_extract(result_json, '$.result') IS NULL
 AND julianday(json_extract(result_json, '$.expires_at')) > julianday(:now)
 GROUP BY json_extract(result_json, '$.customer_id')
), actions AS (
 SELECT 'conversation-' || id id, '客户消息' category, customer_name title,
 unread_count || ' 条未读消息' detail, last_message_at updated_at,
 '客户消息/conversation/' || id target
 FROM conversations WHERE unread_count>0
 UNION ALL
 SELECT CASE WHEN questions>0 THEN 'questions-' ELSE 'requirement-' END || id,
 CASE WHEN questions>0 THEN '待补资料' ELSE '待确认需求' END, title,
 CASE WHEN questions>0 THEN questions || ' 项待确认问题' ELSE '正式需求尚未确认' END,
 updated_at, '客户管理/' || customer_id || '/requirements/' || id
 FROM cases WHERE questions>0 OR status IN ('discovery','clarifying','ready')
 UNION ALL
 SELECT 'proposals-' || b.id, '待确认需求', b.name, p.count || ' 份 GPT 拟写入提案',
 p.updated_at, '客户管理/' || b.id || '/requirements'
 FROM proposals p JOIN business_customers b ON b.id=p.customer_id
)
"""

def aware_time(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()

class WorkbenchQuery:
    def __init__(self, database):
        self.database = database

    def page(self, *, offset=0, limit=100):
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError('invalid workbench page')
        now = datetime.now(timezone.utc).isoformat()
        with self.database.session() as session:
            # Explicit SQLite read transaction keeps page and total on one snapshot.
            session.execute(text('BEGIN'))
            total = session.scalar(text(ACTIONS + 'SELECT count(*) FROM actions'), {'now': now})
            rows = session.execute(text(ACTIONS + '''SELECT * FROM actions
                ORDER BY julianday(updated_at) DESC, id ASC LIMIT :limit OFFSET :offset'''),
                {'now': now, 'offset': offset, 'limit': limit}).mappings().all()
        items = [dict(id=r['id'], category=r['category'], title=r['title'], detail=r['detail'],
                      updatedAt=aware_time(r['updated_at']), href='#'+quote(r['target'], safe='')) for r in rows]
        return {'items': items, 'total': total, 'offset': offset, 'hasMore': offset+len(items)<total, 'asOf': now}
