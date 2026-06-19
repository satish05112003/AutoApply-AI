import os
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("autoapply_ai.storage")

class StorageService:
    @staticmethod
    def _get_local_path(file_key: str) -> str:
        """Helper to get local directory absolute path."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        storage_dir = os.path.join(base_dir, "storage")
        os.makedirs(storage_dir, exist_ok=True)
        return os.path.join(storage_dir, file_key.replace("/", os.sep))

    @staticmethod
    async def upload_file(file_key: str, file_bytes: bytes) -> str:
        """Upload a file key to storage. Returns the download URL or relative path."""
        # Clean file key to work on local filesystems
        safe_key = file_key.lstrip("/")
        
        if settings.STORAGE_TYPE == "local":
            local_path = StorageService._get_local_path(safe_key)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(file_bytes)
            logger.info(f"Uploaded file to local storage: {local_path}")
            return f"/api/v1/resumes/download-file?key={safe_key}"
            
        else:
            # Fallback mock for S3/MinIO if libraries not fully configured
            try:
                import boto3
                from botocore.client import Config
                
                # Check endpoints
                if settings.STORAGE_TYPE == "r2":
                    endpoint = settings.CLOUDFLARE_R2_ENDPOINT
                    access_key = settings.CLOUDFLARE_R2_ACCESS_KEY
                    secret_key = settings.CLOUDFLARE_R2_SECRET_KEY
                else:
                    endpoint = f"http://{settings.MINIO_ENDPOINT}"
                    access_key = settings.MINIO_ACCESS_KEY
                    secret_key = settings.MINIO_SECRET_KEY
                
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    config=Config(signature_version="s3v4"),
                )
                
                # Ensure bucket exists
                bucket = settings.MINIO_BUCKET_RESUMES
                try:
                    s3_client.head_bucket(Bucket=bucket)
                except Exception:
                    s3_client.create_bucket(Bucket=bucket)
                    
                s3_client.put_object(
                    Bucket=bucket,
                    Key=safe_key,
                    Body=file_bytes
                )
                logger.info(f"Uploaded file to remote storage: s3://{bucket}/{safe_key}")
                
                # Return presigned URL or public URL
                return f"{endpoint}/{bucket}/{safe_key}"
            except Exception as e:
                logger.error(f"Remote storage upload failed: {e}. Falling back to local.", exc_info=True)
                # Fallback to local storage
                local_path = StorageService._get_local_path(safe_key)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(file_bytes)
                return f"/api/v1/resumes/download-file?key={safe_key}"

    @staticmethod
    async def download_file(file_key: str) -> bytes:
        """Download file bytes by its key."""
        safe_key = file_key.lstrip("/")
        
        # Always check local filesystem first as safety fallback
        local_path = StorageService._get_local_path(safe_key)
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                return f.read()
                
        if settings.STORAGE_TYPE == "local":
            raise FileNotFoundError(f"File {safe_key} not found in local storage.")
            
        else:
            try:
                import boto3
                if settings.STORAGE_TYPE == "r2":
                    endpoint = settings.CLOUDFLARE_R2_ENDPOINT
                    access_key = settings.CLOUDFLARE_R2_ACCESS_KEY
                    secret_key = settings.CLOUDFLARE_R2_SECRET_KEY
                else:
                    endpoint = f"http://{settings.MINIO_ENDPOINT}"
                    access_key = settings.MINIO_ACCESS_KEY
                    secret_key = settings.MINIO_SECRET_KEY
                    
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                )
                bucket = settings.MINIO_BUCKET_RESUMES
                response = s3_client.get_object(Bucket=bucket, Key=safe_key)
                return response["Body"].read()
            except Exception as e:
                logger.error(f"Remote storage download failed: {e}")
                raise FileNotFoundError(f"File {safe_key} not found.")

    @staticmethod
    async def delete_file(file_key: str) -> bool:
        """Delete file from storage."""
        safe_key = file_key.lstrip("/")
        deleted = False
        
        local_path = StorageService._get_local_path(safe_key)
        if os.path.exists(local_path):
            os.remove(local_path)
            deleted = True
            
        if settings.STORAGE_TYPE != "local":
            try:
                import boto3
                if settings.STORAGE_TYPE == "r2":
                    endpoint = settings.CLOUDFLARE_R2_ENDPOINT
                    access_key = settings.CLOUDFLARE_R2_ACCESS_KEY
                    secret_key = settings.CLOUDFLARE_R2_SECRET_KEY
                else:
                    endpoint = f"http://{settings.MINIO_ENDPOINT}"
                    access_key = settings.MINIO_ACCESS_KEY
                    secret_key = settings.MINIO_SECRET_KEY
                    
                s3_client = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                )
                bucket = settings.MINIO_BUCKET_RESUMES
                s3_client.delete_object(Bucket=bucket, Key=safe_key)
                deleted = True
            except Exception as e:
                logger.error(f"Remote storage delete failed: {e}")
                
        return deleted
