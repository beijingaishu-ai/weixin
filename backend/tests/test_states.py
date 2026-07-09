"""统一发文状态机单测(app.core.states)。

纯函数单测,不依赖 DB / HTTP / app 导入,始终可独立运行。
覆盖 content_article 段与 publish_task 段的 can_transition / ensure_transition:
合法迁移应放行、非法迁移应被 IllegalTransition 拦截。
"""
import pytest

from app.core.states import (
    ArticleStatus,
    IllegalTransition,
    TaskStatus,
    can_transition,
    ensure_transition,
)

ARTICLE = "content_article"
TASK = "publish_task"


# ---------------------------------------------------------------------------
# content_article 段合法迁移
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (ArticleStatus.TRANSFORMED, ArticleStatus.PENDING_REVIEW),
        (ArticleStatus.TRANSFORMED, ArticleStatus.APPROVED),   # 审核关时自动过审
        (ArticleStatus.PENDING_REVIEW, ArticleStatus.APPROVED),
        (ArticleStatus.PENDING_REVIEW, ArticleStatus.REJECTED),
        (ArticleStatus.REJECTED, ArticleStatus.PENDING_REVIEW),
        (ArticleStatus.REJECTED, ArticleStatus.TRANSFORMED),
        (ArticleStatus.APPROVED, ArticleStatus.DRAFT_CREATED),
    ],
)
def test_article_legal_transitions(frm, to):
    assert can_transition(ARTICLE, frm, to) is True
    # ensure_transition 对合法迁移不抛异常
    ensure_transition(ARTICLE, frm, to)


# ---------------------------------------------------------------------------
# content_article 段非法迁移
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (ArticleStatus.TRANSFORMED, ArticleStatus.DRAFT_CREATED),  # 跳过审核直接建稿
        (ArticleStatus.TRANSFORMED, ArticleStatus.REJECTED),      # 未提审不可驳回
        (ArticleStatus.APPROVED, ArticleStatus.PENDING_REVIEW),   # 过审后不可回提审
        (ArticleStatus.DRAFT_CREATED, ArticleStatus.APPROVED),    # 终态不可再迁
        (ArticleStatus.DRAFT_CREATED, ArticleStatus.TRANSFORMED),
        (ArticleStatus.PENDING_REVIEW, ArticleStatus.DRAFT_CREATED),
    ],
)
def test_article_illegal_transitions(frm, to):
    assert can_transition(ARTICLE, frm, to) is False
    with pytest.raises(IllegalTransition) as ei:
        ensure_transition(ARTICLE, frm, to)
    # 异常应携带源/目标态,便于日志定位
    assert ei.value.frm == frm
    assert ei.value.to == to


# ---------------------------------------------------------------------------
# publish_task 段合法迁移(含全链路与失败重试)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (TaskStatus.SCHEDULED, TaskStatus.PUBLISHING),
        (TaskStatus.PUBLISHING, TaskStatus.PUBLISHED),
        (TaskStatus.PUBLISHING, TaskStatus.FAILED),
        (TaskStatus.FAILED, TaskStatus.SCHEDULED),  # 重试回排期
    ],
)
def test_task_legal_transitions(frm, to):
    assert can_transition(TASK, frm, to) is True
    ensure_transition(TASK, frm, to)


def test_task_full_happy_path_chain():
    """SCHEDULED→PUBLISHING→PUBLISHED 整条链路逐段合法。"""
    chain = [TaskStatus.SCHEDULED, TaskStatus.PUBLISHING, TaskStatus.PUBLISHED]
    for frm, to in zip(chain, chain[1:]):
        assert can_transition(TASK, frm, to) is True


def test_task_retry_chain():
    """FAILED→SCHEDULED→PUBLISHING→PUBLISHED 重试后重新走通。"""
    chain = [
        TaskStatus.FAILED,
        TaskStatus.SCHEDULED,
        TaskStatus.PUBLISHING,
        TaskStatus.PUBLISHED,
    ]
    for frm, to in zip(chain, chain[1:]):
        assert can_transition(TASK, frm, to) is True


# ---------------------------------------------------------------------------
# publish_task 段非法迁移
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (TaskStatus.PUBLISHED, TaskStatus.PUBLISHING),  # 终态不可回退
        (TaskStatus.PUBLISHED, TaskStatus.FAILED),
        (TaskStatus.SCHEDULED, TaskStatus.PUBLISHED),   # 不可跳过 PUBLISHING
        (TaskStatus.SCHEDULED, TaskStatus.FAILED),
        (TaskStatus.FAILED, TaskStatus.PUBLISHING),     # 重试须先回 SCHEDULED
        (TaskStatus.FAILED, TaskStatus.PUBLISHED),
    ],
)
def test_task_illegal_transitions(frm, to):
    assert can_transition(TASK, frm, to) is False
    with pytest.raises(IllegalTransition):
        ensure_transition(TASK, frm, to)
