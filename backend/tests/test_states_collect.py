"""collect_article 段状态机单测(app.core.states,M3 采集/映射启用)。

纯函数单测,不依赖 DB / HTTP / app 导入,始终可独立运行。
覆盖 can_transition / ensure_transition 的 collect_article 段:
- 合法:COLLECTED→MAPPED、MAPPED→TRANSFORMED、COLLECTED→UNMATCHED、UNMATCHED→MAPPED;
- 非法:COLLECTED→TRANSFORMED(不可跳过 MAPPED)、TRANSFORMED→任意(终态)、MAPPED→COLLECTED(不可回退)。
"""
import pytest

from app.core.states import (
    CollectStatus,
    IllegalTransition,
    can_transition,
    ensure_transition,
)

COLLECT = "collect_article"


# ---------------------------------------------------------------------------
# collect_article 段合法迁移
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (CollectStatus.COLLECTED, CollectStatus.MAPPED),        # 命中规则
        (CollectStatus.MAPPED, CollectStatus.TRANSFORMED),      # 转换产出 content_article
        (CollectStatus.COLLECTED, CollectStatus.UNMATCHED),     # 无规则命中/去重/原创拦截
        (CollectStatus.MAPPED, CollectStatus.UNMATCHED),        # 已命中但转换阶段被拦截
        (CollectStatus.UNMATCHED, CollectStatus.MAPPED),        # 人工授权/改规则后重跑
    ],
)
def test_collect_legal_transitions(frm, to):
    assert can_transition(COLLECT, frm, to) is True
    # ensure_transition 对合法迁移不抛异常
    ensure_transition(COLLECT, frm, to)


def test_collect_full_happy_path_chain():
    """COLLECTED→MAPPED→TRANSFORMED 整条链路逐段合法。"""
    chain = [
        CollectStatus.COLLECTED,
        CollectStatus.MAPPED,
        CollectStatus.TRANSFORMED,
    ]
    for frm, to in zip(chain, chain[1:]):
        assert can_transition(COLLECT, frm, to) is True


def test_collect_unmatched_requeue_chain():
    """UNMATCHED→MAPPED→TRANSFORMED:复盘授权后重跑走通。"""
    chain = [
        CollectStatus.UNMATCHED,
        CollectStatus.MAPPED,
        CollectStatus.TRANSFORMED,
    ]
    for frm, to in zip(chain, chain[1:]):
        assert can_transition(COLLECT, frm, to) is True


# ---------------------------------------------------------------------------
# collect_article 段非法迁移
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (CollectStatus.COLLECTED, CollectStatus.TRANSFORMED),  # 不可跳过 MAPPED 直接转换
        (CollectStatus.TRANSFORMED, CollectStatus.MAPPED),     # TRANSFORMED 终态,不可再迁
        (CollectStatus.TRANSFORMED, CollectStatus.UNMATCHED),
        (CollectStatus.TRANSFORMED, CollectStatus.COLLECTED),
        (CollectStatus.MAPPED, CollectStatus.COLLECTED),       # 不可回退到初态
        (CollectStatus.UNMATCHED, CollectStatus.TRANSFORMED),  # 须先回 MAPPED
        (CollectStatus.COLLECTED, CollectStatus.COLLECTED),    # 自迁移非法
    ],
)
def test_collect_illegal_transitions(frm, to):
    assert can_transition(COLLECT, frm, to) is False
    with pytest.raises(IllegalTransition) as ei:
        ensure_transition(COLLECT, frm, to)
    # 异常应携带源/目标态,便于日志定位
    assert ei.value.frm == frm
    assert ei.value.to == to


def test_collect_transformed_is_terminal():
    """TRANSFORMED 为终态:对全部目标态均不可迁。"""
    for to in CollectStatus:
        assert can_transition(COLLECT, CollectStatus.TRANSFORMED, to) is False
