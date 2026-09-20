from copy import deepcopy

from backend.app.ai.codex_cli import codex_output_schema
from backend.app.global_agent_schemas import AgentModelAnswer


def test_agent_schema_recursively_requires_all_closed_properties_without_mutation():
    source = AgentModelAnswer.model_json_schema()
    before = deepcopy(source)
    strict = codex_output_schema(source)
    assert source == before
    assert "goals" in strict["$defs"]["AgentCustomerConversationSummary"]["required"]
    assert {"type": "null"} in strict["properties"]["updated_customer_context"]["anyOf"]
    count = 0

    def walk(node):
        nonlocal count
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
                count += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(strict)
    assert count > 10


def test_open_dictionary_values_are_not_discarded():
    schema = {"type": "object", "additionalProperties": {"type": "number"}}
    assert codex_output_schema(schema) == schema
