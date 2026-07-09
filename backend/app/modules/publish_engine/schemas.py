"""publish_engine 出入参模型(Pydantic v2)。

发布任务创建二选一(content_article_id / draft_group_id 恰一非空),
执行链路(建稿 → 提交 → 轮询)由 executor 内联完成,故创建接口出参即任务最终态。
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# 入参:创建 / Mock 配置
# ---------------------------------------------------------------------------
class PublishTaskCreate(BaseModel):
    """创建发布任务。content_article_id 与 draft_group_id 恰一非空。"""

    content_article_id: int | None = Field(None, description="单篇发文时的文章 id")
    draft_group_id: int | None = Field(None, description="多图文成组发文时的组 id")
    mp_account_id: int = Field(..., description="目标公众号 id")
    scheduled_at: datetime | None = Field(None, description="计划发布时间;缺省=立即")
    publish_type: int = Field(1, ge=1, le=2, description="1=freepublish 2=mass")

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "PublishTaskCreate":
        has_article = self.content_article_id is not None
        has_group = self.draft_group_id is not None
        if has_article == has_group:
            raise ValueError("content_article_id 与 draft_group_id 必须恰填其一")
        return self


class MockOutcomeIn(BaseModel):
    """课堂演练用:配置某模拟号(account_type=3)下次发布结果。"""

    publish_status: int | None = Field(
        None, description="下次轮询返回的 publish_status(0 成功 / 3 失败 / 4 审核不通过 ...)"
    )
    submit_errcode: int | None = Field(
        None, description="建稿/提交阶段注入的微信 errcode(如 53503)"
    )


# ---------------------------------------------------------------------------
# 出参:任务详情 / 分页 / 日志 / 统计
# ---------------------------------------------------------------------------
class PublishTaskItem(BaseModel):
    """任务列表项 / 详情公共字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    biz_key: str
    content_article_id: int | None = None
    draft_group_id: int | None = None
    mp_account_id: int
    publish_type: int
    scheduled_at: datetime | None = None
    status: str
    publish_id: str
    published_article_id: str
    published_url: str
    retry_count: int
    max_retry: int
    next_retry_at: datetime | None = None
    last_errcode: int | None = None
    last_errmsg: str
    created_by: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PublishTaskPage(BaseModel):
    items: list[PublishTaskItem]
    total: int
    page: int
    page_size: int


class PublishLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    publish_task_id: int
    phase: str
    from_status: str
    to_status: str
    wx_api: str
    request_digest: str
    errcode: int | None = None
    errmsg: str
    cost_ms: int
    created_at: datetime | None = None


class PublishStats(BaseModel):
    """各状态计数 + 成功率。"""

    total: int
    scheduled: int
    publishing: int
    published: int
    failed: int
    success_rate: float = Field(..., description="published / (已终态任务) 百分比,保留两位")
