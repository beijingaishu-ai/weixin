"""wx-gateway 门面:系统唯一的微信出口。

v1.1《重要设计声明》:发布不走 API,改由浏览器自动化(BrowserChannel/MockBrowserChannel)。
- 发布:publish(mp, articles) → PublishOutcome;下架:takedown(mp, url)。
  account_type=3(测试/模拟号)→ MockBrowserChannel(不出网,教学主线);否则 → BrowserChannel。
- 素材/正文图:upload_image / add_permanent_material 保留(content-center 提审管道复用);
  模拟号返回模拟 URL,真实号的图片最终由 BrowserChannel 在编辑器内上传(见声明)。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import Depends
from redis.asyncio import Redis

from app.core.redis import get_redis
from app.core.states import WxLoginStatus
from app.models.mp_account import MpAccount
from app.modules.wx_gateway import mock_channel, real_channel
from app.modules.wx_gateway.browser_channel import (
    BrowserChannel,
    MockBrowserChannel,
    PublishOutcome,
)
from app.modules.wx_gateway.errors import WX_AUTH_EXPIRED, WxApiError  # re-export
from app.modules.wx_gateway.token_store import TokenStore

MOCK_ACCOUNT_TYPE = 3

__all__ = ["WxGateway", "get_gateway", "WxApiError", "PublishOutcome", "login_valid"]


def login_valid(mp: MpAccount) -> bool:
    """真实号浏览器发布登录态是否在授权有效期内(AUTHORIZED/EXPIRING 且未到 expires_at)。

    唯一时间判据 = wx_login_expires_at;详见 docs/浏览器发布登录态授权设计.md。
    executor 前置校验与 gateway 兜底共用本函数;scheduler 队列过滤在 SQL 层做等价判定。
    """
    return (
        mp.wx_login_status in (WxLoginStatus.AUTHORIZED, WxLoginStatus.EXPIRING)
        and mp.wx_login_expires_at is not None
        and datetime.utcnow() < mp.wx_login_expires_at
    )


class WxGateway:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.tokens = TokenStore(redis)
        self._mock_browser = MockBrowserChannel()

    @staticmethod
    def is_mock(mp: MpAccount) -> bool:
        return mp.account_type == MOCK_ACCOUNT_TYPE

    async def _token(self, mp: MpAccount) -> str:
        return await self.tokens.get(mp)

    # ---- 素材/正文图(content-center 提审管道复用)---------------------------
    async def upload_image(self, mp: MpAccount, data: bytes, filename: str = "img.jpg") -> str:
        if self.is_mock(mp):
            return await mock_channel.upload_image(mp.app_id, data)
        return await real_channel.upload_image(await self._token(mp), data, filename)

    async def add_permanent_material(
        self, mp: MpAccount, data: bytes, filename: str = "cover.jpg", material_type: str = "image"
    ) -> dict:
        if self.is_mock(mp):
            return await mock_channel.add_permanent_material(mp.app_id, data, material_type)
        return await real_channel.add_permanent_material(
            await self._token(mp), data, filename, material_type
        )

    # ---- 发布:浏览器自动化(不走 API)-------------------------------------
    async def publish(
        self, mp: MpAccount, articles: list[dict], publish_type: int = 1
    ) -> PublishOutcome:
        """浏览器模拟在公众号后台建稿并发布。publish_type:1=发表 2=群发。

        真实号:发布前兜底校验登录态授权(过期不启浏览器,直接抛 WX_AUTH_EXPIRED);
        主拦截在 scheduler 队列层(过期号任务不入队),此处为单出口最后一道防线。
        """
        if self.is_mock(mp):
            return await self._mock_browser.publish(mp.app_id, articles, publish_type)
        if not login_valid(mp):
            raise WxApiError(
                WX_AUTH_EXPIRED,
                f"{mp.mp_name} 登录态未授权/已过期({mp.wx_login_status}),需管理员扫码续期",
            )
        return await BrowserChannel().publish(mp.app_id, articles, publish_type)

    async def takedown(self, mp: MpAccount, article_url: str) -> bool:
        """一键下架:模拟在后台删除已发表文章。"""
        if self.is_mock(mp):
            return await self._mock_browser.takedown(mp.app_id, article_url)
        return await BrowserChannel().takedown(mp.app_id, article_url)


async def get_gateway(redis: Redis = Depends(get_redis)) -> WxGateway:
    return WxGateway(redis)
