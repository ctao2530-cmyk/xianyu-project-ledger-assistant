from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


RequestId = Annotated[str, Field(pattern=r"^[A-Za-z0-9._:-]{8,128}$")]


class PhraseMutationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: RequestId
    expected_revision: int = Field(ge=0)


class PhraseCategoryCreateInput(PhraseMutationInput):
    name: str = Field(min_length=1, max_length=32)


class PhraseCreateInput(PhraseMutationInput):
    category_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=4000)


class PhraseUpdateInput(PhraseMutationInput):
    category_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=4000)


class PhraseReorderInput(PhraseMutationInput):
    category_id: str = Field(min_length=1, max_length=128)
    phrase_ids: list[str] = Field(min_length=1, max_length=500)


class PhraseActivationInput(PhraseMutationInput):
    active: bool


class PhraseSnippetView(BaseModel):
    id: str
    category_id: str
    content: str
    position: int
    active: bool
    created_at: datetime
    updated_at: datetime


class PhraseCategoryView(BaseModel):
    id: str
    category_key: str
    name: str
    source: str
    position: int
    active: bool
    phrases: list[PhraseSnippetView]
    created_at: datetime
    updated_at: datetime


class PhraseLibraryView(BaseModel):
    revision: int
    categories: list[PhraseCategoryView]
    idempotent: bool = False
