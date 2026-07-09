"""RealChannel:真实微信接口调用(对齐设计 7.1.4)。

仅当目标号为真实认证号(account_type != 3)时使用;需教师/课程组提供已认证公众号才能
在真机验证(M2 硬前置)。教学主线走 MockChannel,本模块在 CI/无认证号环境不会被触发。

约定:JSON body 用 ensure_ascii=False 编码(中文标题);素材上传为 multipart;
非 0 errcode 统一抛 WxApiError。
"""
from __future__ import annotations

import json

import httpx

from app.modules.wx_gateway.errors import map_wx_error

WX_BASE = "https://api.weixin.qq.com"
_TIMEOUT = httpx.Timeout(connect=3, read=15, write=30, pool=5)


def _check(data: dict) -> dict:
    code = data.get("errcode", 0)
    if code and code != 0:
        raise map_wx_error(code, data.get("errmsg", ""))
    return data


def _json_content(payload: dict) -> bytes:
    # 微信要求原始 UTF-8,不能是 \uXXXX 转义
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


async def upload_image(token: str, data: bytes, filename: str = "img.jpg") -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{WX_BASE}/cgi-bin/media/uploadimg",
            params={"access_token": token},
            files={"media": (filename, data, "image/jpeg")},
        )
    return _check(resp.json())["url"]


async def add_permanent_material(
    token: str, data: bytes, filename: str = "cover.jpg", material_type: str = "image"
) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{WX_BASE}/cgi-bin/material/add_material",
            params={"access_token": token, "type": material_type},
            files={"media": (filename, data, "image/jpeg")},
        )
    d = _check(resp.json())
    return {"media_id": d.get("media_id", ""), "url": d.get("url", "")}


async def add_draft(token: str, articles: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{WX_BASE}/cgi-bin/draft/add",
            params={"access_token": token},
            content=_json_content({"articles": articles}),
            headers={"Content-Type": "application/json"},
        )
    return _check(resp.json())["media_id"]


async def submit_publish(token: str, draft_media_id: str) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{WX_BASE}/cgi-bin/freepublish/submit",
            params={"access_token": token},
            content=_json_content({"media_id": draft_media_id}),
            headers={"Content-Type": "application/json"},
        )
    return str(_check(resp.json())["publish_id"])


async def get_publish_result(token: str, publish_id: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        resp = await c.post(
            f"{WX_BASE}/cgi-bin/freepublish/get",
            params={"access_token": token},
            content=_json_content({"publish_id": publish_id}),
            headers={"Content-Type": "application/json"},
        )
    d = _check(resp.json())
    out: dict = {"publish_status": d.get("publish_status", 1)}
    if out["publish_status"] == 0:
        items = d.get("article_detail", {}).get("item", [])
        if items:
            out["article_id"] = d.get("article_id", "")
            out["article_url"] = items[0].get("article_url", "")
    return out
