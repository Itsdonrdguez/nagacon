from __future__ import annotations

import mimetypes
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

from fastapi.responses import FileResponse, RedirectResponse

from app.core.config import settings


class StorageError(RuntimeError):
    pass


def _looks_like_local_reference(reference: str | None) -> bool:
    if not reference:
        return False
    ref = str(reference)
    if ref.startswith(("s3://", "pruned://", "http://", "https://")):
        return False
    return True


def storage_root(base_dir: str | None = None) -> Path:
    configured_root = getattr(settings, "STORAGE_LOCAL_ROOT", "") or ""
    root = Path(base_dir or configured_root or (Path.cwd() / "exports"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


class _LocalStorage:
    def _normalize(self, path: str | Path) -> Path:
        raw = Path(path)
        if raw.is_absolute():
            return raw
        return storage_root() / raw

    def save_bytes(self, path: str | Path, data: bytes, content_type: str | None = None) -> str:
        target = self._normalize(path)
        ensure_dir(target.parent)
        target.write_bytes(data)
        return str(target.resolve())

    def save_text(self, path: str | Path, content: str, encoding: str = "utf-8") -> str:
        target = self._normalize(path)
        ensure_dir(target.parent)
        target.write_text(content, encoding=encoding)
        return str(target.resolve())

    def exists(self, reference: str) -> bool:
        target = Path(reference)
        return target.exists() and target.is_file()

    def delete(self, reference: str) -> bool:
        target = Path(reference)
        if not target.exists():
            return False
        if target.is_file():
            target.unlink(missing_ok=True)
            return True
        return False

    @contextmanager
    def local_path(self, reference: str, suffix: str | None = None) -> Iterator[Path]:
        yield Path(reference).resolve()

    def download_response(self, reference: str, filename: str | None = None, media_type: str | None = None):
        target = Path(reference).resolve()
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(reference)
        guessed_type, _ = mimetypes.guess_type(str(target))
        return FileResponse(
            path=str(target),
            filename=filename or target.name,
            media_type=media_type or guessed_type or "application/octet-stream",
        )


class _S3Storage:
    def __init__(self) -> None:
        self.bucket = getattr(settings, "S3_BUCKET", "") or ""
        self.endpoint_url = getattr(settings, "S3_ENDPOINT_URL", "") or None
        self.region = getattr(settings, "S3_REGION", "auto")
        self.access_key = getattr(settings, "S3_ACCESS_KEY_ID", "") or ""
        self.secret_key = getattr(settings, "S3_SECRET_ACCESS_KEY", "") or ""
        if not self.bucket:
            raise StorageError("S3_BUCKET / R2_BUCKET is not configured")
        try:
            import boto3
        except Exception as exc:
            raise StorageError(f"boto3 is required for S3/R2 storage: {exc}") from exc
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self.access_key or None,
            aws_secret_access_key=self.secret_key or None,
        )

    def _key(self, path: str | Path) -> str:
        raw = Path(path)
        try:
            return raw.resolve().relative_to(storage_root()).as_posix()
        except Exception:
            try:
                return raw.relative_to(storage_root()).as_posix()
            except Exception:
                return str(raw).replace("\\", "/").lstrip("/")

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _split_reference(self, reference: str) -> tuple[str, str]:
        if not reference.startswith("s3://"):
            raise StorageError(f"Unsupported S3 reference: {reference}")
        bucket_and_key = reference[len("s3://"):]
        bucket, _, key = bucket_and_key.partition("/")
        return bucket, key

    def save_bytes(self, path: str | Path, data: bytes, content_type: str | None = None) -> str:
        key = self._key(path)
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return self._uri(key)

    def save_text(self, path: str | Path, content: str, encoding: str = "utf-8") -> str:
        key = self._key(path)
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content.encode(encoding),
            ContentType=f"text/plain; charset={encoding}",
        )
        return self._uri(key)

    def exists(self, reference: str) -> bool:
        bucket, key = self._split_reference(reference)
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, reference: str) -> bool:
        bucket, key = self._split_reference(reference)
        self.client.delete_object(Bucket=bucket, Key=key)
        return True

    @contextmanager
    def local_path(self, reference: str, suffix: str | None = None) -> Iterator[Path]:
        bucket, key = self._split_reference(reference)
        response = self.client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or Path(key).suffix or "")
        temp.write(data)
        temp.flush()
        temp.close()
        try:
            yield Path(temp.name)
        finally:
            try:
                Path(temp.name).unlink(missing_ok=True)
            except Exception:
                pass

    def download_response(self, reference: str, filename: str | None = None, media_type: str | None = None):
        bucket, key = self._split_reference(reference)
        content_type = media_type or mimetypes.guess_type(filename or key)[0] or "application/octet-stream"
        public_base = getattr(settings, "S3_PUBLIC_BASE_URL", "") or ""
        if public_base:
            return RedirectResponse(url=f"{public_base.rstrip('/')}/{quote(key)}")
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ResponseContentType": content_type,
                "ResponseContentDisposition": f'attachment; filename="{filename or Path(key).name}"',
            },
            ExpiresIn=3600,
        )
        return RedirectResponse(url=url)


def get_storage():
    backend = str(getattr(settings, "STORAGE_BACKEND", "local") or "local").lower()
    if backend == "s3":
        return _S3Storage()
    return _LocalStorage()


def store_bytes(path: str | Path, data: bytes, content_type: str | None = None) -> str:
    return get_storage().save_bytes(path, data, content_type=content_type)


def store_text(path: str | Path, content: str, encoding: str = "utf-8") -> str:
    return get_storage().save_text(path, content, encoding=encoding)


def resolve_local_path(path: str | Path) -> Path:
    return Path(path).resolve()


def file_exists(reference: str | None) -> bool:
    if not reference:
        return False
    if _looks_like_local_reference(reference):
        return _LocalStorage().exists(str(reference))
    return get_storage().exists(str(reference))


def delete_reference(reference: str | None) -> bool:
    if not reference:
        return False
    if str(reference).startswith("pruned://"):
        return False
    if _looks_like_local_reference(reference):
        return _LocalStorage().delete(str(reference))
    return get_storage().delete(str(reference))


@contextmanager
def local_temp_path(reference: str, suffix: str | None = None) -> Iterator[Path]:
    storage = _LocalStorage() if _looks_like_local_reference(reference) else get_storage()
    with storage.local_path(reference, suffix=suffix) as path:
        yield path


def download_response(reference: str, filename: str | None = None, media_type: str | None = None):
    storage = _LocalStorage() if _looks_like_local_reference(reference) else get_storage()
    return storage.download_response(reference, filename=filename, media_type=media_type)
