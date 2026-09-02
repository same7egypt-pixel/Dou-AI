"""Document storage service with S3 & local filesystem support."""
from __future__ import annotations

import os

STORAGE_PROVIDER = os.getenv("STORAGE_PROVIDER", "LOCAL").upper()
S3_BUCKET = os.getenv("S3_BUCKET", "")
AWS_REGION = os.getenv("AWS_REGION", "me-central-1")


class DocumentStorage:
    def store(self, key: str, content: bytes, content_type: str) -> str:
        raise NotImplementedError

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def get_signed_url(self, key: str, expires_minutes: int = 15) -> str:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError


class LocalDocumentStorage(DocumentStorage):
    def __init__(self, base_path: str = "./uploads"):
        self.base_path = base_path

    def store(self, key: str, content: bytes, content_type: str) -> str:
        path = os.path.join(self.base_path, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        return key

    def get(self, key: str) -> bytes:
        path = os.path.join(self.base_path, key)
        with open(path, "rb") as f:
            return f.read()

    def get_signed_url(self, key: str, expires_minutes: int = 15) -> str:
        return f"/uploads/{key}"

    def delete(self, key: str) -> bool:
        path = os.path.join(self.base_path, key)
        if os.path.exists(path):
            os.remove(path)
            return True
        return False


class S3DocumentStorage(DocumentStorage):
    def __init__(self):
        import boto3
        self.client = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
            region_name=AWS_REGION,
        )
        self.bucket = S3_BUCKET

    def store(self, key: str, content: bytes, content_type: str) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return key

    def get(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def get_signed_url(self, key: str, expires_minutes: int = 15) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_minutes * 60,
        )

    def delete(self, key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False


def get_storage() -> DocumentStorage:
    if STORAGE_PROVIDER == "S3" and S3_BUCKET:
        return S3DocumentStorage()
    return LocalDocumentStorage()
