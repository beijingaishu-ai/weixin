"""角色-权限映射(教学版固化为代码常量,对齐设计 3.5.3 与附录 A.3)。

权限点格式 `域:资源:动作`。五角色:super_admin/admin/chief_editor/operator/auditor。
数据范围(可见公众号集合)不在此定义,由 deps.get_visible_mp_ids + mp_account_assign 决定。
"""

ALL_PERMS: set[str] = {
    "mp:account:view", "mp:account:manage",
    "user:manage", "user:assign",
    "collect:source:view", "collect:source:manage", "collect:article:view",
    "mapping:rule:view", "mapping:rule:manage",
    "content:article:view", "content:article:edit", "content:article:submit",
    "content:article:audit", "content:article:delete",
    "content:material:view", "content:material:upload", "content:template:manage",
    "publish:task:view", "publish:task:manage", "publish:log:view",
    "system:config:manage",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "super_admin": set(ALL_PERMS),
    "admin": ALL_PERMS - {"system:config:manage"},
    "chief_editor": {
        "mp:account:view",
        "collect:source:view", "collect:source:manage", "collect:article:view",
        "mapping:rule:view", "mapping:rule:manage",
        "content:article:view", "content:article:edit", "content:article:submit",
        "content:article:audit", "content:article:delete",
        "content:material:view", "content:material:upload", "content:template:manage",
        "publish:task:view", "publish:task:manage", "publish:log:view",
    },
    "operator": {
        "mp:account:view",
        "collect:article:view",
        "content:article:view", "content:article:edit", "content:article:submit",
        "content:material:view", "content:material:upload",
        "publish:task:view",
    },
    "auditor": {
        "content:article:view", "content:article:audit", "publish:log:view",
    },
}

# 角色特权:以下角色对全部公众号可见,不走 mp_account_assign(设计 3.5.1 / 3.6.2)
FULL_ACCESS_ROLES: set[str] = {"super_admin", "admin", "chief_editor", "auditor"}

# 内置角色预置数据(role_code -> 显示名),seeds 用
BUILTIN_ROLES: list[tuple[str, str]] = [
    ("super_admin", "超级管理员"),
    ("admin", "管理员"),
    ("chief_editor", "主编"),
    ("operator", "运营"),
    ("auditor", "审核员"),
]

# 展示用主角色优先级(高 -> 低)
_ROLE_RANK = ["super_admin", "admin", "chief_editor", "auditor", "operator"]


def perms_of(roles: set[str]) -> set[str]:
    """多角色取权限并集。"""
    result: set[str] = set()
    for r in roles:
        result |= ROLE_PERMISSIONS.get(r, set())
    return result


def primary_role(roles: set[str]) -> str:
    for r in _ROLE_RANK:
        if r in roles:
            return r
    return next(iter(roles), "")


def is_valid_role(role_code: str) -> bool:
    return role_code in ROLE_PERMISSIONS
