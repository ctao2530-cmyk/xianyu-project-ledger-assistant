from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from backend.app.services.customer_context_images import (
    ArchivedCustomerImage,
    CustomerContextImageError,
    CustomerContextImageReader,
    CustomerImageReadAuthorization,
)


def original_jpeg() -> bytes:
    image = Image.new("RGB", (72, 48), (109, 78, 230))
    exif = Image.Exif()
    exif[0x010E] = "synthetic metadata must remain byte-for-byte intact"
    output = BytesIO()
    image.save(output, format="JPEG", quality=91, exif=exif)
    return output.getvalue()


def archived_image(
    archive_root: Path,
    content: bytes,
    *,
    suffix: str = ".jpg",
    conversation_id: int = 17,
    mime_type: str = "image/jpeg",
    storage_path: str | None = None,
) -> ArchivedCustomerImage:
    digest = hashlib.sha256(content).hexdigest()
    relative = Path("2026") / "09" / f"{digest}{suffix}"
    path = archive_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return ArchivedCustomerImage(
        archive_id="cimg-synthetic",
        conversation_id=conversation_id,
        message_id=29,
        storage_path=storage_path or relative.as_posix(),
        sha256=digest,
        mime_type=mime_type,
        file_size=len(content),
        capture_status="stored",
        integrity_verified=True,
    )


def authorization(
    conversation_id: int = 17, *, allowed: bool = True
) -> CustomerImageReadAuthorization:
    return CustomerImageReadAuthorization(
        conversation_id=conversation_id,
        original_images_authorized=allowed,
    )


def test_read_preserves_original_bytes_hash_and_exif(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    content = original_jpeg()
    metadata = archived_image(archive_root, content)
    source_path = archive_root / metadata.storage_path
    before = hashlib.sha256(source_path.read_bytes()).hexdigest()

    result = CustomerContextImageReader(archive_root).read(metadata, authorization())

    assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before
    assert result.content == content
    assert "content=" not in repr(result)
    with Image.open(BytesIO(result.content)) as image:
        assert image.getexif()[0x010E] == "synthetic metadata must remain byte-for-byte intact"


@pytest.mark.parametrize(("allowed", "conversation_id"), [(False, 17), (True, 99)])
def test_read_requires_exact_conversation_authorization(
    tmp_path: Path, allowed: bool, conversation_id: int
) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    metadata = archived_image(archive_root, original_jpeg())
    with pytest.raises(CustomerContextImageError) as caught:
        CustomerContextImageReader(archive_root).read(
            metadata, authorization(conversation_id, allowed=allowed)
        )
    assert caught.value.code == "image_access_denied"


def test_path_traversal_symlink_and_fake_image_fail_closed(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    content = original_jpeg()
    digest = hashlib.sha256(content).hexdigest()
    (outside / f"{digest}.jpg").write_bytes(content)
    outside_metadata = ArchivedCustomerImage(
        archive_id="cimg-outside",
        conversation_id=17,
        message_id=30,
        storage_path=f"../outside/{digest}.jpg",
        sha256=digest,
        mime_type="image/jpeg",
        file_size=len(content),
        capture_status="stored",
        integrity_verified=True,
    )
    with pytest.raises(CustomerContextImageError) as traversal:
        CustomerContextImageReader(archive_root).read(
            outside_metadata, authorization()
        )
    assert traversal.value.code == "image_path_outside_archive"

    metadata = archived_image(archive_root, content)
    source = archive_root / metadata.storage_path
    link = source.with_name(f"{metadata.sha256}.jpeg")
    link.symlink_to(source)
    linked = ArchivedCustomerImage(
        **{
            **metadata.__dict__,
            "storage_path": link.relative_to(archive_root).as_posix(),
        }
    ) if hasattr(metadata, "__dict__") else ArchivedCustomerImage(
        archive_id=metadata.archive_id,
        conversation_id=metadata.conversation_id,
        message_id=metadata.message_id,
        storage_path=link.relative_to(archive_root).as_posix(),
        sha256=metadata.sha256,
        mime_type=metadata.mime_type,
        file_size=metadata.file_size,
        capture_status=metadata.capture_status,
        integrity_verified=metadata.integrity_verified,
    )
    with pytest.raises(CustomerContextImageError) as symlink:
        CustomerContextImageReader(archive_root).read(linked, authorization())
    assert symlink.value.code == "image_path_invalid"

    fake = archived_image(
        archive_root, b"not an image", suffix=".png", mime_type="image/png"
    )
    with pytest.raises(CustomerContextImageError) as invalid:
        CustomerContextImageReader(archive_root).read(fake, authorization())
    assert invalid.value.code == "image_format_invalid"


def test_hash_size_status_and_limit_are_rechecked(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    archive_root.mkdir()
    content = original_jpeg()
    metadata = archived_image(archive_root, content)
    (archive_root / metadata.storage_path).write_bytes(content + b"changed")
    with pytest.raises(CustomerContextImageError) as changed:
        CustomerContextImageReader(archive_root).read(metadata, authorization())
    assert changed.value.code in {"image_size_mismatch", "image_hash_mismatch"}

    fresh = archived_image(archive_root, content)
    with pytest.raises(CustomerContextImageError) as limited:
        CustomerContextImageReader(archive_root, max_image_bytes=64).read(
            fresh, authorization()
        )
    assert limited.value.code == "image_too_large"
