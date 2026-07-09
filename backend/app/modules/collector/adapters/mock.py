"""MockAdapter:内置样例数据集,不触网,供教学演示与测试。

- 通过 config_json.dataset 选择数据集(默认 "campus");未知 dataset 回退默认集。
- 每个数据集 >=5 篇,含 标题/作者/url/正文HTML/pub_time;
  其中至少 1 篇 is_original_marked=True,用于演示"原创转载未授权拦截"。
- fetch_list 返回全部清单(游标可空实现,不做增量);fetch_detail 返回内置正文。

因不出网,MockAdapter 可被单测直接实例化调用。
"""
from __future__ import annotations

from typing import Any

from app.modules.collector.adapters.base import (
    ArticleDetail,
    ArticleMeta,
    SourceAdapter,
    register,
)

# ---------------------------------------------------------------------------
# 内置数据集:dataset 名 -> 文章列表
# 每篇字段:url/title/author/pub_time/source_mp_name/is_original_marked/raw_html/cover_url
# ---------------------------------------------------------------------------
_DATASETS: dict[str, list[dict[str, Any]]] = {
    "campus": [
        {
            "url": "https://example.edu/news/1",
            "title": "校园开放日活动圆满举行",
            "author": "校园通讯社",
            "pub_time": "2026-06-30T09:00:00",
            "source_mp_name": "阳光校园",
            "is_original_marked": False,
            "cover_url": "https://example.edu/img/openday.jpg",
            "raw_html": (
                "<h1>校园开放日活动圆满举行</h1>"
                "<p>本周六,我校迎来了一年一度的<strong>校园开放日</strong>,"
                "吸引了众多家长与学生前来参观。</p>"
                "<p>活动设置了实验室体验、社团展示、学长答疑等多个环节,现场气氛热烈。</p>"
                "<img src='https://example.edu/img/openday.jpg' alt='开放日现场'/>"
            ),
        },
        {
            "url": "https://example.edu/news/2",
            "title": "图书馆延长期末考试期间开放时间",
            "author": "图书馆",
            "pub_time": "2026-06-29T18:30:00",
            "source_mp_name": "阳光校园",
            "is_original_marked": False,
            "cover_url": "",
            "raw_html": (
                "<h2>图书馆延长开放时间通知</h2>"
                "<p>为配合期末备考,图书馆自下周起延长开放至<strong>23:00</strong>。</p>"
                "<ul><li>周一至周五 08:00-23:00</li><li>周末 09:00-22:00</li></ul>"
            ),
        },
        {
            "url": "https://example.edu/news/3",
            "title": "我校学子在全国数学建模竞赛中获奖",
            "author": "教务处",
            "pub_time": "2026-06-28T10:15:00",
            "source_mp_name": "阳光校园",
            # 原创声明文章:用于演示原创转载未授权拦截
            "is_original_marked": True,
            "cover_url": "https://example.edu/img/math.jpg",
            "raw_html": (
                "<h1>喜报:我校学子在全国数学建模竞赛中获奖</h1>"
                "<p>近日,全国大学生数学建模竞赛结果揭晓,我校代表队斩获一等奖。</p>"
                "<blockquote>本文为原创内容,转载请授权。</blockquote>"
                "<p>指导教师表示,团队在为期三天的比赛中通宵奋战,最终提交了高质量论文。</p>"
            ),
        },
        {
            "url": "https://example.edu/news/4",
            "title": "校园食堂推出夏季新菜单",
            "author": "后勤集团",
            "pub_time": "2026-06-27T12:00:00",
            "source_mp_name": "阳光校园",
            "is_original_marked": False,
            "cover_url": "",
            "raw_html": (
                "<h2>夏季新菜单上线</h2>"
                "<p>本季度食堂新增<em>凉面</em>、酸梅汤等消暑餐品,欢迎同学们品尝。</p>"
                "<table><thead><tr><th>窗口</th><th>特色</th></tr></thead>"
                "<tbody><tr><td>一楼</td><td>凉面</td></tr>"
                "<tr><td>二楼</td><td>冷饮</td></tr></tbody></table>"
            ),
        },
        {
            "url": "https://example.edu/news/5",
            "title": "关于暑期社会实践报名的通知",
            "author": "团委",
            "pub_time": "2026-06-26T08:45:00",
            "source_mp_name": "阳光校园",
            "is_original_marked": False,
            "cover_url": "",
            "raw_html": (
                "<h2>暑期社会实践报名启动</h2>"
                "<p>报名截止日期为 <strong>7 月 10 日</strong>,请有意向的同学尽快提交材料。</p>"
                "<p>咨询请联系团委办公室。</p>"
            ),
        },
    ],
    "tech": [
        {
            "url": "https://example.tech/post/1",
            "title": "大模型推理成本一年下降十倍",
            "author": "科技观察",
            "pub_time": "2026-07-01T09:00:00",
            "source_mp_name": "极客前沿",
            "is_original_marked": False,
            "cover_url": "https://example.tech/img/llm.jpg",
            "raw_html": (
                "<h1>大模型推理成本一年下降十倍</h1>"
                "<p>随着芯片与推理框架的持续优化,主流大模型的单位推理成本大幅下降。</p>"
                "<p>业内预计,这将进一步推动 AI 应用的规模化落地。</p>"
            ),
        },
        {
            "url": "https://example.tech/post/2",
            "title": "开源社区发布新一代向量数据库",
            "author": "开源之道",
            "pub_time": "2026-06-30T14:20:00",
            "source_mp_name": "极客前沿",
            "is_original_marked": True,
            "cover_url": "",
            "raw_html": (
                "<h1>新一代向量数据库发布</h1>"
                "<blockquote>原创首发,未经授权禁止转载。</blockquote>"
                "<p>该数据库在召回率与延迟上均有显著提升,支持混合检索。</p>"
            ),
        },
        {
            "url": "https://example.tech/post/3",
            "title": "边缘计算在物联网中的应用实践",
            "author": "云原生笔记",
            "pub_time": "2026-06-29T11:00:00",
            "source_mp_name": "极客前沿",
            "is_original_marked": False,
            "cover_url": "",
            "raw_html": (
                "<h2>边缘计算实践</h2>"
                "<p>把计算下沉到边缘节点,可显著降低网络回传延迟。</p>"
                "<ul><li>低延迟</li><li>节省带宽</li><li>数据本地化</li></ul>"
            ),
        },
        {
            "url": "https://example.tech/post/4",
            "title": "Rust 在系统编程领域的崛起",
            "author": "编程日报",
            "pub_time": "2026-06-28T16:40:00",
            "source_mp_name": "极客前沿",
            "is_original_marked": False,
            "cover_url": "",
            "raw_html": (
                "<h2>Rust 的崛起</h2>"
                "<p>凭借内存安全与零成本抽象,Rust 正被越来越多的基础设施项目采用。</p>"
            ),
        },
        {
            "url": "https://example.tech/post/5",
            "title": "如何为团队引入可观测性体系",
            "author": "SRE 实录",
            "pub_time": "2026-06-27T10:05:00",
            "source_mp_name": "极客前沿",
            "is_original_marked": False,
            "cover_url": "",
            "raw_html": (
                "<h2>可观测性入门</h2>"
                "<p>指标、日志、链路追踪三支柱缺一不可。</p>"
                "<p>从核心链路开始逐步铺开,避免一次性铺满造成噪声。</p>"
            ),
        },
    ],
}

_DEFAULT_DATASET = "campus"


@register
class MockAdapter(SourceAdapter):
    """离线样例适配器。"""

    adapter_type = "mock"

    def _rows(self) -> list[dict[str, Any]]:
        name = str(self.config.get("dataset") or _DEFAULT_DATASET)
        return _DATASETS.get(name, _DATASETS[_DEFAULT_DATASET])

    async def fetch_list(
        self, cursor: dict[str, Any]
    ) -> tuple[list[ArticleMeta], dict[str, Any]]:
        metas = [
            ArticleMeta(
                url=r["url"],
                title=r["title"],
                pub_time=r.get("pub_time", ""),
                author=r.get("author", ""),
                source_mp_name=r.get("source_mp_name", ""),
                extra={"_key": r["url"]},
            )
            for r in self._rows()
        ]
        # mock 不做增量,游标原样透传(保留调用方已有键)
        return metas, dict(cursor or {})

    async def fetch_detail(self, meta: ArticleMeta) -> ArticleDetail:
        for r in self._rows():
            if r["url"] == meta.url:
                return ArticleDetail(
                    url=r["url"],
                    title=r["title"],
                    pub_time=r.get("pub_time", ""),
                    author=r.get("author", ""),
                    source_mp_name=r.get("source_mp_name", ""),
                    raw_html=r.get("raw_html", ""),
                    cover_url=r.get("cover_url", ""),
                    is_original_marked=bool(r.get("is_original_marked", False)),
                )
        # 清单外的项(理论不出现):回退为空正文详情
        return ArticleDetail(
            url=meta.url,
            title=meta.title,
            pub_time=meta.pub_time,
            author=meta.author,
            source_mp_name=meta.source_mp_name,
        )

    async def healthcheck(self) -> bool:
        # 离线数据集恒可用
        return bool(self._rows())
