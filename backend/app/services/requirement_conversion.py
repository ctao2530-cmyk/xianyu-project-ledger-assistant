"""Explicit ID-based conversion; never infer dependencies from titles."""
from ..global_agent_schemas import AgentRequirementBlueprint, AgentExecutionPlan
from ..requirement_blueprints import RequirementBlueprintV2


def convert_agent_blueprint(blueprint, execution_plan, *, project_type, stage_mapping,
                            implementations, evidence_refs, evidence_mapping=None):
    source = AgentRequirementBlueprint.model_validate(blueprint)
    plan = AgentExecutionPlan.model_validate(execution_plan)
    by_id = {s.id: s for s in plan.stages}
    if set(stage_mapping) != {s.id for s in source.stages} or set(stage_mapping.values()) != set(by_id) or len(set(stage_mapping.values())) != len(stage_mapping):
        raise ValueError('必须逐项显式映射蓝图阶段与执行阶段 ID')
    task_to_stage = {by_id[pid].task_key: sid for sid, pid in stage_mapping.items()}
    result = source.model_dump(exclude={'maturity'})
    result.update(schema_version='2.0', readiness=source.maturity, project_type=project_type,
                  change_summary=plan.change_summary, evidence_refs=evidence_refs)
    for stage in result['stages']:
        work = by_id[stage_mapping[stage['id']]]
        dependencies = [task_to_stage[key] for key in work.dependency_task_keys]
        if set(dependencies) != set(stage['dependency_ids']):
            raise ValueError('蓝图阶段依赖与执行计划依赖不一致')
        if not stage['estimated_hours'] or stage['id'] not in implementations:
            raise ValueError('每个阶段必须明确工时和 implementation，不自动猜测')
        stage.update(task_key=work.task_key, workspace_key=work.workspace_key,
            implementation=implementations[stage['id']], deliverables=work.deliverables,
            work_items=list(dict.fromkeys(stage['work_items'] + work.allowed_changes)),
            process_tests=work.process_tests, allowed_changes=work.allowed_changes,
            stop_conditions=work.stop_conditions)
        stage['evidence_refs'] = list(dict.fromkeys(stage['evidence_refs'] + work.evidence_refs))
        matching = [gate for gate in result['acceptance_gates'] if stage['id'] in gate['stage_ids']]
        if not matching:
            raise ValueError('执行阶段缺少对应交付验收门')
        matching[0]['criteria'] = list(dict.fromkeys(matching[0]['criteria'] + work.acceptance_criteria))
    for key in ('out_of_scope', 'assumptions', 'open_questions'):
        result[key] = list(dict.fromkeys(result[key] + getattr(plan, key)))
    result['out_of_scope'] = list(dict.fromkeys(result['out_of_scope'] + plan.must_not_change))
    risks = {r['id']: r for r in result['risks']}
    for risk in plan.risks:
        value = risk.model_dump()
        if risk.id in risks and risks[risk.id] != value:
            raise ValueError('相同风险 ID 内容冲突，需显式统一')
        risks[risk.id] = value
    result['risks'] = list(risks.values())
    for kind in ('objectives', 'capabilities', 'stages', 'acceptance_gates', 'risks'):
        for node in result[kind]:
            node['evidence_refs'] = [(evidence_mapping or {}).get(ref, ref) for ref in node['evidence_refs']]
    return RequirementBlueprintV2.model_validate(result)


def blueprint_diff(previous, current):
    result = {}
    for kind in ('objectives', 'capabilities', 'stages', 'acceptance_gates', 'risks'):
        old = {r['id']: r for r in previous.get(kind, [])}
        new = {r['id']: r for r in current.get(kind, [])}
        result[kind] = {label: [] for label in ('added', 'modified', 'removal_proposed', 'unchanged')}
        for key in dict.fromkeys([*old, *new]):
            label = 'added' if key not in old else 'removal_proposed' if key not in new else 'unchanged' if old[key] == new[key] else 'modified'
            result[kind][label].append({'id': key, 'before': old.get(key), 'after': new.get(key)})
    return result
