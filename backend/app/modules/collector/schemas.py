"""collector 出入参模型(Pydantic v2)。

config_json 在 API 层以对象传入/返回,service 以 JSON 字符串存库。
"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --------------------------- 采集源 ---------------------------
class SourceCreate(BaseModel):
    source_name: str = Field(..., min_length=1, max_length=64)
    adapter_type: str = Field(..., min_length=1, max_length=32)
    config_json: dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int = Field(120, ge=15, description="采集间隔≥15分钟")
    jitter_seconds: int = Field(60, ge=0)
    whitelist_confirmed: int = Field(0, ge=0, le=1)
    auth_proof_url: str = Field("", max_length=512)


class SourceUpdate(BaseModel):
    source_name: str | None = Field(None, min_length=1, max_length=64)
    config_json: dict[str, Any] | None = None
    interval_minutes: int | None = Field(None, ge=15)
    jitter_seconds: int | None = Field(None, ge=0)
    whitelist_confirmed: int | None = Field(None, ge=0, le=1)
    auth_proof_url: str | None = Field(None, max_length=512)


class SourceItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_name: str
    adapter_type: str
    config_json: dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int
    jitter_seconds: int
    whitelist_confirmed: int
    auth_proof_url: str
    status: str
    fail_count: int
    next_run_at: datetime | None = None
    created_at: datetime | None = None


class SourcePage(BaseModel):
    items: list[SourceItem]
    total: int
    page: int
    page_size: int


# --------------------------- 采集文章 ---------------------------
class ArticleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    title: str
    author: str = ""
    url: str = ""
    status: str
    is_original_marked: int = 0
    unmatched_reason: str = ""
    dedup_of: int | None = None
    collected_at: datetime | None = None


class ArticleDetail(ArticleItem):
    raw_html: str = ""
    clean_html: str = ""
    cover_url: str = ""
    simhash: str = ""


class ArticlePage(BaseModel):
    items: list[ArticleItem]
    total: int
    page: int
    page_size: int


class ManualImportIn(BaseModel):
    source_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=255)
    url: str = Field("", max_length=1024)
    author: str = Field("", max_length=64)
    raw_html: str = Field(..., min_length=1)
    is_original_marked: int = Field(0, ge=0, le=1)


class RunResult(BaseModel):
    collected: int = 0
    duplicated: int = 0
    total: int = 0


class TestRunResult(BaseModel):
    ok: bool
    sample: dict[str, Any] | None = None
    hint: str = ""


class DedupInfo(BaseModel):
    id: int
    status: str
    dedup_of: int | None = None
    simhash: str = ""
    hamming_to_dup: int | None = None
    hint: str = ""


class Overview(BaseModel):
    sources_total: int = 0
    sources_active: int = 0
    articles_total: int = 0
    collected_today: int = 0
    duplicated: int = 0
    dedup_rate: float = 0.0
    by_status: dict[str, int] = Field(default_factory=dict)


class IdResult(BaseModel):
    id: int
