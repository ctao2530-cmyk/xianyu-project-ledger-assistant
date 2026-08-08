from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..services.risk import detect_risks


STYLE_FIELDS = (
    ("简洁直接", "direct"),
    ("友好沟通", "friendly"),
    ("成交引导", "conversion"),
)

StructuredResult = TypeVar("StructuredResult", bound=BaseModel)


class ProductContext(BaseModel):
    title: str
    price: str
    description: str


class ChatContextMessage(BaseModel):
    direction: Literal["customer", "seller"]
    content: str
    time: str


class SellerStyleContext(BaseModel):
    enabled: bool = True
    sample_count: int = 0
    summary: str = ""
    traits: list[str] = Field(default_factory=list, max_length=8)
    examples: list[str] = Field(default_factory=list, max_length=20)


class AIInput(BaseModel):
    customer_message: str
    product: ProductContext
    recent_messages: list[ChatContextMessage]
    seller_rules: list[str]
    current_time: str
    seller_style: SellerStyleContext | None = None


class AIResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direct: str = Field(min_length=20, max_length=100)
    friendly: str = Field(min_length=20, max_length=100)
    conversion: str = Field(min_length=20, max_length=100)
    risk_level: Literal["low", "medium", "high"]
    risk_reasons: list[str] = Field(max_length=20)
    needs_human_confirmation: Literal[True]

    @model_validator(mode="after")
    def require_distinct_drafts(self) -> "AIResult":
        if len({self.direct, self.friendly, self.conversion}) != 3:
            raise ValueError("三条回复草稿必须明显不同")
        return self

    def with_enforced_risks(self, source: AIInput) -> "AIResult":
        # Static product metadata and older turns are context, not a request to perform
        # a risky action.  Including a product's ordinary list price here would make
        # every draft high-risk forever.  The unattended gate separately checks the
        # current customer turn and the exact reply that may be sent.
        all_text = "\n".join(
            [
                source.customer_message,
                self.direct,
                self.friendly,
                self.conversion,
            ]
        )
        deterministic = detect_risks(all_text)
        reasons = list(dict.fromkeys([*self.risk_reasons, *deterministic]))[:20]
        level = "high" if deterministic else self.risk_level
        return self.model_copy(
            update={
                "risk_level": level,
                "risk_reasons": reasons,
                "needs_human_confirmation": True,
            }
        )

    def drafts(self) -> list["GeneratedDraft"]:
        return [
            GeneratedDraft(
                style=style,
                content=getattr(self, field),
                risk_flags=detect_risks(getattr(self, field)),
            )
            for style, field in STYLE_FIELDS
        ]


@dataclass(slots=True)
class GeneratedDraft:
    style: str
    content: str
    risk_flags: list[str]


@dataclass(slots=True)
class ProviderHealth:
    status: str
    detail: str | None = None
    installed: bool | None = None
    logged_in: bool | None = None
    repair_command: str | None = None
    checked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AIModelOption:
    model: str
    display_name: str
    default_reasoning_effort: str | None
    supported_reasoning_efforts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AIModelSelection:
    model: str | None = None
    reasoning_effort: str | None = None


class AIProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        repair_command: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.safe_message = message
        self.repair_command = repair_command
        self.retryable = retryable


class AIProvider(ABC):
    name: str

    def __init__(self) -> None:
        self.health = ProviderHealth(status="checking", detail="正在检查模型环境")
        self._model_selection = AIModelSelection()

    @property
    def status(self) -> str:
        return self.health.status

    @property
    def detail(self) -> str | None:
        return self.health.detail

    @property
    def model_selection(self) -> AIModelSelection:
        return self._model_selection

    async def available_models(self, *, refresh: bool = False) -> list[AIModelOption]:
        raise AIProviderError("model_selection_unsupported", "当前 AI Provider 不支持模型选择")

    def configure_model(self, selection: AIModelSelection) -> None:
        self._model_selection = selection

    @abstractmethod
    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        raise NotImplementedError

    @abstractmethod
    async def generate(
        self,
        payload: AIInput,
        *,
        task_key: str,
        model_selection: AIModelSelection | None = None,
    ) -> AIResult:
        raise NotImplementedError

    async def generate_structured(
        self,
        prompt: str,
        *,
        result_type: type[StructuredResult],
        task_key: str,
        model_selection: AIModelSelection | None = None,
        timeout: float | None = None,
    ) -> StructuredResult:
        """Generate a validated JSON object for a non-chat-draft workflow."""
        raise AIProviderError(
            "structured_generation_unsupported",
            "当前 AI Provider 不支持需求文档生成",
        )

    async def cancel(self, task_key: str) -> None:
        return None

    async def close(self) -> None:
        return None
