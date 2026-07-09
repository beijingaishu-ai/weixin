"""浏览器发布通道(对齐 v1.1《重要设计声明》)。

发布不走微信 API,改由浏览器自动化模拟人工在公众号后台(mp.weixin.qq.com)建稿并发表:
  LOGIN → NEW_DRAFT → FILL → UPLOAD_IMG → SAVE → PUBLISH → RESULT

- MockBrowserChannel:教学验收主线,不出网,一步 publish() 走完全流程并返回逐步骤记录;
  可经 mock_channel.set_mock_outcome 注入失败(submit_errcode→PUBLISH 步失败;
  publish_status!=0→RESULT 步失败),用于演练重试与告警。
- BrowserChannel:真实 Playwright 自动化(account_type 非模拟号时启用)。因强依赖后台
  页面结构、且需自有账号登录态,以"结构化步骤 + 可维护选择器配置"形式交付,真实可用性
  以届时页面为准;无 playwright 依赖时惰性报错,不影响 Mock 主线与测试。

publish() 返回 PublishOutcome:status ∈ {PUBLISHED, FAILED},附 article_url / steps。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.wx_gateway import mock_channel
from app.modules.wx_gateway.errors import PUBLISH_STATUS_TEXT, WX_AUTH_EXPIRED, WxApiError

# 页面步骤(= publish_log.phase 白名单)
STEP_LOGIN = "LOGIN"
STEP_NEW_DRAFT = "NEW_DRAFT"
STEP_FILL = "FILL"
STEP_UPLOAD_IMG = "UPLOAD_IMG"
STEP_SAVE = "SAVE"
STEP_PUBLISH = "PUBLISH"
STEP_RESULT = "RESULT"

_WX_ADMIN = "https://mp.weixin.qq.com"


@dataclass
class StepLog:
    phase: str
    ok: bool = True
    errmsg: str = ""
    detail: str = ""


@dataclass
class PublishOutcome:
    status: str                       # PUBLISHED | FAILED
    article_url: str = ""
    article_id: str = ""
    errcode: int | None = None
    errmsg: str = ""
    steps: list[StepLog] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "PUBLISHED"


# ===========================================================================
# MockBrowserChannel:本地模拟(教学主线)
# ===========================================================================
class MockBrowserChannel:
    """模拟人工建稿+发表,不出网。结果可经 mock_channel.set_mock_outcome 配置。"""

    async def publish(
        self, app_id: str, articles: list[dict], publish_type: int = 1
    ) -> PublishOutcome:
        cfg = mock_channel.get_outcome(app_id)
        _act = "群发(推送粉丝)" if publish_type == 2 else "发表(发布到主页,不推送粉丝)"
        steps: list[StepLog] = [
            StepLog(STEP_LOGIN, detail="复用 storage_state 登录态"),
            StepLog(STEP_NEW_DRAFT, detail="新建图文消息"),
            StepLog(STEP_FILL, detail=f"填充 {len(articles)} 篇(标题/作者/正文/封面)"),
            StepLog(STEP_UPLOAD_IMG, detail="正文与封面图经编辑器上传"),
            StepLog(STEP_SAVE, detail="保存草稿"),
        ]
        # 注入的"发表阶段失败"(等价原 submit_errcode)
        submit_err = cfg.get("submit_errcode")
        if submit_err:
            steps.append(StepLog(STEP_PUBLISH, ok=False, errmsg=f"发表失败 errcode={submit_err}"))
            return PublishOutcome(
                status="FAILED", errcode=submit_err,
                errmsg=f"发表被拦截(errcode={submit_err})", steps=steps,
            )
        steps.append(StepLog(STEP_PUBLISH, detail=f"点击『{_act}』"))

        # 发表结果(等价原 publish_status:0 成功,其余失败)
        status = int(cfg.get("publish_status", 0) or 0)
        if status == 0:
            n = mock_channel.next_seq("mockpub")
            url = f"{_WX_ADMIN}/s/MOCK_{n}"
            steps.append(StepLog(STEP_RESULT, detail=f"发表成功 {url}"))
            return PublishOutcome(status="PUBLISHED", article_url=url, article_id=f"mockart_{n}", steps=steps)
        text = PUBLISH_STATUS_TEXT.get(status, f"发表失败(status={status})")
        steps.append(StepLog(STEP_RESULT, ok=False, errmsg=text))
        return PublishOutcome(status="FAILED", errcode=status, errmsg=text, steps=steps)

    async def takedown(self, app_id: str, article_url: str) -> bool:
        """模拟在后台删除/下架已发表文章。"""
        return True


# ===========================================================================
# BrowserChannel:真实 Playwright 自动化(未认证个人订阅号)
# ===========================================================================
# 选择器配置(已按 mp.weixin.qq.com 图文编辑器 appmsg_edit_v2 实测校准,2026-07)。
# 微信改版时按 scripts/wx_publish_test.py --inspect 导出的 DOM 重新校准这里。
WX_SELECTORS: dict[str, str] = {
    "title_input": "#title, textarea[name='title']",
    "author_input": "#author, input[name='author']",
    # 正文是 ProseMirror contenteditable 的 div(非 iframe)
    "content_editable": "div.ProseMirror[contenteditable='true']",
    "digest_input": "#js_description, textarea[name='digest']",
    "save_btn": "button:has-text('保存为草稿')",
    # 发表按钮 class=mass_send;点后弹"创作来源声明"确认框
    "publish_btn": "button.mass_send, button:has-text('发表')",
    # 发表确认框主按钮:纯自检内容无需声明,点「无需声明并发表」
    "confirm_btn": "button:has-text('无需声明并发表'), a:has-text('无需声明并发表'), "
                   ".weui-desktop-dialog__ft .weui-desktop-btn_primary, button:has-text('确定')",
    "published_link": "a[href*='mp.weixin.qq.com/s/']",
}


def editor_url(token: str) -> str:
    """图文编辑器直达 URL(用登录态里的 token 拼,绕开首页卡片点击)。"""
    return (
        "https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2"
        f"&action=edit&isNew=1&type=77&createType=0&token={token}&lang=zh_CN"
    )


# 封面调试:每个子步骤把可见按钮/文件输入/弹窗结构落盘,一次跑完即可精确定位选择器。
_COVER_DUMP_JS = r"""
() => {
  const vis = el => { try { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none'; } catch(e){ return false; } };
  const out = { url: location.href, buttons: [], links: [], fileInputs: [], dialogs: [] };
  document.querySelectorAll('button, a.weui-desktop-btn, .weui-desktop-btn').forEach(b => {
    const t = (b.innerText || '').trim(); if (t && vis(b)) out.buttons.push({ t: t.slice(0, 24), c: (b.className || '').slice(0, 50) }); });
  document.querySelectorAll('a').forEach(a => { const t = (a.innerText || '').trim();
    if (vis(a) && ((a.className || '').includes('imagedialog') || /图片库|封面|上传|图片|正文|扫码|配图/.test(t)))
      out.links.push({ t: t.slice(0, 24), c: (a.className || '').slice(0, 60) }); });
  document.querySelectorAll('input[type=file]').forEach((f, i) => out.fileInputs.push(
    { i, visible: vis(f), accept: f.accept || '', name: f.name || '', c: (f.className || '').slice(0, 50) }));
  document.querySelectorAll('.weui-desktop-dialog, [class*="dialog"], [class*="Dialog"]').forEach(d => {
    if (!vis(d)) return;
    const title = ((d.querySelector('.weui-desktop-dialog__title, [class*="title"], [class*="Title"]') || {}).innerText || '').trim();
    const ft = [...d.querySelectorAll('button, .weui-desktop-btn')].filter(vis).map(b => (b.innerText || '').trim()).filter(Boolean).slice(0, 8);
    out.dialogs.push({ title: title.slice(0, 40), ft }); });
  return JSON.stringify(out, null, 1);
}
"""


class BrowserChannel:
    """真实 mp.weixin.qq.com 自动化(未认证个人订阅号)。

    需先用 scripts/wx_login.py 扫码捕获该号 storage_state。发布支持:
      publish_type=1 发表(发布到主页,不推粉丝,可全自动)
      publish_type=2 群发(推送粉丝,需管理员扫码/短信确认,半自动:脚本等待确认)
    WX_PUBLISH_DRY_RUN=true 时只建草稿保存、不点发表/群发(安全试跑,校准选择器)。

    ⚠️ 选择器随微信后台版本变化,首次接入按实际页面在 WX_SELECTORS 校准;
       每步失败会截图到 WX_DEBUG_SHOT_DIR 便于定位。
    """

    def __init__(self, storage_state_path: str | None = None):
        self._explicit_state = storage_state_path

    def _state_path(self, app_id: str):
        from pathlib import Path

        from app.core.config import settings

        if self._explicit_state:
            return self._explicit_state
        p = Path(settings.WX_STORAGE_STATE_DIR) / f"{app_id}.json"
        return str(p) if p.exists() else None

    async def _shot(self, page, name: str) -> None:
        try:
            from pathlib import Path

            from app.core.config import settings

            d = Path(settings.WX_DEBUG_SHOT_DIR)
            d.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(d / f"{name}.png"))
        except Exception:  # noqa: BLE001 —— 截图失败不影响主流程
            pass

    async def _cover_dump(self, page, tag: str, fname: str = "cover_trace.txt") -> None:
        """把当前页可见按钮/文件输入/弹窗结构追加到 <fname>(封面/发表调试用)。"""
        try:
            from pathlib import Path

            from app.core.config import settings

            data = await page.evaluate(_COVER_DUMP_JS)
            d = Path(settings.WX_DEBUG_SHOT_DIR)
            d.mkdir(parents=True, exist_ok=True)
            with open(d / fname, "a", encoding="utf-8") as f:
                f.write(f"\n===== {tag} =====\n{data}\n")
        except Exception:  # noqa: BLE001 —— 调试落盘失败不影响主流程
            pass

    async def publish(
        self, app_id: str, articles: list[dict], publish_type: int = 1
    ) -> PublishOutcome:
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise WxApiError(
                -1,
                "真实浏览器发布需安装 playwright(pip install playwright && "
                "python -m playwright install chromium)。教学演示请用测试/模拟号(account_type=3)。",
            ) from e

        from app.core.config import settings

        state = self._state_path(app_id)
        if not state:
            raise WxApiError(
                WX_AUTH_EXPIRED,
                f"未找到 {app_id} 的登录态,请先运行: python scripts/wx_login.py {app_id}",
            )

        steps: list[StepLog] = []
        art = articles[0]  # 首版单篇;多图文组后续扩展
        to = settings.WX_STEP_TIMEOUT_MS

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings.WX_HEADLESS)
            ctx = await browser.new_context(storage_state=state)
            page = await ctx.new_page()
            try:
                import re

                # LOGIN:复用登录态打开首页,取 token
                await page.goto(_WX_ADMIN, timeout=to)
                await page.wait_for_timeout(1500)
                m = re.search(r"token=(\d+)", page.url)
                if not m:
                    await self._shot(page, "login_failed")
                    raise WxApiError(WX_AUTH_EXPIRED, "登录态已失效,请重新扫码授权(scripts/wx_login.py)")
                token = m.group(1)
                steps.append(StepLog(STEP_LOGIN, detail="登录态有效"))

                # NEW_DRAFT:直达图文编辑器(绕开首页卡片点击)
                editor = page
                await editor.goto(editor_url(token), timeout=to)
                await editor.wait_for_selector(
                    WX_SELECTORS["title_input"], state="attached", timeout=to
                )
                await editor.wait_for_timeout(2500)
                # 关掉可能的引导/提示弹窗(best-effort)
                for txt in ("我知道了", "知道了"):
                    try:
                        await editor.click(f"button:has-text('{txt}')", timeout=1000)
                    except Exception:  # noqa: BLE001
                        pass
                steps.append(StepLog(STEP_NEW_DRAFT, detail="进入图文编辑器"))

                # FILL:标题与正文都是 ProseMirror(标题矮、正文高),按高度区分,均键入;
                #       作者是普通可见 input,直接 fill。
                pm = editor.locator(WX_SELECTORS["content_editable"])
                n = await pm.count()
                boxes: list = []
                for i in range(n):
                    el = pm.nth(i)
                    try:
                        box = await el.bounding_box()
                    except Exception:  # noqa: BLE001
                        box = None
                    if box and box["height"] > 1:
                        boxes.append((box["height"], el))
                boxes.sort(key=lambda x: x[0])
                title_pm = boxes[0][1] if boxes else None
                body_pm = boxes[-1][1] if boxes else None

                title = art.get("title", "")[:64]
                if title_pm is not None and title:
                    await title_pm.click(timeout=to)
                    await title_pm.press_sequentially(title, delay=10)
                if art.get("author"):
                    try:
                        await editor.fill(WX_SELECTORS["author_input"], art["author"][:64], timeout=5000)
                    except Exception:  # noqa: BLE001 —— 作者非必填
                        pass
                plain = re.sub(r"<[^>]+>", "", art.get("content", "")).strip()
                if body_pm is not None and plain:
                    await body_pm.click(timeout=to)
                    await body_pm.press_sequentially(plain, delay=12)
                if art.get("digest"):
                    try:
                        await editor.fill(WX_SELECTORS["digest_input"], art["digest"][:120], timeout=5000)
                    except Exception:  # noqa: BLE001 —— 摘要选填
                        pass
                steps.append(StepLog(STEP_FILL, detail="已填标题/作者/正文"))

                # 设封面(上传本地图)—— 发表必需;放 SAVE 前,DRY_RUN 也做,便于验证草稿含封面
                await self._set_cover(editor, to, art.get("cover_path", ""), steps)

                # SAVE
                await editor.click(WX_SELECTORS["save_btn"], timeout=to)
                await editor.wait_for_timeout(2500)
                await self._shot(editor, "after_save")
                steps.append(StepLog(STEP_SAVE, detail="已保存草稿"))

                # 试运行:到此为止,不真正发表
                if settings.WX_PUBLISH_DRY_RUN:
                    steps.append(StepLog(STEP_PUBLISH, detail="DRY_RUN:已建草稿,未发表"))
                    return PublishOutcome(
                        status="FAILED", errcode=None,
                        errmsg="DRY_RUN 试跑:草稿已建,未发表(设 WX_PUBLISH_DRY_RUN=false 真正发表)",
                        steps=steps,
                    )

                # 点「发表」→ 逐个放行随后弹出的确认框,直到成文链接出现。
                # 微信 发表 流程可能连续弹多个框(顺序):
                #   ① 温馨提示(一次性法律声明,主按钮「同意以上声明」;该号点过一次后不再弹)
                #   ② 原创声明(纯自检无需声明 →「无需声明并发表」)
                #   ③ 可能的二次确认(确认发表 / 确定)
                # 全自动发文要求逐个自动放行;每步落盘 publish_trace.txt 便于校准。
                await self._cover_dump(editor, "P0_before_publish", "publish_trace.txt")
                await editor.click(WX_SELECTORS["publish_btn"], timeout=to)
                await editor.wait_for_timeout(1800)
                await self._shot(editor, "publish_dialog")

                confirm_labels = [
                    "同意以上声明", "无需声明并发表", "继续发表", "确认发表", "确定",
                ]
                click_seq = []
                for step in range(6):
                    await self._cover_dump(editor, f"C{step}", "publish_trace.txt")
                    # 成文链接已出现 → 发布完成,停止点击
                    try:
                        if await editor.locator(WX_SELECTORS["published_link"]).count() > 0:
                            break
                    except Exception:  # noqa: BLE001
                        pass
                    hit = None
                    for label in confirm_labels:
                        for sel in (f"button:has-text('{label}'):visible",
                                    f"a:has-text('{label}'):visible",
                                    f"text={label}"):
                            try:
                                loc = editor.locator(sel)
                                if await loc.count() == 0:
                                    continue
                                await loc.first.click(timeout=3000)
                                hit = label
                                break
                            except Exception:  # noqa: BLE001
                                continue
                        if hit:
                            break
                    click_seq.append(hit)
                    if not hit:
                        break  # 没有已知确认按钮了(已发布 or 出现未知框,看 trace)
                    await editor.wait_for_timeout(1800)

                await self._shot(editor, "after_confirm")
                await self._cover_dump(editor, f"Pend seq={click_seq}", "publish_trace.txt")

                if publish_type == 2:
                    steps.append(StepLog(STEP_PUBLISH, detail=f"已点发表(群发,确认序列={click_seq})"))
                    ok = await self._wait_result(editor, settings.WX_MASS_CONFIRM_WAIT_S)
                    if not ok:
                        raise WxApiError(-1, "群发未在限定时间内完成管理员确认")
                else:
                    steps.append(StepLog(STEP_PUBLISH, detail=f"已点发表(发布到主页,确认序列={click_seq})"))
                    ok = await self._wait_result(editor, 60)

                # RESULT:读取成文链接;拿不到链接则视为未确认发布成功(避免误报 PUBLISHED)
                url = ""
                try:
                    url = await editor.get_attribute(WX_SELECTORS["published_link"], "href", timeout=8000) or ""
                except Exception:  # noqa: BLE001
                    url = ""
                await self._shot(editor, "after_publish")
                if not ok and not url:
                    steps.append(StepLog(
                        STEP_RESULT, ok=False,
                        errmsg=f"点完确认序列 {click_seq} 但未检出成文链接;对照 publish_trace.txt/after_confirm.png 校准"))
                    return PublishOutcome(
                        status="FAILED", errcode=-1,
                        errmsg="发表确认已点击但未检出成文链接(可能仍有未知确认框)", steps=steps)
                steps.append(StepLog(STEP_RESULT, detail=f"发布完成 {url}"))
                return PublishOutcome(status="PUBLISHED", article_url=url, steps=steps)

            except WxApiError:
                raise
            except Exception as e:  # noqa: BLE001 —— 页面异常统一转 FAILED + 截图
                try:
                    await self._shot(page, "error")
                except Exception:  # noqa: BLE001
                    pass
                phase = steps[-1].phase if steps else STEP_LOGIN
                steps.append(StepLog(phase, ok=False, errmsg=str(e)[:200]))
                return PublishOutcome(status="FAILED", errcode=-1, errmsg=str(e)[:300], steps=steps)
            finally:
                await browser.close()

    async def _set_cover(self, editor, to: int, cover_path: str, steps: list) -> None:
        """设封面(发表必需):打开封面选择器 → 从图片库选择 → 上传本地封面图 → 下一步 → 完成。

        流程按 mp.weixin.qq.com「选择图片」弹窗实测:弹窗有隐藏 <input type=file>,
        直接 set_input_files 塞图(绕过原生选择框),上传后自动选中 → 下一步(裁剪)→ 完成。
        cover_path 为空 → 记失败,发表会被"必须插入一张图片"拦下。
        """
        from pathlib import Path
        if not cover_path or not Path(cover_path).exists():
            steps.append(StepLog(STEP_UPLOAD_IMG, ok=False, errmsg="无封面图(cover_path 为空或不存在)"))
            return

        async def click_first(selectors, timeout_ms):
            """依次尝试选择器,点中第一个可见的,返回命中的选择器(未命中返回 None)。"""
            for sel in selectors:
                try:
                    loc = editor.locator(sel)
                    if await loc.count() == 0:
                        continue
                    await loc.first.click(timeout=timeout_ms)
                    return sel
                except Exception:  # noqa: BLE001
                    continue
            return None

        trace = []  # 记录每步命中的选择器,写进 step detail 便于回看
        try:
            await self._cover_dump(editor, "0_before_open")
            # 1) 打开封面区(hover 让"选择封面"浮层出现,再点)
            for sel in (".js_imgcover", ".appmsg_cover", "text=拖拽或选择封面", "text=选择封面"):
                try:
                    await editor.hover(sel, timeout=1500)
                except Exception:  # noqa: BLE001
                    pass
            opened = await click_first(
                (".js_imgcover", ".appmsg_cover", "text=拖拽或选择封面",
                 "text=选择封面", "text=从正文选择封面"), 2500)
            trace.append(f"open={opened}")
            await editor.wait_for_timeout(1200)
            await self._cover_dump(editor, "1_after_open_popover")

            # 2) 从图片库选择 → 打开「选择图片」弹窗
            lib = await click_first(
                ("a.js_imagedialog:visible", "text=从图片库选择",
                 "text=图片库", "a.js_imagedialog"), 4000)
            trace.append(f"lib={lib}")
            await editor.wait_for_timeout(2500)
            await self._cover_dump(editor, "2_after_open_dialog")

            # 3) 弹窗内隐藏 file input 直接塞封面图(优先弹窗内可见/最后一个)
            finput = editor.locator("input[type=file]")
            n = await finput.count()
            await finput.last.set_input_files(cover_path)
            trace.append(f"file_input_count={n}")
            await editor.wait_for_timeout(4500)  # 等上传完成 + 自动选中
            await self._shot(editor, "cover_uploaded")
            await self._cover_dump(editor, "3_after_upload")

            # 4) 下一步(进入裁剪);有的版本上传后直接是"确定/完成",没有"下一步"
            nxt = await click_first(
                ("button:has-text('下一步'):visible", "text=下一步",
                 ".weui-desktop-dialog__ft .weui-desktop-btn_primary:visible"), to)
            trace.append(f"next={nxt}")
            await editor.wait_for_timeout(1800)
            await self._cover_dump(editor, "4_after_next")

            # 5) 完成裁剪:「编辑封面」弹窗主按钮实测是『确认』(非完成/确定)
            fin = await click_first(
                ("button:has-text('确认'):visible", "text=确认",
                 "button:has-text('完成'):visible", "text=完成",
                 ".weui-desktop-dialog__ft .weui-desktop-btn_primary:visible",
                 "button:has-text('确定'):visible", "text=确定"), 3000)
            trace.append(f"finish={fin}")
            await editor.wait_for_timeout(1500)
            await self._shot(editor, "after_cover")
            await self._cover_dump(editor, "5_after_finish")
            steps.append(StepLog(STEP_UPLOAD_IMG, detail=f"封面:已上传本地图 [{'; '.join(trace)}]"))
        except Exception as e:  # noqa: BLE001
            await self._shot(editor, "cover_failed")
            await self._cover_dump(editor, "X_failed")
            steps.append(StepLog(
                STEP_UPLOAD_IMG, ok=False,
                errmsg=f"封面上传失败: {e} [{'; '.join(trace)}]"[:220]))

    @staticmethod
    async def _wait_result(page, timeout_s: int) -> bool:
        """轮询等待成文链接出现(发表/群发确认完成)。"""
        for _ in range(max(1, timeout_s)):
            try:
                link = await page.query_selector(WX_SELECTORS["published_link"])
                if link:
                    return True
            except Exception:  # noqa: BLE001
                pass
            await page.wait_for_timeout(1000)
        return False

    async def takedown(self, app_id: str, article_url: str) -> bool:
        # 下架:登录后台 → 定位该文章 → 删除。页面路径随后台版本变化,按实际校准。
        raise WxApiError(-1, "真实下架需按你的后台页面接入(在已发表列表中删除该文章)")
