from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select

from backend.app.config import get_settings
from backend.app.database import Database
from backend.app.models import (
    PhraseLibraryMutationRequest,
    PhraseLibraryState,
    PhraseSnippet,
)
from backend.app.phrase_library_schemas import (
    PhraseActivationInput,
    PhraseCategoryCreateInput,
    PhraseCreateInput,
    PhraseReorderInput,
    PhraseUpdateInput,
)
from backend.app.services.phrase_library import PhraseLibraryError, PhraseLibraryService


ROOT = Path(__file__).resolve().parents[2]


def upgrade(path: Path, revision: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    try:
        os.environ["DATABASE_URL"] = f"sqlite:///{path}"
        get_settings.cache_clear()
        command.upgrade(Config(str(ROOT / "alembic.ini")), revision)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


def build_service(tmp_path: Path) -> tuple[Database, PhraseLibraryService]:
    database = Database(f"sqlite:///{tmp_path / 'phrase-library.db'}")
    database.create_all()
    return database, PhraseLibraryService(database)


def test_defaults_are_empty_global_and_get_is_read_only(tmp_path: Path) -> None:
    database, service = build_service(tmp_path)
    first = service.view()
    second = service.view()

    assert first.revision == second.revision == 0
    assert [row.name for row in first.categories] == ["初次咨询", "开工前", "完工后"]
    assert [row.source for row in first.categories] == ["default", "default", "default"]
    assert all(row.phrases == [] for row in first.categories)
    with database.session() as session:
        assert session.scalar(
            select(func.count()).select_from(PhraseLibraryMutationRequest)
        ) == 0
        assert session.get(PhraseLibraryState, "global").revision == 0


def test_mutations_are_revision_guarded_idempotent_and_preserve_text(tmp_path: Path) -> None:
    database, service = build_service(tmp_path)
    initial = service.view()
    category = service.create_category(
        PhraseCategoryCreateInput(
            request_id="phrase-category-request-0001",
            expected_revision=initial.revision,
            name=" 需求澄清 ",
        )
    )
    assert category.revision == 1
    assert category.categories[-1].name == "需求澄清"
    assert service.create_category(
        PhraseCategoryCreateInput(
            request_id="phrase-category-request-0001",
            expected_revision=initial.revision,
            name=" 需求澄清 ",
        )
    ).idempotent is True

    default_id = category.categories[0].id
    created = service.create_phrase(
        PhraseCreateInput(
            request_id="phrase-create-request-0001",
            expected_revision=category.revision,
            category_id=default_id,
            content="第一行\n  第二行保留缩进",
        )
    )
    phrase = created.categories[0].phrases[0]
    assert phrase.content == "第一行\n  第二行保留缩进"
    assert created.revision == 2
    assert service.create_phrase(
        PhraseCreateInput(
            request_id="phrase-create-request-0001",
            expected_revision=category.revision,
            category_id=default_id,
            content="第一行\n  第二行保留缩进",
        )
    ).idempotent is True
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(PhraseSnippet)) == 1

    with pytest.raises(PhraseLibraryError, match="请求编号"):
        service.create_phrase(
            PhraseCreateInput(
                request_id="phrase-create-request-0001",
                expected_revision=category.revision,
                category_id=default_id,
                content="改用同一请求号写入其他内容",
            )
        )
    with pytest.raises(PhraseLibraryError) as conflict:
        service.create_phrase(
            PhraseCreateInput(
                request_id="phrase-create-request-0002",
                expected_revision=0,
                category_id=default_id,
                content="过期页面提交",
            )
        )
    assert conflict.value.code == "revision_conflict"
    assert conflict.value.revision == 2


def test_edit_reorder_deactivate_and_restore_keep_the_same_rows(tmp_path: Path) -> None:
    database, service = build_service(tmp_path)
    category_id = service.view().categories[0].id
    first = service.create_phrase(
        PhraseCreateInput(
            request_id="phrase-create-request-1001",
            expected_revision=0,
            category_id=category_id,
            content="第一条",
        )
    )
    second = service.create_phrase(
        PhraseCreateInput(
            request_id="phrase-create-request-1002",
            expected_revision=first.revision,
            category_id=category_id,
            content="第二条",
        )
    )
    first_id, second_id = [row.id for row in second.categories[0].phrases]
    reordered = service.reorder(
        PhraseReorderInput(
            request_id="phrase-reorder-request-1001",
            expected_revision=second.revision,
            category_id=category_id,
            phrase_ids=[second_id, first_id],
        )
    )
    assert [row.id for row in reordered.categories[0].phrases if row.active] == [second_id, first_id]

    edited = service.update_phrase(
        first_id,
        PhraseUpdateInput(
            request_id="phrase-update-request-1001",
            expected_revision=reordered.revision,
            category_id=category_id,
            content="第一条（已编辑）",
        ),
    )
    retired = service.set_activation(
        first_id,
        PhraseActivationInput(
            request_id="phrase-activation-request-1001",
            expected_revision=edited.revision,
            active=False,
        ),
    )
    inactive = next(row for row in retired.categories[0].phrases if row.id == first_id)
    assert inactive.active is False
    restored = service.set_activation(
        first_id,
        PhraseActivationInput(
            request_id="phrase-activation-request-1002",
            expected_revision=retired.revision,
            active=True,
        ),
    )
    assert next(row for row in restored.categories[0].phrases if row.id == first_id).active
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(PhraseSnippet)) == 2
        assert session.get(PhraseSnippet, first_id).content == "第一条（已编辑）"


def test_startup_migration_is_idempotent_and_rejects_partial_schema(tmp_path: Path) -> None:
    complete_path = tmp_path / "complete.db"
    complete = Database(f"sqlite:///{complete_path}")
    complete.create_all()
    complete.create_all()
    assert PhraseLibraryService(complete).view().revision == 0

    missing_index_path = tmp_path / "missing-index.db"
    missing_index = Database(f"sqlite:///{missing_index_path}")
    missing_index.create_all()
    with missing_index.engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX ix_phrase_snippets_active")
    with pytest.raises(RuntimeError, match="missing indexes"):
        missing_index.create_all()

    partial_path = tmp_path / "partial.db"
    with sqlite3.connect(partial_path) as connection:
        connection.execute(
            "CREATE TABLE phrase_library_states ("
            "id VARCHAR(32) PRIMARY KEY, revision INTEGER NOT NULL, "
            "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        )
    partial = Database(f"sqlite:///{partial_path}")
    with pytest.raises(RuntimeError, match="phrase library schema is incomplete"):
        partial.create_all()


def test_alembic_0034_to_0035_and_sqlite_integrity(tmp_path: Path) -> None:
    path = tmp_path / "alembic.db"
    upgrade(path, "20260819_0034")
    with sqlite3.connect(path) as connection:
        tables_before = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "phrase_categories" not in tables_before

    upgrade(path, "20260819_0035")
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == "20260819_0035"
        assert [
            row[0]
            for row in connection.execute(
                "SELECT name FROM phrase_categories ORDER BY position"
            )
        ] == ["初次咨询", "开工前", "完工后"]
        assert connection.execute("SELECT COUNT(*) FROM phrase_snippets").fetchone()[0] == 0
