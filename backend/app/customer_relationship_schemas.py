from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ledger_schemas import LedgerSnapshotEnvelope


RequestId = str
CustomerSource = Literal["xianyu", "wechat", "referral", "other"]
CustomerFollowUpStatus = Literal["new", "contacted", "proposal", "won", "inactive"]
CustomerLevel = Literal["A", "B", "C"]


class CustomerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: RequestId = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=255)
    source: CustomerSource
    phone: str = Field(default="", max_length=100)
    follow_up_status: CustomerFollowUpStatus
    last_contact_at: str = Field(default="", max_length=64)
    level: CustomerLevel
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("last_contact_at")
    @classmethod
    def validate_last_contact_at(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            return ""
        try:
            datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("最近联系时间格式无效") from None
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            tag = value.strip()
            if not tag:
                continue
            if len(tag) > 50:
                raise ValueError("单个客户标签不能超过 50 个字符")
            if tag not in normalized:
                normalized.append(tag)
        return normalized


class CustomerUpdateResult(LedgerSnapshotEnvelope):
    customer_id: str
    idempotent: bool = False


class CustomerRelationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    project_id: str = Field(min_length=1, max_length=128)
    current_customer_id: str = Field(min_length=1, max_length=128)
    target_customer_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def customers_must_differ(self):
        if self.current_customer_id == self.target_customer_id:
            raise ValueError("目标客户与当前客户不能相同")
        return self


class CustomerRelationImpact(BaseModel):
    project_count: int
    payment_count: int
    change_order_count: int
    settlement_issue_count: int
    confirmed_amount: float
    pending_amount: float


class CustomerRelationPreview(BaseModel):
    preview_token: str
    revision: int
    project_id: str
    project_name: str
    project_status: str
    contract_total: float
    current_customer_id: str
    current_customer_name: str
    target_customer_id: str
    target_customer_name: str
    impact: CustomerRelationImpact
    preserves: list[str]
    warnings: list[str]


class CustomerRelationRebindRequest(CustomerRelationPreviewRequest):
    request_id: RequestId = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    preview_token: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")


class CustomerRelationRebindResult(LedgerSnapshotEnvelope):
    project_id: str
    current_customer_id: str
    target_customer_id: str
    impact: CustomerRelationImpact
    idempotent: bool = False
