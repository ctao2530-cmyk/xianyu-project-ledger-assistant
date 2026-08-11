from __future__ import annotations

from dataclasses import dataclass

from .agents import SalesAgent
from .ai import AIModelSelection, AIProvider, DeepSeekProvider, build_ai_provider
from .adapters import XianyuAdapter
from .channels.base import ChannelSender, ChannelSenderRegistry
from .channels.wechat import WeChatAdapter, WechatMockProvider, WechatSender
from .channels.wecom import WeComAPIClient, WeComSender
from .channels.xianyu import XianyuSender
from .config import Settings
from .database import Database
from .ledger import LedgerService
from .rate_limit import SlidingWindowRateLimiter
from .services.actions import HumanActions
from .services.ai_queue import AIJobQueue
from .services.ai_models import AIModelSettingsService
from .services.automation import AutoReplyService
from .services.business_analysis import BusinessAnalysisService
from .services.event_hub import EventHub
from .services.listener import ListenerService
from .services.listener_state import ListenerStateTracker
from .services.listener_supervisor import ListenerSupervisor
from .services.notifier import MacOSNotifier
from .services.processor import MessageProcessor
from .services.product_intelligence import ProductIntelligenceService
from .services.requirements import RequirementAnalysisService
from .services.requirement_exchange import RequirementExchangeService
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
    sales_agent: SalesAgent
    api_limiter: SlidingWindowRateLimiter
    send_limiter: SlidingWindowRateLimiter
    ledger: LedgerService
    product_intelligence: ProductIntelligenceService
    business_analysis: BusinessAnalysisService


def build_runtime(settings: Settings) -> Runtime:
    database = Database(settings.database_url)
    database.create_all()
    ledger = LedgerService(database, settings.project_root)
    # Create the canonical empty snapshot row without touching existing reply data.
    ledger.get()
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
    business_analysis = BusinessAnalysisService(database, ledger)
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
    processor = MessageProcessor(
        database,
        adapter,
        ai_queue,
        notifier,
        history_limit=settings.xianyu_history_limit,
        context_hydration_timeout_seconds=settings.xianyu_context_hydration_timeout_seconds,
        item_cache_ttl_seconds=settings.xianyu_item_cache_ttl_seconds,
        reply_burst_coalesce_seconds=settings.reply_burst_coalesce_seconds,
        sales_agent=(
            sales_agent
            if settings.sales_agent_enabled and settings.sales_agent_auto_analyze
            else None
        ),
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
        sales_agent=sales_agent,
        api_limiter=SlidingWindowRateLimiter(settings.api_rate_limit_per_minute),
        send_limiter=send_limiter,
        ledger=ledger,
        product_intelligence=product_intelligence,
        business_analysis=business_analysis,
    )
