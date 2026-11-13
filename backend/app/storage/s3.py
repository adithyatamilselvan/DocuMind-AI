import asyncio
from collections.abc import AsyncIterator

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.storage.base import ObjectNotFoundError


class S3ObjectStore:
    """S3 / MinIO store. boto3 is synchronous, so calls run in worker threads."""

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self._c = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value() or None,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    async def put_file(self, key: str, path: str, content_type: str) -> None:
        # Encryption at rest is configured on the bucket (not every S3-compatible server
        # accepts per-request SSE headers).
        await asyncio.to_thread(
            self._c.upload_file, path, self.bucket, key, ExtraArgs={"ContentType": content_type}
        )

    async def get_bytes(self, key: str) -> bytes:
        def _get() -> bytes:
            try:
                return self._c.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            except ClientError as e:
                if e.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    raise ObjectNotFoundError(key) from e
                raise

        return await asyncio.to_thread(_get)

    async def stream(self, key: str, chunk_size: int = 1024 * 256) -> AsyncIterator[bytes]:  # type: ignore[override]
        def _open():  # noqa: ANN202
            try:
                return self._c.get_object(Bucket=self.bucket, Key=key)["Body"]
            except ClientError as e:
                if e.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    raise ObjectNotFoundError(key) from e
                raise

        body = await asyncio.to_thread(_open)
        try:
            while chunk := await asyncio.to_thread(body.read, chunk_size):
                yield chunk
        finally:
            body.close()

    async def download_to(self, key: str, path: str) -> None:
        def _dl() -> None:
            try:
                self._c.download_file(self.bucket, key, path)
            except ClientError as e:
                if e.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    raise ObjectNotFoundError(key) from e
                raise

        await asyncio.to_thread(_dl)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._c.delete_object, Bucket=self.bucket, Key=key)

    async def exists(self, key: str) -> bool:
        def _head() -> bool:
            try:
                self._c.head_object(Bucket=self.bucket, Key=key)
                return True
            except ClientError:
                return False

        return await asyncio.to_thread(_head)
