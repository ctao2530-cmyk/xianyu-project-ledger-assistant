from backend.app.ai import AIModelSelection
from backend.app.config import Settings
from backend.app.database import Database
from backend.app.services.reply_strategy import ReplyStrategyService


def test_reply_strategy_persists_mode_and_resolves_profiles(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'reply-strategy.db'}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        reply_speed_mode="balanced",
        reply_fast_model="gpt-5.4-mini",
        reply_balanced_model="gpt-5.5",
        reply_quality_model="gpt-5.6-sol",
    )
    service = ReplyStrategyService(database, settings, "codex_cli")

    balanced = service.resolve(
        base_selection=AIModelSelection(model="custom-model", reasoning_effort="high"),
        has_local_risk=False,
    )
    assert balanced.mode == "balanced"
    assert balanced.model_selection.model == "gpt-5.5"
    assert balanced.context_messages == settings.reply_balanced_context_messages

    service.set_mode("fast")
    restarted = ReplyStrategyService(database, settings, "codex_cli")
    assert restarted.mode == "fast"
    assert restarted.resolve(
        base_selection=AIModelSelection(), has_local_risk=False
    ).model_selection.model == "gpt-5.4-mini"


def test_high_risk_always_uses_quality_profile(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'reply-risk.db'}")
    database.create_all()
    settings = Settings(
        _env_file=None,
        reply_speed_mode="fast",
        reply_quality_model="gpt-5.6-sol",
    )
    service = ReplyStrategyService(database, settings, "codex_cli")

    resolved = service.resolve(
        base_selection=AIModelSelection(model="gpt-5.4-mini", reasoning_effort="low"),
        has_local_risk=True,
    )

    assert resolved.mode == "quality"
    assert resolved.model_selection.model == "gpt-5.6-sol"
    assert resolved.escalated_for_risk is True
