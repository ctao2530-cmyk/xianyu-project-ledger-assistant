from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agents import SalesAgent
from .ai import (
    AIModelSelection,
    AIProvider,
    CodexCliProvider,
    DeepSeekProvider,
    OpenAICompatibleProvider,
    build_ai_provider,
)
from .agents.global_agent import (
    GlobalAgentBusinessTools,
    GlobalAgentRAG,
    GlobalAgentService,
)
from .adapters import XianyuAdapter
from .channels.base import ChannelSender, ChannelSenderRegistry
from .channels.wechat import WeChatAdapter, WechatMockProvider, WechatSender
from .channels.wecom import WeComAPIClient, WeComSender
from .channels.xianyu import XianyuSender
from .config import Settings
from .database import Database
from .ledger import LedgerService
from .prediction import PredictionService
from .prediction.calibration_service import EstimateCalibrationService
from .rate_limit import SlidingWindowRateLimiter
from .services.actions import HumanActions
from .services.ai_queue import AIJobQueue
from .services.ai_models import AIModelSettingsService
from .services.automation import AutoReplyService
from .services.business_analysis import BusinessAnalysisService
from .services.business_recommendations import BusinessRecommendationService
from .services.connection_recovery import ConnectionRecoveryService
from .services.codex_plans import CodexPlanService
from .services.codex_sync import CodexSyncService
from .services.codex_development import CodexDevelopmentService
from .services.codex_verification import CodexVerificationService
from .services.project_outcomes import ProjectOutcomeService
from .services.project_sample_formation import ProjectSampleFormationService
from .services.project_progress import ProjectProgressService
from .services.codex_runtime import AppServerDevelopmentRuntime, WorktreeManager
from .services.conversation_history_import import ConversationHistoryImportService
from .services.customer_relationships import CustomerRelationshipService
from .services.customer_intake import CustomerIntakeService
from .services.customer_images import CustomerImageArchiveService
from .services.event_hub import EventHub
from .services.listener import ListenerService
from .services.listener_state import ListenerStateTracker
from .services.listener_supervisor import ListenerSupervisor
from .services.notifier import MacOSNotifier
from .services.processor import MessageProcessor
from .services.product_intelligence import ProductIntelligenceService
from .services.phrase_library import PhraseLibraryService
from .services.traffic_growth import TrafficGrowthService
from .services.project_product_attribution import ProjectProductAttributionService
from .services.requirements import RequirementAnalysisService
from .services.requirement_exchange import RequirementExchangeService
from .services.requirement_materials import RequirementMaterialsService
from .services.reply_strategy import ReplyStrategyService
from .services.status import RuntimeStatus
from .services.style_learning import StyleLearningService
from .services.wecom import WeComService


@dataclass(slots=True)
class Runtime:
    settings: Settings
    database: Database
    adapter: XianyuAdapter
    wechat_adapter: WeChatAdapter
    wechat_sender: ChannelSender
    wecom: WeComService
    channel_senders: ChannelSenderRegistry
    ai: AIProvider
    deepseek: DeepSeekProvider
    ai_models: AIModelSettingsService
    reply_strategy: ReplyStrategyService
    style_learning: StyleLearningService
    ai_queue: AIJobQueue
    event_hub: EventHub
    notifier: MacOSNotifier
    status: RuntimeStatus
    processor: MessageProcessor
    listener: ListenerService
    listener_state: ListenerStateTracker
    listener_supervisor: ListenerSupervisor
    actions: HumanActions
    automation: AutoReplyService
    requirements: RequirementAnalysisService
    requirement_exchange: RequirementExchangeService
    requirement_materials: RequirementMaterialsService
    sales_agent: SalesAgent
    api_limiter: SlidingWindowRateLimiter
    send_limiter: SlidingWindowRateLimiter
    ledger: LedgerService
    product_intelligence: ProductIntelligenceService
    traffic_growth: TrafficGrowthService
    business_analysis: BusinessAnalysisService
    business_recommendations: BusinessRecommendationService
    predictions: PredictionService
    estimate_calibration: EstimateCalibrationService
    sample_formation: ProjectSampleFormationService
    customer_relationships: CustomerRelationshipService
    customer_intake: CustomerIntakeService
    project_product_attribution: ProjectProductAttributionService
    connection_recovery: ConnectionRecoveryService
    conversation_history_import: ConversationHistoryImportService
    customer_images: CustomerImageArchiveService
    codex_plans: CodexPlanService
    codex_sync: CodexSyncService
    codex_development: CodexDevelopmentService
    codex_verification: CodexVerificationService
    global_agent: GlobalAgentService
    phrase_library: PhraseLibraryService


def build_runtime(settings: Settings) -> Runtime:
    database = Database(settings.database_url)
    database.create_all()
    ledger = LedgerService(database, settings.project_root)
    # Create the canonical empty snapshot row without touching existing reply data.
    ledger.get()
    project_outcomes = ProjectOutcomeService()
    adapter = XianyuAdapter(settings)
    wechat_adapter = WeChatAdapter(WechatMockProvider())
    wecom_client = WeComAPIClient(settings)
    wechat_sender: ChannelSender = (
        WeComSender(wecom_client)
        if settings.wechat_provider == "wecom"
        else WechatSender()
    )
    channel_senders = ChannelSenderRegistry(
        XianyuSender(adapter),
        wechat_sender,
    )
    ai = build_ai_provider(settings)
    deepseek = DeepSeekProvider(settings)
    ai_models = AIModelSettingsService(database, ai, settings)
    reply_strategy = ReplyStrategyService(database, settings, ai.name)
    style_learning = StyleLearningService(database, settings)
    style_learning.bootstrap()
    notifier = MacOSNotifier(settings.macos_notifications)
    status = RuntimeStatus()
    listener_state = ListenerStateTracker(
        database,
        status,
        retention_days=settings.listener_log_retention_days,
    )
    event_hub = EventHub()
    sales_provider = deepseek if settings.deepseek_configured else ai
    sales_model_selection = (
        AIModelSelection(model=settings.deepseek_lead_model)
        if sales_provider.name == deepseek.name
        else AIModelSelection(
            model=settings.reply_balanced_model or settings.codex_model or None,
            reasoning_effort=settings.reply_balanced_reasoning_effort or None,
        )
    )
    sales_agent = SalesAgent(
        database,
        ledger,
        sales_provider,
        model_selection=sales_model_selection,
        providers={ai.name: ai, deepseek.name: deepseek},
        model_selections={
            deepseek.name: AIModelSelection(model=settings.deepseek_lead_model),
            ai.name: AIModelSelection(
                model=settings.reply_balanced_model or settings.codex_model or None,
                reasoning_effort=settings.reply_balanced_reasoning_effort or None,
            ),
        },
        timeout_seconds=settings.sales_agent_timeout_seconds,
        event_hub=event_hub,
        history_limit=settings.sales_agent_history_limit,
    )
    product_intelligence = ProductIntelligenceService(
        database,
        adapter,
        settings,
        event_hub,
        notifier,
        ledger=ledger,
    )
    traffic_growth = TrafficGrowthService(
        database,
        settings,
        product_intelligence=product_intelligence,
    )
    product_intelligence.traffic_growth = traffic_growth
    project_progress = ProjectProgressService()
    sample_formation = ProjectSampleFormationService(
        database,
        ledger,
        event_hub,
        outcomes=project_outcomes,
        progress=project_progress,
    )
    predictions = PredictionService(database, ledger, project_outcomes)
    estimate_calibration = EstimateCalibrationService(
        database,
        project_outcomes,
        progress=project_progress,
        sample_formation=sample_formation,
    )
    business_analysis = BusinessAnalysisService(
        database,
        ledger,
        predictions=predictions,
        outcomes=project_outcomes,
        reasoning_providers={ai.name: ai, deepseek.name: deepseek},
        model_settings=ai_models,
        provider_selections={
            deepseek.name: AIModelSelection(
                model=(
                    settings.business_analysis_model.strip()
                    or settings.deepseek_lead_model
                )
            ),
        },
        provider_enabled={
            ai.name: settings.ai_configured,
            deepseek.name: settings.deepseek_configured,
        },
        reasoning_timeout_seconds=settings.business_analysis_timeout_seconds,
    )
    business_recommendations = BusinessRecommendationService(
        database,
        business_analysis,
        product_intelligence=product_intelligence,
    )
    customer_relationships = CustomerRelationshipService(database, ledger)
    customer_intake = CustomerIntakeService(database, ledger, event_hub)
    project_product_attribution = ProjectProductAttributionService(database, ledger)
    send_limiter = SlidingWindowRateLimiter(settings.send_rate_limit_per_minute)
    actions = HumanActions(database, channel_senders, style_learning)
    automation = AutoReplyService(
        database,
        actions,
        notifier,
        settings,
        status,
        send_limiter=send_limiter,
    )
    ai_queue = AIJobQueue(
        database,
        ai,
        settings,
        providers={ai.name: ai, deepseek.name: deepseek},
        automatic_provider=(deepseek.name if settings.deepseek_configured else ai.name),
        event_hub=event_hub,
        on_completed=automation.handle_completed,
        style_learning=style_learning,
        reply_strategy=reply_strategy,
    )
    requirements = RequirementAnalysisService(
        database,
        ai,
        settings,
        notifier,
        event_hub=event_hub,
    )
    requirement_exchange = RequirementExchangeService(database, ledger)
    codex_plans = CodexPlanService(
        database,
        ledger,
        ai,
        settings,
        progress=project_progress,
    )
    codex_verification = CodexVerificationService(
        database,
        ledger,
        event_hub,
        progress=project_progress,
        outcomes=project_outcomes,
        sample_formation=sample_formation,
        managed_worktree_root=Path(settings.xunying_codex_worktree_root),
    )
    codex_sync = CodexSyncService(database, event_hub, codex_verification)
    codex_development_runtime = AppServerDevelopmentRuntime(
        settings.codex_command,
        request_timeout=settings.codex_app_server_request_timeout_seconds,
    )
    codex_development = CodexDevelopmentService(
        database,
        codex_sync,
        codex_development_runtime,
        WorktreeManager(Path(settings.xunying_codex_worktree_root)),
        verification=codex_verification,
        default_model=settings.codex_model,
        default_reasoning_effort=settings.codex_reasoning_effort,
    )
    requirement_materials = RequirementMaterialsService(
        database,
        requirement_exchange,
        settings.project_root,
    )
    customer_images = CustomerImageArchiveService(
        database,
        settings.project_root,
    )
    processor = MessageProcessor(
        database,
        adapter,
        ai_queue,
        notifier,
        history_limit=settings.xianyu_history_limit,
        context_hydration_timeout_seconds=settings.xianyu_context_hydration_timeout_seconds,
        item_cache_ttl_seconds=settings.xianyu_item_cache_ttl_seconds,
        reply_burst_coalesce_seconds=settings.reply_burst_coalesce_seconds,
        reply_drafts_enabled=settings.customer_reply_drafts_enabled,
        sales_analysis_enabled=(
            settings.customer_quote_conversion_enabled
            and settings.sales_agent_enabled
            and settings.sales_agent_auto_analyze
        ),
        sales_agent=(
            sales_agent
            if (
                settings.customer_quote_conversion_enabled
                and settings.sales_agent_enabled
                and settings.sales_agent_auto_analyze
            )
            else None
        ),
        customer_images=customer_images,
        media_fetchers={
            "xianyu": adapter.fetch_media,
            "wechat": wecom_client.fetch_media,
        },
        event_hub=event_hub,
    )
    wecom = WeComService(
        settings,
        database,
        wechat_adapter,
        processor,
        style_learning,
        notifier,
        client=wecom_client,
    )
    listener = ListenerService(
        settings,
        adapter,
        processor,
        notifier,
        status,
        state_tracker=listener_state,
    )
    listener_supervisor = ListenerSupervisor(listener, status, listener_state)
    connection_recovery = ConnectionRecoveryService(
        settings,
        adapter,
        listener_supervisor,
        deepseek,
        ai,
        ai_queue=ai_queue,
        sales_agent=sales_agent,
        business_analysis=business_analysis,
    )
    conversation_history_import = ConversationHistoryImportService(
        database,
        adapter,
        ai_queue,
        event_hub,
        customer_images=customer_images,
        draft_generation_enabled=settings.customer_reply_drafts_enabled,
    )
    codex_agent_provider = (
        ai if ai.name == "codex_cli" else CodexCliProvider(settings)
    )
    openai_agent_provider = (
        ai if ai.name == "openai_compatible" else OpenAICompatibleProvider(settings)
    )
    global_agent = GlobalAgentService(
        database,
        settings,
        event_hub,
        GlobalAgentRAG(database, settings),
        GlobalAgentBusinessTools(database, ledger, business_analysis),
        customer_intake,
        providers={
            "codex_cli": codex_agent_provider,
            "deepseek": deepseek,
            "openai_compatible": openai_agent_provider,
        },
        provider_configured={
            "codex_cli": bool(settings.codex_command.strip()),
            "deepseek": settings.deepseek_configured,
            "openai_compatible": settings.openai_compatible_configured,
        },
    )
    global_agent.bootstrap_profiles()
    global_agent.recover_orphaned_runs()
    phrase_library = PhraseLibraryService(database)
    return Runtime(
        settings=settings,
        database=database,
        adapter=adapter,
        wechat_adapter=wechat_adapter,
        wechat_sender=wechat_sender,
        wecom=wecom,
        channel_senders=channel_senders,
        ai=ai,
        deepseek=deepseek,
        ai_models=ai_models,
        reply_strategy=reply_strategy,
        style_learning=style_learning,
        ai_queue=ai_queue,
        event_hub=event_hub,
        notifier=notifier,
        status=status,
        processor=processor,
        listener=listener,
        listener_state=listener_state,
        listener_supervisor=listener_supervisor,
        actions=actions,
        automation=automation,
        requirements=requirements,
        requirement_exchange=requirement_exchange,
        codex_plans=codex_plans,
        codex_sync=codex_sync,
        codex_development=codex_development,
        codex_verification=codex_verification,
        requirement_materials=requirement_materials,
        sales_agent=sales_agent,
        api_limiter=SlidingWindowRateLimiter(settings.api_rate_limit_per_minute),
        send_limiter=send_limiter,
        ledger=ledger,
        product_intelligence=product_intelligence,
        traffic_growth=traffic_growth,
        business_analysis=business_analysis,
        business_recommendations=business_recommendations,
        predictions=predictions,
        estimate_calibration=estimate_calibration,
        sample_formation=sample_formation,
        customer_relationships=customer_relationships,
        customer_intake=customer_intake,
        project_product_attribution=project_product_attribution,
        connection_recovery=connection_recovery,
        conversation_history_import=conversation_history_import,
        customer_images=customer_images,
        global_agent=global_agent,
        phrase_library=phrase_library,
    )
