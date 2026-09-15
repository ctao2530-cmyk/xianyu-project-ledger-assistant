"""Published MCP schemas; validate payloads only after the customer grant check."""
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, WithJsonSchema

from .global_agent_schemas import AgentExecutionPlan, AgentRequirementBlueprint
from .requirement_blueprints import EvidenceReference, RequirementBlueprintV2


class BlueprintConversion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    project_type: str = Field(min_length=2, max_length=120)
    stage_mapping: dict[str, str] = Field(description='蓝图阶段 ID → 执行计划阶段 ID，必须完整一一对应')
    implementations: dict[str, str] = Field(description='蓝图阶段 ID → 明确实现说明，不根据标题猜测')
    evidence_refs: list[EvidenceReference] = Field(description='真实授权消息 message_id / 图片 archive_id；导出序号不能代替消息 ID')
    evidence_mapping: dict[str, str] | None = Field(default=None, description='原证据 ID → evidence_refs 中的 ID')


def inline_schema(model):
    """Avoid nested $defs colliding with FastMCP's enclosing arguments schema."""
    schema = model.model_json_schema()
    definitions = schema.pop('$defs', {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            if '$ref' in value:
                return expand(definitions[value['$ref'].rsplit('/', 1)[1]])
            return {key: expand(item) for key, item in value.items()}
        return value

    return expand(schema)


DocumentInput = Annotated[dict[str, Any], WithJsonSchema(inline_schema(RequirementBlueprintV2))]
AgentBlueprintInput = Annotated[dict[str, Any], WithJsonSchema(inline_schema(AgentRequirementBlueprint))]
ExecutionPlanInput = Annotated[dict[str, Any], WithJsonSchema(inline_schema(AgentExecutionPlan))]
ConversionInput = Annotated[dict[str, Any], WithJsonSchema(inline_schema(BlueprintConversion))]


def safe_validation_issues(exc: ValidationError, root: str):
    # Never include Pydantic input, ctx, msg (custom validators can embed values),
    # or caller-controlled dictionary keys / unexpected field names.
    schemas = [inline_schema(m) for m in (RequirementBlueprintV2, AgentRequirementBlueprint,
                                         AgentExecutionPlan, BlueprintConversion)]
    fields = set()

    def collect(value):
        if isinstance(value, dict):
            fields.update(value.get('properties', {}))
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    collect(schemas)
    reasons = {'missing': '缺少必填字段', 'extra_forbidden': '存在不支持的字段',
               'value_error': '节点 ID、引用或依赖关系不合法，请核对唯一性、引用和依赖环'}
    return [{'path': [root, *[part if isinstance(part, int) or part in fields else '<key>'
                              for part in error['loc']]],
             'type': error['type'],
             'reason': reasons.get(error['type'], '字段类型、取值或长度不符合工具声明的 schema')}
            for error in exc.errors(include_input=False, include_context=False, include_url=False)[:20]]
