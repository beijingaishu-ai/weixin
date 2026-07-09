"""微信错误码语义化(对齐设计 7.1.3)。

把微信 errcode 归为三类:
  - RETRYABLE:可退避重试(系统繁忙 / 分钟级频控)
  - TOKEN    :刷 token 后原请求重放一次
  - FATAL    :不可重试,任务转 FAILED 并按需告警
"""
from __future__ import annotations

RETRYABLE = "retryable"
TOKEN = "token"
FATAL = "fatal"
AUTH_EXPIRED = "auth_expired"  # 浏览器发布登录态过期/被踢:暂停该号队列,不退避不死信,告警续扫

# 浏览器发布专用错误码(非微信 API errcode,自定义 48xxx 段避免与官方冲突)
WX_AUTH_EXPIRED = 48101

# errcode -> (含义, 归类, 处理提示)
WX_ERROR_TABLE: dict[int, tuple[str, str, str]] = {
    -1: ("系统繁忙", RETRYABLE, "指数退避重试(1s/2s/4s,最多3次)"),
    WX_AUTH_EXPIRED: ("登录态过期需重新扫码授权", AUTH_EXPIRED,
                      "暂停该号发布队列;不计退避不死信;告警管理员扫码续期"),
    40001: ("access_token 无效", TOKEN, "invalidate 后强刷 token,原请求重放1次"),
    42001: ("access_token 已过期", TOKEN, "同 40001"),
    40164: ("调用 IP 不在白名单", FATAL, "不重试;熔断该号任务;告警运维附当前出口IP"),
    45009: ("接口日调用量超限", FATAL, "不重试;挂起至次日;检查软限流"),
    45011: ("API 调用太频繁", RETRYABLE, "退避 60s 后重试"),
    40007: ("无效 media_id", FATAL, "清素材映射缓存重走素材落地;二次仍失败转 FAILED"),
    48001: ("无该接口权限(未认证号无发布能力)", FATAL, "任务 FAILED;标记该号能力缺失"),
    53503: ("草稿未通过发布检查", FATAL, "任务 FAILED;驳回内容编辑修改(含违规/死链)"),
    53504: ("需前往公众平台官网操作草稿", FATAL, "任务 FAILED;转人工"),
    53505: ("请手动保存成功后再发表", FATAL, "任务 FAILED;转人工"),
}

# 发布结果 publish_status(freepublish/get)语义
PUBLISH_STATUS_TEXT: dict[int, str] = {
    0: "发布成功",
    1: "发布中",
    2: "原创校验未通过(常因转载未获白名单)",
    3: "常规失败",
    4: "平台审核不通过",
    5: "成功后用户删除所有文章",
    6: "成功后系统封禁所有文章",
}


class WxApiError(Exception):
    """微信接口调用失败(非 0 errcode)。"""

    def __init__(self, errcode: int, errmsg: str = "", category: str | None = None):
        meaning, cat, hint = WX_ERROR_TABLE.get(errcode, ("未知错误", FATAL, "转人工排查"))
        self.errcode = errcode
        self.errmsg = errmsg or meaning
        self.category = category or cat
        self.hint = hint
        super().__init__(f"[{errcode}] {self.errmsg} ({self.category})")

    @property
    def retryable(self) -> bool:
        return self.category == RETRYABLE

    @property
    def is_token_error(self) -> bool:
        return self.category == TOKEN

    @property
    def is_auth_expired(self) -> bool:
        return self.category == AUTH_EXPIRED


def map_wx_error(errcode: int, errmsg: str = "") -> WxApiError:
    return WxApiError(errcode, errmsg)
