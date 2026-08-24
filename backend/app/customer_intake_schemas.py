from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CustomerSource = Literal["xianyu", "wechat", "referral", "other"]
CustomerLevel = Literal["A", "B", "C"]
CustomerPriceType = Literal["", "customer_budget", "operator_quote", "agreed_price"]


class CustomerIntakeCandidate(BaseModel):
    conversation_id: int
    channel: str
    customer_name: str
    customer_source: CustomerSource
    last_message_at: datetime | None = None
    last_text_preview: str = ""
    same_name_exists: bool = False


class CustomerIntakeCandidatesView(BaseModel):
    revision: int
    candidates: list[CustomerIntakeCandidate]


class CustomerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=0)
    confirmed: Literal[True]
    conversation_id: int | None = None
    name: str = Field(min_length=1, max_length=255)
    source: CustomerSource
    phone: str = Field(default="", max_length=100)
    level: CustomerLevel = "C"
    current_need: str = Field(default="", max_length=4_000)
    price_type: CustomerPriceType = ""
    price_amount: float | None = Field(default=None, gt=0, le=100_000_000)
    next_action: str = Field(default="", max_length=2_000)
    notes: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def price_type_required_for_amount(self):
        if self.price_amount is not None and not self.price_type:
            raise ValueError("填写金额时必须选择价格类型")
        return self


class CustomerCreateResult(BaseModel):
    revision: int
    snapshot: dict
    customer_id: str
    conversation_id: int | None = None
    created: bool = True
    idempotent: bool = False
