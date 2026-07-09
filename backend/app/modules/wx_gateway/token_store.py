"""access_token 中控(对齐设计 7.1.1 / 7.1.2)。

- Redis 缓存 wx:token:{app_id},写入 TTL = expires_in - 300(读到的至少还有 5 分钟寿命)。
- 分布式锁 wx:lock:token:{app_id}(SET NX EX)防并发刷新互相挤掉 token;释放用 CAS。
- 仅用于真实号(account_type != 3);模拟号由 gateway 路由到 MockChannel,不取 token。
"""
from __future__ import annotations

import asyncio
import uuid

import httpx
from redis.asyncio import Redis

from app.core.crypto import decrypt_secret
from app.models.mp_account import MpAccount
from app.modules.wx_gateway.errors import WxApiError

WX_BASE = "https://api.weixin.qq.com"
SAFE_TTL = 300           # 提前量:写入 TTL 扣掉 5 分钟
LOCK_TTL = 10            # 刷新锁 10s
WAIT_STEPS = 20          # 未抢到锁时的自旋次数
WAIT_INTERVAL = 0.25     # 每次自旋 0.25s

_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


def _tkey(app_id: str) -> str:
    return f"wx:token:{app_id}"


def _lkey(app_id: str) -> str:
    return f"wx:lock:token:{app_id}"


class TokenStore:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def get(self, mp: MpAccount) -> str:
        token = await self.redis.get(_tkey(mp.app_id))
        if token:
            return token
        return await self._refresh(mp)

    async def invalidate(self, app_id: str) -> None:
        await self.redis.delete(_tkey(app_id))

    async def _refresh(self, mp: MpAccount) -> str:
        app_id = mp.app_id
        lock_id = uuid.uuid4().hex
        got = await self.redis.set(_lkey(app_id), lock_id, nx=True, ex=LOCK_TTL)
        if got:
            try:
                secret = decrypt_secret(app_id, mp.app_secret_cipher, mp.key_version)
                async with httpx.AsyncClient(timeout=5) as client:
                    resp = await client.get(
                        f"{WX_BASE}/cgi-bin/token",
                        params={
                            "grant_type": "client_credential",
                            "appid": app_id,
                            "secret": secret,
                        },
                    )
                data = resp.json()
                if "access_token" not in data:
                    await self.redis.incr(f"wx:token:failcnt:{app_id}")
                    raise WxApiError(data.get("errcode", -1), data.get("errmsg", "取 token 失败"))
                await self.redis.set(
                    _tkey(app_id),
                    data["access_token"],
                    ex=max(60, data.get("expires_in", 7200) - SAFE_TTL),
                )
                await self.redis.delete(f"wx:token:failcnt:{app_id}")
                return data["access_token"]
            finally:
                await self._release(app_id, lock_id)
        # 未抢到锁:自旋等待刷新者写回
        for _ in range(WAIT_STEPS):
            await asyncio.sleep(WAIT_INTERVAL)
            token = await self.redis.get(_tkey(app_id))
            if token:
                return token
        raise WxApiError(-1, f"{app_id} token 刷新等待超时")

    async def _release(self, app_id: str, lock_id: str) -> None:
        try:
            await self.redis.eval(_RELEASE_LUA, 1, _lkey(app_id), lock_id)
        except Exception:  # noqa: BLE001  —— 无 Lua 支持时降级为 CAS 删除
            cur = await self.redis.get(_lkey(app_id))
            if cur == lock_id:
                await self.redis.delete(_lkey(app_id))
