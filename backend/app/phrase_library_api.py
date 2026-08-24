from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from .codex_sync_api import _local_only
from .phrase_library_schemas import (
    PhraseActivationInput,
    PhraseCategoryCreateInput,
    PhraseCreateInput,
    PhraseLibraryView,
    PhraseReorderInput,
    PhraseUpdateInput,
)
from .services.phrase_library import PhraseLibraryError


phrase_library_router = APIRouter(prefix="/api/phrase-library", tags=["phrase-library"])


def _service(request: Request):
    _local_only(request)
    return request.app.state.runtime.phrase_library


def _raise(exc: PhraseLibraryError) -> None:
    detail: dict[str, object] = {
        "code": exc.code,
        "message": exc.safe_message,
    }
    if exc.revision is not None:
        detail["revision"] = exc.revision
    raise HTTPException(status_code=exc.status_code, detail=detail) from None


@phrase_library_router.get("", response_model=PhraseLibraryView)
def phrase_library(request: Request) -> PhraseLibraryView:
    try:
        return _service(request).view()
    except PhraseLibraryError as exc:
        _raise(exc)


@phrase_library_router.post(
    "/categories",
    response_model=PhraseLibraryView,
    status_code=status.HTTP_201_CREATED,
)
def create_phrase_category(
    payload: PhraseCategoryCreateInput,
    request: Request,
) -> PhraseLibraryView:
    try:
        return _service(request).create_category(payload)
    except PhraseLibraryError as exc:
        _raise(exc)


@phrase_library_router.post(
    "/phrases",
    response_model=PhraseLibraryView,
    status_code=status.HTTP_201_CREATED,
)
def create_phrase(payload: PhraseCreateInput, request: Request) -> PhraseLibraryView:
    try:
        return _service(request).create_phrase(payload)
    except PhraseLibraryError as exc:
        _raise(exc)


@phrase_library_router.patch(
    "/phrases/{phrase_id}",
    response_model=PhraseLibraryView,
)
def update_phrase(
    phrase_id: str,
    payload: PhraseUpdateInput,
    request: Request,
) -> PhraseLibraryView:
    try:
        return _service(request).update_phrase(phrase_id, payload)
    except PhraseLibraryError as exc:
        _raise(exc)


@phrase_library_router.post(
    "/phrases/reorder",
    response_model=PhraseLibraryView,
)
def reorder_phrases(
    payload: PhraseReorderInput,
    request: Request,
) -> PhraseLibraryView:
    try:
        return _service(request).reorder(payload)
    except PhraseLibraryError as exc:
        _raise(exc)


@phrase_library_router.post(
    "/phrases/{phrase_id}/activation",
    response_model=PhraseLibraryView,
)
def activate_phrase(
    phrase_id: str,
    payload: PhraseActivationInput,
    request: Request,
) -> PhraseLibraryView:
    try:
        return _service(request).set_activation(phrase_id, payload)
    except PhraseLibraryError as exc:
        _raise(exc)
