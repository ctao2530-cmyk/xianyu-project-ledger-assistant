"""Append-only operator-recorded customer outcomes, separate from task completion.
Uses the existing transaction/audit ledger; no schema or implicit business transition.
"""
import hashlib
import json
from sqlalchemy import select, text, func
from ..models import RequirementCase, RequirementDocumentVersion, BusinessProject, LedgerMutationRequest, utcnow
from ..ledger import LedgerService, RevisionConflict

OPERATION = 'project_customer_acceptance'

class AcceptanceError(ValueError):
    pass

class ProjectAcceptanceService:
    def __init__(self, database, ledger):
        self.database, self.ledger = database, ledger

    def history(self, project_id, *, limit=20, offset=0):
        with self.database.session() as s:
            if not s.get(BusinessProject, project_id):
                raise AcceptanceError('项目不存在')
            revision, _ = self.ledger.get_in_session(s)
            query = select(LedgerMutationRequest).where(LedgerMutationRequest.operation == OPERATION,
                func.json_extract(LedgerMutationRequest.result_json, '$.project_id') == project_id)
            rows = s.scalars(query.order_by(LedgerMutationRequest.created_at.desc(), LedgerMutationRequest.request_id.desc()).offset(offset).limit(limit+1)).all()
            return {'revision': revision, 'items': [json.loads(r.result_json) for r in rows[:limit]], 'has_more': len(rows)>limit}

    def record(self, project_id, payload):
        if not payload['confirmed']:
            raise AcceptanceError('请明确确认录入客户结论')
        identity = {'project_id': project_id, **payload}
        digest = hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.database.session() as s:
            s.execute(text('BEGIN IMMEDIATE'))
            old = s.get(LedgerMutationRequest, payload['request_id'])
            if old:
                if old.operation != OPERATION or old.payload_hash != digest:
                    raise AcceptanceError('请求编号已用于其他内容')
                return json.loads(old.result_json)
            revision, snapshot = self.ledger.get_in_session(s)
            if revision != payload['expected_revision']:
                raise RevisionConflict(revision)
            project = s.get(BusinessProject, project_id)
            case = s.get(RequirementCase, payload['case_id'])
            if not project or not case or case.project_id != project_id or case.customer_id != project.customer_id:
                raise AcceptanceError('验收需求必须属于项目当前关联客户与项目')
            if case.current_version != payload['version']:
                raise AcceptanceError('正式需求版本已变化，请刷新后记录')
            version = s.scalar(select(RequirementDocumentVersion).where(RequirementDocumentVersion.case_id==case.id, RequirementDocumentVersion.version==payload['version']))
            if not version:
                raise AcceptanceError('正式需求版本不存在')
            revision, _ = self.ledger.save_in_session(s, snapshot, revision)
            result = {k: payload[k] for k in ('request_id','case_id','version','decision','reviewer','evidence')}
            result.update(project_id=project_id, revision=revision, recorded_at=utcnow().isoformat(),
                          evidence_kind='operator_recorded', document_sha256=hashlib.sha256(version.structured_json.encode()).hexdigest())
            s.add(LedgerMutationRequest(request_id=payload['request_id'], operation=OPERATION, payload_hash=digest,
                                       result_json=json.dumps(result,ensure_ascii=False)))
            s.commit()
            return result
