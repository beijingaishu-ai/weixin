"""素材上微信的去重助手(对齐设计 4.2.3 / 7.3.2)。

按 (material_id, mp_account_id) 在 content_material_wx_ref 去重:同一素材对同一公众号只上传一次,
保护永久素材配额、节省调用额度。content-center(正文图 uploadimg)与 publish-engine(封面
add_material)共用本助手,保证去重语义一致、不在同一张表上各写一套。

kind:
  'uploadimg' —— 正文内图,/cgi-bin/media/uploadimg,只回 wx_url;
  'material'  —— 封面永久素材,/cgi-bin/material/add_material,回 media_id + wx_url。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.models.content import ContentMaterial, ContentMaterialWxRef
from app.models.mp_account import MpAccount

UPLOADIMG = "uploadimg"
MATERIAL = "material"


async def ensure_material_on_wx(
    db: AsyncSession,
    gateway,  # WxGateway(避免循环导入,不做类型标注)
    mp: MpAccount,
    material: ContentMaterial,
    kind: str = UPLOADIMG,
) -> ContentMaterialWxRef:
    """确保 material 已上传到 mp 对应公众号,返回引用(命中即复用不重传)。"""
    ref = await db.scalar(
        select(ContentMaterialWxRef).where(
            ContentMaterialWxRef.material_id == material.id,
            ContentMaterialWxRef.mp_account_id == mp.id,
        )
    )
    if ref and (ref.wx_url or ref.media_id):
        return ref

    data = storage.read_bytes(material.file_path)
    if kind == MATERIAL:
        result = await gateway.add_permanent_material(mp, data)
        media_id, wx_url = result.get("media_id", ""), result.get("url", "")
    else:
        wx_url = await gateway.upload_image(mp, data)
        media_id = ""

    if ref is None:
        ref = ContentMaterialWxRef(material_id=material.id, mp_account_id=mp.id)
        db.add(ref)
    ref.media_id = media_id
    ref.wx_url = wx_url
    await db.flush()
    return ref
