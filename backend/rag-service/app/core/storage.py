"""
MinIO 对象存储客户端
负责文档原始文件的上传、下载和删除，实现持久化存储

使用方式:
    storage = container.get_storage()
    await storage.initialize()
    await storage.upload(bucket, object_name, local_path)
    await storage.download(bucket, object_name, local_path)
"""
import io
import logging
from typing import Optional

from config.settings import settings

logger = logging.getLogger(__name__)


class StorageClient:
    """MinIO 对象存储客户端"""

    def __init__(self):
        self._client = None
        self._is_initialized = False

    async def initialize(self):
        """初始化 MinIO 连接"""
        if self._is_initialized:
            return

        try:
            from minio import Minio

            self._client = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            logger.info(f"MinIO 连接成功: {settings.MINIO_ENDPOINT}")
            self._is_initialized = True

            # 确保 bucket 存在
            await self._ensure_bucket(settings.MINIO_BUCKET)

        except Exception as e:
            logger.warning(f"MinIO 连接失败: {e}")
            logger.warning("文档将不会持久化存储到对象存储")

    async def _ensure_bucket(self, bucket: str):
        """确保 bucket 存在，不存在则创建"""
        if not self._client:
            return
        try:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)
                logger.info(f"MinIO bucket 已创建: {bucket}")
            else:
                logger.debug(f"MinIO bucket 已存在: {bucket}")
        except Exception as e:
            logger.warning(f"MinIO bucket 检查失败: {e}")

    async def upload_from_bytes(
        self, bucket: str, object_name: str, data: bytes, content_type: Optional[str] = None,
    ) -> bool:
        """上传字节数据到 MinIO

        Args:
            bucket: Bucket 名称
            object_name: 对象路径 (如 kb_id/doc_id/filename.pdf)
            data: 文件字节内容
            content_type: 内容类型 (如 application/pdf)

        Returns:
            是否上传成功
        """
        if not self._client:
            logger.warning("MinIO 未初始化，跳过上传")
            return False

        try:
            self._client.put_object(
                bucket,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type or "application/octet-stream",
            )
            logger.info(f"MinIO 上传成功: {bucket}/{object_name} ({len(data)} bytes)")
            return True
        except Exception as e:
            logger.error(f"MinIO 上传失败: {bucket}/{object_name} - {e}")
            return False

    async def upload(self, bucket: str, object_name: str, file_path: str) -> bool:
        """上传本地文件到 MinIO

        Args:
            bucket: Bucket 名称
            object_name: 对象路径
            file_path: 本地文件路径

        Returns:
            是否上传成功
        """
        if not self._client:
            return False

        import os
        if not os.path.exists(file_path):
            logger.error(f"本地文件不存在: {file_path}")
            return False

        try:
            import mimetypes
            content_type, _ = mimetypes.guess_type(file_path)

            result = self._client.fput_object(
                bucket,
                object_name,
                file_path,
                content_type=content_type or "application/octet-stream",
            )
            logger.info(f"MinIO 上传成功: {bucket}/{object_name} (etag={result.etag})")
            return True
        except Exception as e:
            logger.error(f"MinIO 上传失败: {bucket}/{object_name} - {e}")
            return False

    async def download(self, bucket: str, object_name: str, local_path: str) -> bool:
        """从 MinIO 下载文件到本地

        Args:
            bucket: Bucket 名称
            object_name: 对象路径
            local_path: 本地目标路径

        Returns:
            是否下载成功
        """
        if not self._client:
            return False

        try:
            import os
            os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)

            self._client.fget_object(bucket, object_name, local_path)
            logger.info(f"MinIO 下载成功: {bucket}/{object_name} -> {local_path}")
            return True
        except Exception as e:
            logger.error(f"MinIO 下载失败: {bucket}/{object_name} - {e}")
            return False

    async def delete(self, bucket: str, object_name: str) -> bool:
        """从 MinIO 删除对象

        Args:
            bucket: Bucket 名称
            object_name: 对象路径

        Returns:
            是否删除成功
        """
        if not self._client:
            return False

        try:
            self._client.remove_object(bucket, object_name)
            logger.info(f"MinIO 删除成功: {bucket}/{object_name}")
            return True
        except Exception as e:
            logger.error(f"MinIO 删除失败: {bucket}/{object_name} - {e}")
            return False

    async def exists(self, bucket: str, object_name: str) -> bool:
        """检查对象是否存在

        Args:
            bucket: Bucket 名称
            object_name: 对象路径

        Returns:
            是否存在
        """
        if not self._client:
            return False

        try:
            self._client.stat_object(bucket, object_name)
            return True
        except Exception:
            return False

    async def close(self):
        """关闭连接 (由 Container 管理)"""
        self._client = None
        self._is_initialized = False
        logger.info("MinIO 连接已关闭")


# 全局单例由 Container 管理
storage_client = StorageClient()
