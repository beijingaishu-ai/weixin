"""启动引导:预置五个内置角色 + 首个超级管理员(仅当不存在时)。

幂等:重复运行不会重复插入。超级管理员密码取自环境变量 SUPER_ADMIN_PASSWORD。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.content import ContentStyleTemplate
from app.models.user import SysRole, SysUser, SysUserRole
from app.modules.auth_rbac.permissions import BUILTIN_ROLES

logger = logging.getLogger("app.seeds")

# 内置排版模板(片段仅含白名单标签 + 内联 style,对齐设计 4.3)
BUILTIN_TEMPLATES: list[dict] = [
    {
        "template_name": "左线引用",
        "category": "quote",
        "description": "绿色左边线引用块",
        "footer_html": (
            '<section style="margin:16px 8px;padding:12px 16px;border-left:4px solid #07c160;'
            'background:#f7f7f7;color:#595959;font-size:15px;line-height:1.8;">在此输入引用内容</section>'
        ),
    },
    {
        "template_name": "圆点分隔",
        "category": "divider",
        "description": "居中圆点分隔线",
        "footer_html": (
            '<section style="margin:24px 0;text-align:center;color:#c8c8c8;'
            'font-size:14px;letter-spacing:8px;">● ● ●</section>'
        ),
    },
    {
        "template_name": "标题卡片",
        "category": "title",
        "description": "居中标题卡片",
        "footer_html": (
            '<section style="margin:16px 0;padding:10px 0;text-align:center;font-size:18px;'
            'font-weight:bold;color:#07c160;border-top:2px solid #07c160;'
            'border-bottom:2px solid #07c160;">在此输入小标题</section>'
        ),
    },
]


async def seed_roles(db: AsyncSession) -> dict[str, int]:
    """确保五个内置角色存在,返回 {role_code: role_id}。"""
    existing = {r.role_code: r.id for r in await db.scalars(select(SysRole))}
    for code, name in BUILTIN_ROLES:
        if code not in existing:
            role = SysRole(role_code=code, role_name=name, is_builtin=1)
            db.add(role)
            await db.flush()
            existing[code] = role.id
            logger.info("预置角色: %s", code)
    return existing


async def seed_super_admin(db: AsyncSession, role_ids: dict[str, int]) -> None:
    username = settings.SUPER_ADMIN_USERNAME
    exists = await db.scalar(select(SysUser).where(SysUser.username == username))
    if exists:
        return
    user = SysUser(
        username=username,
        password_hash=hash_password(settings.SUPER_ADMIN_PASSWORD),
        real_name="超级管理员",
        status=1,
    )
    db.add(user)
    await db.flush()
    db.add(SysUserRole(user_id=user.id, role_id=role_ids["super_admin"]))
    logger.warning(
        "已创建超级管理员 '%s'(初始密码取自 SUPER_ADMIN_PASSWORD,请尽快登录后修改)", username
    )


async def seed_style_templates(db: AsyncSession) -> None:
    """预置内置排版模板(幂等,按 template_name 去重)。created_by 用系统账号 id=1。"""
    existing = {
        t.template_name for t in await db.scalars(select(ContentStyleTemplate))
    }
    for tpl in BUILTIN_TEMPLATES:
        if tpl["template_name"] not in existing:
            db.add(
                ContentStyleTemplate(
                    template_name=tpl["template_name"],
                    category=tpl["category"],
                    description=tpl.get("description", ""),
                    footer_html=tpl.get("footer_html"),
                    is_builtin=1,
                    enabled=1,
                    created_by=1,
                )
            )


async def run_seeds(db: AsyncSession) -> None:
    role_ids = await seed_roles(db)
    await seed_super_admin(db, role_ids)
    await seed_style_templates(db)
    await db.commit()
