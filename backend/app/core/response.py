"""统一响应包 {code, message, data}(对齐设计 3.8)。

约定:code=0 表示成功;非 0 表示业务错误。HTTP 状态码另由异常层控制。
"""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 1, data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}
