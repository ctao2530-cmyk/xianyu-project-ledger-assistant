from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProjectProductImpact(BaseModel):
    project_net_confirmed: float
    project_expenses: float
    project_refunds: float
    project_profit: float
    current_product_project_count: int
    current_product_profit_before: float
    current_product_profit_after: float
    target_product_project_count: int
    target_product_profit_before: float
    target_product_profit_after: float


class ProjectProductPreviewRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    project_id: str = Field(min_length=1, max_length=128)
    target_item_external_id: str | None = Field(default=None, max_length=128)


class ProjectProductPreview(BaseModel):
    preview_token: str
    revision: int
    project_id: str
    project_name: str
    current_item_external_id: str | None
    current_item_title: str | None
    target_item_external_id: str | None
    target_item_title: str | None
    action: Literal["bind", "rebind", "unbind"]
    impact: ProjectProductImpact
    preserves: list[str]
    warnings: list[str]


class ProjectProductCommitRequest(BaseModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")
    expected_revision: int = Field(ge=0)
    preview_token: str = Field(min_length=64, max_length=64)
    project_id: str = Field(min_length=1, max_length=128)
    target_item_external_id: str | None = Field(default=None, max_length=128)


class ProjectProductCommitResult(BaseModel):
    revision: int
    snapshot: dict
    project_id: str
    current_item_external_id: str | None
    target_item_external_id: str | None
    impact: ProjectProductImpact
    idempotent: bool = False
