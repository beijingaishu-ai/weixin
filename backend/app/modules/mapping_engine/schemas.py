"""mapping-engine 出入参模型(Pydantic v2)。

约定:
- match_condition_json / transform_action_json / schedule_policy_json 在 API 层以「对象」传入,
  service 层 json.dumps 入库;出参回读时 json.loads 还原为对象。
- 分页统一 {items, total, page, page_size}。
- rule_name<=64 对齐 schema。
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 规则 CRUD
# ---------------------------------------------------------------------------
class RuleCreate(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=64)
    target_mp_account_id: int = Field(..., ge=1)
    source_ids: list[int] = Field(default_factory=list)
    match_condition_json: dict[str, Any] = Field(default_factory=dict)
    transform_action_json: dict[str, Any] = Field(default_factory=dict)
    schedule_policy_json: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(100, ge=0)
    enabled: int = Field(1, ge=0, le=1)


class RuleUpdate(BaseModel):
    """全量更新(PUT):字段全给,重建 mapping_rule_source。"""

    rule_name: str = Field(..., min_length=1, max_length=64)
    target_mp_account_id: int = Field(..., ge=1)
    source_ids: list[int] = Field(default_factory=list)
    match_condition_json: dict[str, Any] = Field(default_factory=dict)
    transform_action_json: dict[str, Any] = Field(default_factory=dict)
    schedule_policy_json: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(100, ge=0)
    enabled: int = Field(1, ge=0, le=1)


class RuleStatusIn(BaseModel):
    enabled: int = Field(..., ge=0, le=1)


class RuleItem(BaseModel):
    """列表项 / 详情项:JSON 字段已还原为对象,附带 source_ids。"""

    id: int
    rule_name: str
    target_mp_account_id: int
    source_ids: list[int] = Field(default_factory=list)
    match_condition_json: dict[str, Any] = Field(default_factory=dict)
    transform_action_json: dict[str, Any] = Field(default_factory=dict)
    schedule_policy_json: dict[str, Any] = Field(default_factory=dict)
    priority: int
    enabled: int
    created_by: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RulePage(BaseModel):
    items: list[RuleItem]
    total: int
    page: int
    page_size: int


class IdResult(BaseModel):
    id: int


# ---------------------------------------------------------------------------
# dry-run / preview
# ---------------------------------------------------------------------------
class DryRunSample(BaseModel):
    title: str = ""
    content: str = ""


class DryRunIn(BaseModel):
    """对 match_condition_json 做命中测试:优先用 collect_article_id,否则用 sample。"""

    match_condition_json: dict[str, Any] = Field(default_factory=dict)
    collect_article_id: int | None = Field(None, ge=1)
    sample: DryRunSample | None = None


class DryRunResult(BaseModel):
    matched: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)


class PreviewIn(BaseModel):
    collect_article_id: int = Field(..., ge=1)


class PreviewResult(BaseModel):
    title: str
    content_html: str


# ---------------------------------------------------------------------------
# run-pending / executions
# ---------------------------------------------------------------------------
class RunPendingResult(BaseModel):
    processed: int = 0
    mapped: int = 0
    transformed: int = 0
    unmatched: int = 0
    produced_content: int = 0


class ExecutionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content_article_id: int
    collect_article_id: int | None = None
    mapping_rule_id: int | None = None
    target_mp_account_id: int
    title: str
    status: str
    suggested_publish_at: datetime | None = None
    created_at: datetime | None = None


class ExecutionPage(BaseModel):
    items: list[ExecutionItem]
    total: int
    page: int
    page_size: int
