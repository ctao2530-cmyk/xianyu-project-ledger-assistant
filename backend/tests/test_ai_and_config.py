from __future__ import annotations

import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.ai import (
    AIInput,
    AIModelSelection,
    AIResult,
    ChatContextMessage,
    CodexCliProvider,
    ProductContext,
)
from backend.app.services.risk import detect_risks


def test_automatic_send_is_always_disabled() -> None:
    settings = Settings(_env_file=None)
    assert settings.automatic_sending_enabled is False


def test_customer_message_ai_workbenches_are_paused_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.customer_reply_drafts_enabled is False
    assert settings.customer_quote_conversion_enabled is False


def test_codex_json_extraction_and_fixed_result() -> None:
    parsed = CodexCliProvider._extract_json(
        """结果如下：```json
        {"direct":"可以，请先发具体需求、截止时间和参考资料，我看完后回复。",
         "friendly":"您好，可以先把功能需求、期望时间和参考案例发来，我帮您确认。",
         "conversion":"把需求文档、截止时间和参考资料发我，确认范围后再继续沟通。",
         "risk_level":"low","risk_reasons":[],"needs_human_confirmation":true}
        ```"""
    )
    result = AIResult.model_validate(parsed)
    assert result.needs_human_confirmation is True
    assert len(result.drafts()) == 3


def test_codex_model_catalog_filters_internal_aliases() -> None:
    options = CodexCliProvider._parse_model_catalog(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.6-terra",
                        "display_name": "GPT-5.6-Terra",
                        "visibility": "list",
                        "default_reasoning_level": "medium",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "medium"},
                            {"effort": "high"},
                        ],
                    },
                    {
                        "slug": "codex-auto-review",
                        "display_name": "Internal alias",
                        "visibility": "list",
                        "supported_reasoning_levels": [{"effort": "medium"}],
                    },
                ]
            }
        )
    )

    assert [option.model for option in options] == ["gpt-5.6-terra"]
    assert options[0].default_reasoning_effort == "medium"
    assert options[0].supported_reasoning_efforts == ("low", "medium", "high")


def test_codex_command_uses_runtime_model_selection() -> None:
    provider = CodexCliProvider(Settings(_env_file=None))
    provider._command_path = "/usr/local/bin/codex"
    provider.configure_model(
        AIModelSelection(model="gpt-5.5", reasoning_effort="high")
    )

    args = provider._command_args(
        Path("/tmp/work"),
        Path("/tmp/schema.json"),
        Path("/tmp/output.json"),
    )

    assert args[args.index("--model") + 1] == "gpt-5.5"
    assert 'model_reasoning_effort="high"' in args


def test_codex_command_allows_per_task_model_without_mutating_reply_model() -> None:
    provider = CodexCliProvider(Settings(_env_file=None))
    provider._command_path = "/usr/local/bin/codex"
    provider.configure_model(
        AIModelSelection(model="gpt-5.5", reasoning_effort="low")
    )

    args = provider._command_args(
        Path("/tmp/work"),
        Path("/tmp/schema.json"),
        Path("/tmp/output.json"),
        model_selection=AIModelSelection(
            model="gpt-5.6-sol", reasoning_effort="max"
        ),
    )

    assert args[args.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="max"' in args
    assert provider.model_selection.model == "gpt-5.5"


def test_sensitive_topics_are_flagged() -> None:
    flags = detect_risks("请给我手机号和账号密码，退款后明天交付，报价 500 元")
    assert set(flags) == {
        "报价需确认",
        "退款需确认",
        "账号密码需确认",
        "联系方式需确认",
        "交付时间需确认",
    }


def test_static_product_price_does_not_make_safe_current_turn_high_risk() -> None:
    source = AIInput(
        customer_message="你好，可以先了解一下需求吗",
        product=ProductContext(
            title="网页制作服务",
            price="¥500",
            description="根据需求沟通制作范围",
        ),
        recent_messages=[
            ChatContextMessage(
                direction="seller",
                content="商品页面已有参考价格",
                time="2026-08-03T08:00:00+08:00",
            )
        ],
        seller_rules=[],
        current_time="2026-08-03T09:00:00+08:00",
    )
    result = AIResult(
        direct="您好，可以先把具体功能和参考资料发来，我先帮您梳理需求。",
        friendly="可以的，您把想做的内容和参考案例发来，我们先把需求沟通清楚。",
        conversion="请先发一下具体功能和参考资料，我确认需求范围后再为您说明下一步。",
        risk_level="low",
        risk_reasons=[],
        needs_human_confirmation=True,
    ).with_enforced_risks(source)

    assert result.risk_level == "low"
    assert result.risk_reasons == []
