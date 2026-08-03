from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config

from .config import get_settings


class ObjectStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            region_name=self.settings.s3_region,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
            config=Config(signature_version="s3v4"),
        )
        self.signing_client = boto3.client(
            "s3",
            endpoint_url=(self.settings.s3_public_endpoint_url or self.settings.s3_endpoint_url),
            region_name=self.settings.s3_region,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
            config=Config(signature_version="s3v4"),
        )

    @staticmethod
    def key_for(sha256: str) -> str:
        return f"objects/{sha256[:2]}/{sha256[2:4]}/{sha256}"

    def presign_put(self, sha256: str, content_type: str) -> tuple[str, dict[str, str]]:
        key = self.key_for(sha256)
        metadata = {"sha256": sha256}
        url = self.signing_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": key,
                "ContentType": content_type,
                "Metadata": metadata,
            },
            ExpiresIn=self.settings.upload_url_ttl_seconds,
        )
        return url, {
            "Content-Type": content_type,
            "x-amz-meta-sha256": sha256,
        }

    def presign_get(self, object_key: str) -> str:
        return self.signing_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": object_key},
            ExpiresIn=self.settings.download_url_ttl_seconds,
        )

    def head(self, object_key: str) -> dict[str, Any]:
        return self.client.head_object(Bucket=self.settings.s3_bucket, Key=object_key)

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.settings.s3_bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.settings.s3_bucket)


@lru_cache
def get_storage() -> ObjectStorage:
    return ObjectStorage()
