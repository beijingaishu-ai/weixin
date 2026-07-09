"""业务异常与全局异常处理:把一切错误收敛成 {code, message, data} 包。"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("app")


class AppError(Exception):
    """业务错误。code 为业务错误码,status_code 为 HTTP 状态码。"""

    def __init__(self, message: str, code: int = 1, status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def _envelope(code: int, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"code": code, "message": message, "data": None}
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return _envelope(exc.code, exc.message, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        # 401/403/404 等:code 用 HTTP 状态码,便于前端区分
        detail = exc.detail if isinstance(exc.detail, str) else "请求错误"
        return _envelope(exc.status_code, detail, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", [])[1:])
        msg = f"参数校验失败: {loc} {first.get('msg', '')}".strip()
        return _envelope(422, msg, 422)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("未处理异常: %s", exc)
        return _envelope(500, "服务器内部错误", 500)
