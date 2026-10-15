"""Text-only model adapters. No message reader or executable tools are exposed."""

from pathlib import Path

from .api import ApiModel, delete_api_key, store_api_key
from .common import ModelCancelled, ModelError
from .dsh import DshModel, discover_dsh


def create_model(settings: dict, private_root: Path):
    if not isinstance(settings, dict):
        raise ModelError("MODEL_CONFIG", "模型配置格式无效。")
    backend = settings.get("backend", "dsh")
    if backend == "api":
        return ApiModel(settings.get("api", {}))
    if backend == "dsh":
        return DshModel(settings.get("dsh", {}), Path(private_root))
    raise ModelError("MODEL_CONFIG", "请选择 DSH 或兼容 API。")


__all__ = [
    "create_model", "store_api_key", "delete_api_key", "discover_dsh",
    "ModelError", "ModelCancelled", "ApiModel", "DshModel",
]
