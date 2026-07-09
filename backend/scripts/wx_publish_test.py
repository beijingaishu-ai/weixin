"""浏览器发布自检 / 选择器校准脚本(直接驱动 BrowserChannel,不经 DB/任务)。

先跑 wx_login.py 捕获登录态,再用本脚本快速迭代:

  cd backend
  # 默认:有头 + DRY_RUN(只建草稿不发表,最安全)
  .venv/Scripts/python scripts/wx_publish_test.py wx你的AppID

  # 纯文本更容易先跑通;卡住时看控制台是哪一步 FAIL + media/wx_debug/*.png 截图
  .venv/Scripts/python scripts/wx_publish_test.py wx你的AppID --title "测试标题" --content "<p>正文</p>"

  # 校准好、DRY_RUN 能走到 SAVE 后,再真正发表(发布到主页,不推粉丝):
  .venv/Scripts/python scripts/wx_publish_test.py wx你的AppID --real

  # 群发(推粉丝,需你管理员微信扫码/短信确认;订阅号 1 次/天):
  .venv/Scripts/python scripts/wx_publish_test.py wx你的AppID --real --publish-type 2

参数:
  --real         真正发表/群发(默认只 DRY_RUN 建草稿不发)
  --headless     无头运行(默认有头,便于观察每一步)
  --publish-type 1=发表(默认) 2=群发
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


_DUMP_JS = r"""() => {
  const out = [];
  const vis = (e) => {
    const r = e.getBoundingClientRect();
    return (r.width > 1 && r.height > 1 && e.offsetParent !== null)
      ? `VISIBLE ${Math.round(r.width)}x${Math.round(r.height)}` : 'hidden';
  };
  document.querySelectorAll('input,textarea,[contenteditable]').forEach(e => {
    out.push(`<${e.tagName.toLowerCase()}${e.type ? ' type=' + e.type : ''}> [${vis(e)}] `
      + `id="${e.id}" class="${(e.className||'').toString().slice(0,80)}" `
      + `name="${e.getAttribute('name')||''}" placeholder="${e.getAttribute('placeholder')||''}" `
      + `contenteditable="${e.getAttribute('contenteditable')||''}"`);
  });
  out.push('--- buttons/links ---');
  document.querySelectorAll('button,a,[role=button]').forEach(e => {
    const t = (e.innerText||'').trim().replace(/\s+/g,' ').slice(0, 24);
    if (t) out.push(`<${e.tagName.toLowerCase()}> [${vis(e)}] "${t}" id="${e.id}" class="${(e.className||'').toString().slice(0,60)}"`);
  });
  return out.join('\n');
}"""


async def inspect(app_id: str) -> None:
    """打开图文编辑器,导出主页面 + 各 iframe 的表单/按钮结构到 dom_dump.txt。"""
    from pathlib import Path

    from playwright.async_api import async_playwright

    from app.core.config import settings

    state = Path(settings.WX_STORAGE_STATE_DIR) / f"{app_id}.json"
    if not state.exists():
        print(f"未找到登录态 {state},请先跑 wx_login.py")
        return
    dbg = Path(settings.WX_DEBUG_SHOT_DIR)
    dbg.mkdir(parents=True, exist_ok=True)

    import re

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(storage_state=str(state))
        page = await ctx.new_page()
        await page.goto("https://mp.weixin.qq.com")
        await page.wait_for_timeout(1500)
        m = re.search(r"token=(\d+)", page.url)
        token = m.group(1) if m else ""
        print(f"token = {token}")
        # 直达图文编辑器(绕开首页卡片点击);两种已知 URL 形态都试,取能打开编辑器的
        editor = page
        candidates = [
            f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&createType=0&token={token}&lang=zh_CN",
            f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=10&isMul=1&isNew=1&token={token}&lang=zh_CN",
        ]
        for url in candidates:
            try:
                await editor.goto(url, timeout=20000)
                await editor.wait_for_timeout(3500)
                # 编辑器页通常含标题/正文可编辑区;粗判:body 文本含"标题"或有 contenteditable
                has_edit = await editor.evaluate(
                    "() => !!document.querySelector('[contenteditable=\"true\"], textarea')"
                )
                if has_edit:
                    print(f"编辑器已打开: {url}")
                    break
            except Exception as e:  # noqa: BLE001
                print(f"候选URL失败 {url}: {e}")

        blocks = [f"URL: {editor.url}\n", "=== MAIN 主页面 ===\n" + await editor.evaluate(_DUMP_JS)]
        for i, f in enumerate(editor.frames):
            if f == editor.main_frame:
                continue
            try:
                blocks.append(f"\n=== IFRAME {i} url={f.url} ===\n" + await f.evaluate(_DUMP_JS))
            except Exception as e:  # noqa: BLE001
                blocks.append(f"\n=== IFRAME {i} (无法读取: {e}) ===")
        text = "\n".join(blocks)
        (dbg / "dom_dump.txt").write_text(text, encoding="utf-8")
        await editor.screenshot(path=str(dbg / "inspect.png"), full_page=True)
        print(text[:3500])
        print(f"\n完整结构已存: {dbg / 'dom_dump.txt'}  (请把这个文件内容发我)")
        await b.close()


async def inspect_cover(app_id: str) -> None:
    """打开封面选择器 + 素材库弹窗,逐步截图并导出 DOM(校准封面上传流程)。"""
    import re
    from pathlib import Path

    from playwright.async_api import async_playwright

    from app.core.config import settings

    state = Path(settings.WX_STORAGE_STATE_DIR) / f"{app_id}.json"
    if not state.exists():
        print(f"未找到登录态 {state},请先跑 wx_login.py")
        return
    dbg = Path(settings.WX_DEBUG_SHOT_DIR)
    dbg.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False)
        ctx = await b.new_context(storage_state=str(state))
        page = await ctx.new_page()
        await page.goto("https://mp.weixin.qq.com")
        await page.wait_for_timeout(1500)
        m = re.search(r"token=(\d+)", page.url)
        token = m.group(1) if m else ""
        await page.goto(
            "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
            f"&action=edit&isNew=1&type=77&createType=0&token={token}&lang=zh_CN",
            timeout=20000,
        )
        await page.wait_for_timeout(3500)
        await page.screenshot(path=str(dbg / "cover_a_editor.png"), full_page=True)

        # 1) 打开封面选择器:hover+click 封面区(多候选)
        for sel in ["text=拖拽或选择封面", ".js_imgcover", ".appmsg_cover",
                    ".cover_appmsg__preview", "text=选择封面", ".js_cover"]:
            try:
                await page.hover(sel, timeout=1500)
                await page.click(sel, timeout=1500)
                print(f"点开封面区: {sel}")
                break
            except Exception:  # noqa: BLE001
                continue
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(dbg / "cover_b_picker.png"), full_page=True)

        # 2) 点【可见的】"从图片库选择"(隐藏副本点了无效)
        try:
            await page.locator("a.js_imagedialog:visible").first.click(timeout=4000)
            print("点从图片库选择(visible)")
        except Exception:  # noqa: BLE001
            try:
                await page.get_by_text("从图片库选择").last.click(timeout=4000)
                print("点从图片库选择(by text last)")
            except Exception as e:  # noqa: BLE001
                print(f"点从图片库选择失败: {e}")
        await page.wait_for_timeout(4000)
        await page.screenshot(path=str(dbg / "cover_c_dialog.png"), full_page=True)

        # 3) dump 主页面 + 所有 iframe(素材库弹窗常在 iframe 内)+ 各处可见图片
        def _img_js() -> str:
            return r"""() => {
              const out=[];
              document.querySelectorAll('img').forEach((e)=>{
                const r=e.getBoundingClientRect();
                if(r.width>30 && r.height>30 && e.offsetParent!==null)
                  out.push(`img ${Math.round(r.width)}x${Math.round(r.height)} class="${(e.className||'').toString().slice(0,70)}"`);
              });
              return out.slice(0,20).join('\n');
            }"""
        blocks = ["=== MAIN 元素 ===\n" + await page.evaluate(_DUMP_JS)]
        blocks.append("\n=== MAIN 可见图片 ===\n" + await page.evaluate(_img_js()))
        for i, f in enumerate(page.frames):
            if f == page.main_frame:
                continue
            try:
                blocks.append(f"\n=== IFRAME {i} url={f.url[:90]} 元素 ===\n" + await f.evaluate(_DUMP_JS))
                blocks.append(f"\n=== IFRAME {i} 可见图片 ===\n" + await f.evaluate(_img_js()))
            except Exception as e:  # noqa: BLE001
                blocks.append(f"\n=== IFRAME {i} 读取失败: {e} ===")
        text = "\n".join(blocks)
        (dbg / "dom_dump_cover.txt").write_text(text, encoding="utf-8")
        print(text[:2500])
        print(f"\n完整结构: {dbg / 'dom_dump_cover.txt'}  (连同 cover_a/b/c.png 一起发我)")
        await b.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="浏览器发布自检")
    ap.add_argument("app_id", help="真实公众号 AppID(须已用 wx_login.py 捕获登录态)")
    ap.add_argument("--title", default="浏览器发布自检")
    ap.add_argument(
        "--content",
        default="<p>这是一篇用于校准浏览器发布流程的测试图文,纯文本、不含站外图片。</p>",
    )
    ap.add_argument("--author", default="")
    ap.add_argument("--cover", default="", help="封面图本地路径(真发必需;发表要求有封面)")
    ap.add_argument("--publish-type", type=int, default=1, choices=[1, 2])
    ap.add_argument("--real", action="store_true", help="真正发表/群发(默认 DRY_RUN)")
    ap.add_argument("--headless", action="store_true", help="无头(默认有头)")
    ap.add_argument("--inspect", action="store_true",
                    help="只打开编辑器并导出 DOM 结构(供校准选择器,不发布)")
    ap.add_argument("--inspect-cover", dest="inspect_cover", action="store_true",
                    help="打开封面选择器+素材库弹窗,逐步截图并导出 DOM(校准封面)")
    args = ap.parse_args()

    # 默认:有头 + DRY_RUN(安全)。必须在 import settings 之前设。
    os.environ["WX_HEADLESS"] = "true" if args.headless else "false"
    os.environ["WX_PUBLISH_DRY_RUN"] = "false" if args.real else "true"

    if args.inspect:
        asyncio.run(inspect(args.app_id))
        return
    if args.inspect_cover:
        asyncio.run(inspect_cover(args.app_id))
        return

    from app.modules.wx_gateway.browser_channel import BrowserChannel
    from app.modules.wx_gateway.errors import WxApiError

    article = {
        "id": 0,
        "title": args.title,
        "author": args.author,
        "content": args.content,
        "cover_path": args.cover,
    }

    async def run() -> None:
        print("=" * 60)
        print(f"  app_id={args.app_id}  publish_type={args.publish_type}  "
              f"{'REAL 真发' if args.real else 'DRY_RUN 试跑'}  "
              f"{'headless' if args.headless else '有头'}")
        print("=" * 60)
        ch = BrowserChannel()
        try:
            outcome = await ch.publish(args.app_id, [article], publish_type=args.publish_type)
        except WxApiError as e:
            print(f"[前置失败] {e.errmsg}")
            return
        print(f"结果 status = {outcome.status}")
        for s in outcome.steps:
            mark = "OK  " if s.ok else "FAIL"
            print(f"  [{mark}] {s.phase}: {s.detail or s.errmsg}")
        if outcome.errmsg:
            print(f"errmsg: {outcome.errmsg}")
        if outcome.article_url:
            print(f"成文链接: {outcome.article_url}")
        print("\n截图目录: backend/media/wx_debug/  (若某步 FAIL,对照截图校准 WX_SELECTORS)")

    asyncio.run(run())


if __name__ == "__main__":
    main()
