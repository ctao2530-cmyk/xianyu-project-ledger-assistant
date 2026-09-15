from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .image_codec import validate_image, compatible_preview, ImageCodecError


class CustomerContextImageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ArchivedCustomerImage:
    archive_id: str
    conversation_id: int
    message_id: int
    storage_path: str
    sha256: str
    mime_type: str
    file_size: int
    capture_status: str
    integrity_verified: bool
    deleted: bool = False


@dataclass(frozen=True, slots=True)
class CustomerImageReadAuthorization:
    conversation_id: int
    original_images_authorized: bool


@dataclass(frozen=True, slots=True)
class CustomerContextImageInput:
    archive_id: str
    conversation_id: int
    message_id: int
    mime_type: str
    sha256: str
    file_size: int
    content: bytes = field(repr=False)
    representation: str = "original"
    source_sha256: str = ""
    source_mime_type: str = ""


class CustomerContextImageReader:
    """Read and validate archived originals without modifying or transcoding them."""

    HARD_MAX_IMAGE_BYTES = 25 * 1024 * 1024
    _MIME_ALIASES = {
        "image/jpg": "image/jpeg",
        "image/pjpeg": "image/jpeg",
        "image/x-png": "image/png",
    }

    def __init__(
        self,
        archive_root: Path,
        *,
        storage_base: Path | None = None,
        max_image_bytes: int = HARD_MAX_IMAGE_BYTES,
    ) -> None:
        try:
            resolved_root = archive_root.resolve(strict=True)
        except OSError as exc:
            raise CustomerContextImageError(
                "image_archive_root_unavailable", "客户原图归档目录不可用"
            ) from exc
        if not resolved_root.is_dir():
            raise CustomerContextImageError(
                "image_archive_root_unavailable", "客户原图归档目录不可用"
            )
        if max_image_bytes < 1 or max_image_bytes > self.HARD_MAX_IMAGE_BYTES:
            raise ValueError("max_image_bytes must be between 1 and 25 MB")
        self.archive_root = resolved_root
        self.storage_base = (storage_base or resolved_root).resolve()
        self.max_image_bytes = max_image_bytes

    @staticmethod
    def _normalize_mime(value: str) -> str:
        supplied = value.split(";", 1)[0].strip().lower()
        return CustomerContextImageReader._MIME_ALIASES.get(supplied, supplied)

    @staticmethod
    def _validate_digest(value: str) -> str:
        digest = value.strip().lower()
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise CustomerContextImageError(
                "image_metadata_invalid", "客户原图归档元数据无效"
            )
        return digest

    def _authorized(
        self,
        archive: ArchivedCustomerImage,
        authorization: CustomerImageReadAuthorization,
    ) -> None:
        if (
            not authorization.original_images_authorized
            or authorization.conversation_id < 1
            or archive.conversation_id != authorization.conversation_id
        ):
            raise CustomerContextImageError(
                "image_access_denied", "当前会话未授权读取客户原图"
            )

    def _validate_archive_metadata(self, archive: ArchivedCustomerImage) -> str:
        if archive.deleted:
            raise CustomerContextImageError("image_deleted", "原图已由用户删除")
        if archive.capture_status in {"pending", "running", "retry", "unavailable"}:
            raise CustomerContextImageError("image_not_archived", "图片尚未完成归档，请查看逐图状态")
        if archive.capture_status in {"failed", "blocked"}:
            raise CustomerContextImageError("image_archive_failed", "图片归档失败，请查看清单中的失败原因")
        if (
            not archive.archive_id.strip()
            or archive.conversation_id < 1
            or archive.message_id < 1
            or archive.capture_status != "stored"
            or not archive.integrity_verified
            or archive.deleted
            or archive.file_size < 1
            or not archive.storage_path.strip()
            or "\x00" in archive.storage_path
        ):
            raise CustomerContextImageError(
                "image_not_available", "客户原图未完成可信归档"
            )
        if archive.file_size > self.max_image_bytes:
            raise CustomerContextImageError(
                "image_too_large", "客户原图超过本次分析允许的大小"
            )
        if not self._normalize_mime(archive.mime_type).startswith("image/"):
            raise CustomerContextImageError(
                "image_metadata_invalid", "客户原图归档元数据无效"
            )
        return self._validate_digest(archive.sha256)

    def _resolve_archive_file(self, storage_path: str) -> Path:
        raw_path = Path(storage_path)
        candidate = raw_path if raw_path.is_absolute() else self.storage_base / raw_path
        lexical = Path(os.path.abspath(candidate))
        if lexical == self.archive_root or self.archive_root not in lexical.parents:
            raise CustomerContextImageError(
                "image_path_outside_archive", "客户原图存储路径越出归档目录"
            )
        current = self.archive_root
        for part in lexical.relative_to(self.archive_root).parts:
            current = current / part
            try:
                if current.is_symlink():
                    raise CustomerContextImageError(
                        "image_path_invalid", "客户原图归档路径不能包含符号链接"
                    )
            except OSError as exc:
                raise CustomerContextImageError(
                    "image_path_invalid", "客户原图存储路径无效"
                ) from exc
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise CustomerContextImageError(
                "image_file_missing", "客户原图文件不存在"
            ) from exc
        except OSError as exc:
            raise CustomerContextImageError(
                "image_path_invalid", "客户原图存储路径无效"
            ) from exc
        if resolved == self.archive_root or self.archive_root not in resolved.parents:
            raise CustomerContextImageError(
                "image_path_outside_archive", "客户原图存储路径越出归档目录"
            )
        return resolved

    def _read_original(self, path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise CustomerContextImageError(
                "image_file_unreadable", "客户原图文件不可读取"
            ) from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise CustomerContextImageError(
                    "image_file_invalid", "客户原图归档对象不是普通文件"
                )
            if before.st_size > self.max_image_bytes:
                raise CustomerContextImageError(
                    "image_too_large", "客户原图超过本次分析允许的大小"
                )
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                content = handle.read(self.max_image_bytes + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if len(content) > self.max_image_bytes:
            raise CustomerContextImageError(
                "image_too_large", "客户原图超过本次分析允许的大小"
            )
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(content) != before.st_size
        ):
            raise CustomerContextImageError(
                "image_changed_during_read", "客户原图读取期间发生变化"
            )
        return content

    def _validate_format(self, content: bytes, mime_type: str, path: Path) -> str:
        try:
            detected_mime, suffix, _width, _height = validate_image(content, mime_type)
            aliases = {".jpg": {".jpg", ".jpeg"}, ".tiff": {".tiff", ".tif"},
                       ".heic": {".heic", ".heif"}, ".heif": {".heic", ".heif"}}
            suffixes = aliases.get(suffix, {suffix})
        except ImageCodecError as exc:
            raise CustomerContextImageError("image_format_invalid" if exc.code == "image_corrupt" else exc.code, str(exc)) from None
        if detected_mime != self._normalize_mime(mime_type):
            raise CustomerContextImageError(
                "image_mime_mismatch", "客户原图内容与归档 MIME 类型不一致"
            )
        if path.suffix.lower() not in suffixes:
            raise CustomerContextImageError(
                "image_suffix_mismatch", "客户原图内容与归档扩展名不一致"
            )
        return detected_mime

    def read(
        self,
        archive: ArchivedCustomerImage,
        authorization: CustomerImageReadAuthorization,
        *, representation: str = "original",
    ) -> CustomerContextImageInput:
        self._authorized(archive, authorization)
        expected_digest = self._validate_archive_metadata(archive)
        path = self._resolve_archive_file(archive.storage_path)
        if path.stem.lower() != expected_digest:
            raise CustomerContextImageError(
                "image_storage_name_mismatch", "客户原图存储名与归档哈希不一致"
            )
        content = self._read_original(path)
        if len(content) != archive.file_size:
            raise CustomerContextImageError(
                "image_size_mismatch", "客户原图大小与归档元数据不一致"
            )
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != expected_digest:
            raise CustomerContextImageError(
                "image_hash_mismatch", "客户原图哈希与归档元数据不一致"
            )
        mime_type = self._validate_format(content, archive.mime_type, path)
        if representation not in {"original", "compatible"}:
            raise CustomerContextImageError("image_representation_invalid", "请选择原图或兼容副本")
        source_digest, source_mime = actual_digest, mime_type
        if representation == "compatible":
            try:
                content, mime_type = compatible_preview(content)
            except ImageCodecError as exc:
                raise CustomerContextImageError(exc.code, str(exc)) from None
            actual_digest = hashlib.sha256(content).hexdigest()
        return CustomerContextImageInput(
            archive_id=archive.archive_id,
            conversation_id=archive.conversation_id,
            message_id=archive.message_id,
            mime_type=mime_type,
            sha256=actual_digest,
            file_size=len(content),
            content=content,
            representation=representation,
            source_sha256=source_digest,
            source_mime_type=source_mime,
        )
