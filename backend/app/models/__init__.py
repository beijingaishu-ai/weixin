"""ORM 模型集中导出(便于 Base.metadata 在测试中 create_all)。"""
from app.models.audit import AuditRecord
from app.models.collect import CollectArticle, CollectSource
from app.models.content import (
    ContentArticle,
    ContentArticleVersion,
    ContentDraftGroup,
    ContentMaterial,
    ContentMaterialWxRef,
    ContentStyleTemplate,
)
from app.models.mapping import MappingRule, MappingRuleSource
from app.models.mp_account import MpAccount, MpAccountAssign
from app.models.publish import PublishLog, PublishTask
from app.models.user import SysRole, SysUser, SysUserRole

__all__ = [
    # M1
    "SysUser",
    "SysRole",
    "SysUserRole",
    "MpAccount",
    "MpAccountAssign",
    "AuditRecord",
    # M2 内容中心
    "ContentMaterial",
    "ContentMaterialWxRef",
    "ContentStyleTemplate",
    "ContentDraftGroup",
    "ContentArticle",
    "ContentArticleVersion",
    # M2 发布引擎
    "PublishTask",
    "PublishLog",
    # M3 采集中心
    "CollectSource",
    "CollectArticle",
    # M3 映射引擎
    "MappingRule",
    "MappingRuleSource",
]
