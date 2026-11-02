#!/usr/bin/env python3
"""把 data/shares.yaml 构建成可发布的静态站点（web/）。

用法：
    python tools/build_site.py                     # 构建到 web/
    python tools/build_site.py --site-url https://xxx.qoder.site   # 带上正式域名（补 canonical/og/sitemap）
    python tools/build_site.py --no-images         # 跳过图片压缩，纯改文案时更快

卡片正文会预渲染进 index.html（搜索引擎可抓取），同一份数据以 JSON 内嵌供前端检索，
因此站点不依赖任何后端接口，也不额外发起网络请求。

封面与发行包所在的根目录由 tools/paths.py 解析（相对本站点工程），数据文件里不存绝对路径：
那种路径一换机器就失效，而且失效后构建不报错，只是悄悄产出一个没有封面的站点。
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

import paths as path_config

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = SITE_ROOT / "data" / "shares.yaml"
DEFAULT_DOCS = SITE_ROOT / "data" / "docs.yaml"
DEFAULT_OUT = SITE_ROOT / "web"
DEFAULT_SRC = SITE_ROOT / "site"
MAX_WIDTH = 1280
MAX_FULL_WIDTH = 1920
SOFT_LIMIT_MB = 45

CATEGORY_NOTE = {
    "文档处理": "PDF 与文档类工具",
    "证件证照": "证件照与报名照制作",
    "图片处理": "图片修复与批处理",
    "音视频": "音视频转换与压缩",
    "表格数据": "Excel/CSV 批量处理",
    "文件批量": "文件重命名与整理",
    "系统效率": "Windows 桌面效率",
    "办公票据": "发票与票据台账",
}

BRAND = "HRX 软件库"
PAGE_TITLE = "HRX 软件库 - 本地工具下载目录"
PAGE_DESC = (
    "本机能离线运行的 Windows 小工具目录：PDF、证件照、图片、音视频、表格、文件批量与系统效率工具，"
    "按名称或功能关键词搜索，附网盘分享链接与提取码。"
)
PAGE_DESC_WITH_DOCS = PAGE_DESC + "同站另附成套实战文档资料，解压后离线阅读。"

# robots 里显式点名放行：默认组虽然是全放行，但共享域名上的通用规则容易被上游改写，
# 而且 AI 爬虫和搜索引擎分开声明，将来要收紧训练类抓取时不会连带影响收录。
ROBOTS_GROUPS = [
    ("搜索引擎", ["Googlebot", "Bingbot", "Baiduspider", "Sogou web spider", "360Spider", "YisouSpider", "YandexBot", "Applebot"]),
    ("AI 检索类：回答中带来源链接，能带来回访", ["OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot", "DuckAssistBot"]),
    ("AI 训练类：决定内容进不进模型长期记忆", ["GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "Bytespider", "CCBot", "Amazonbot"]),
]


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def entry_links(entry: dict) -> list[dict]:
    """归一化下载渠道：downloads 数组优先，否则回退到 share_url 三件套。"""
    raw = entry.get("downloads")
    if isinstance(raw, dict):
        raw = [raw]
    links = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        links.append(
            {
                "platform": str(item.get("platform") or "").strip(),
                "url": url,
                "code": str(item.get("code") or "").strip(),
                "note": str(item.get("note") or "").strip(),
            }
        )
    if links:
        return links
    url = str(entry.get("share_url") or "").strip()
    if not url:
        return []
    return [
        {
            "platform": str(entry.get("platform") or "").strip(),
            "url": url,
            "code": str(entry.get("share_code") or "").strip(),
            "note": "",
        }
    ]


def load_entries(path: Path, kind: str = "software") -> tuple[list[dict], dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = doc.get("shares") if kind == "software" else doc.get("docs")
    entries = [e for e in (rows or []) if isinstance(e, dict)]
    # 只有挂了网盘链接的条目才上架；没链接的留在数据里当待办，不占页面
    visible = []
    for e in entries:
        if e.get("status") == "hidden":
            continue
        links = entry_links(e)
        if not links:
            continue
        e["_links"] = links
        e["kind"] = kind
        visible.append(e)
    visible.sort(key=lambda e: (e.get("status") == "coming_soon", str(e.get("slug"))))
    return visible, doc.get("site") or {}


def copy_brand_assets(src: Path, out: Path) -> None:
    """公众号二维码不是条目封面，--no-images 时也要复制。"""
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    qr_src = src / "assets" / "qrcode_wc.png"
    if not qr_src.is_file():
        print(f"警告：缺少二维码素材 {qr_src}，页面上的公众号二维码会显示为空白。")
        return
    (img_dir / "wechat-qr.png").write_bytes(qr_src.read_bytes())


def make_images(entries: list[dict], root: Path, out: Path) -> int:
    """按 root/条目目录/条目里的相对路径 取封面，返回「声明了封面却没取到」的条数。

    这种失配不会报错，只会让卡片静默退化成排版封面，所以必须数出来打印给人看。
    """
    try:
        from PIL import Image
    except ImportError:
        print("提示：未安装 Pillow，跳过封面处理（卡片将使用排版封面）。")
        return 0
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    misses = 0
    for entry in entries:
        rel = entry.get("image") or ""
        src = (root / entry["slug"] / rel) if rel else None
        entry["_asset_full"] = ""
        if not src or not src.is_file():
            entry["_asset"] = ""
            if rel:
                misses += 1
            continue
        stem = re.sub(r"[^a-z0-9]+", "", entry["slug"].lower()) or f"e{entries.index(entry)}"
        if entry.get("image_kind") == "icon":
            dst = img_dir / f"{stem}-icon.png"
            with Image.open(src) as im:
                im.convert("RGBA").resize((128, 128), Image.LANCZOS).save(dst, optimize=True)
            entry["_asset"] = f"images/{dst.name}"
            continue
        dst = img_dir / f"{stem}-cover.webp"
        dst_full = img_dir / f"{stem}-full.webp"
        with Image.open(src) as im:
            base = im.convert("RGB")
            full = base if base.width <= MAX_FULL_WIDTH else base.resize(
                (MAX_FULL_WIDTH, round(base.height * MAX_FULL_WIDTH / base.width)), Image.LANCZOS
            )
            card = base if base.width <= MAX_WIDTH else base.resize(
                (MAX_WIDTH, round(base.height * MAX_WIDTH / base.width)), Image.LANCZOS
            )
            full.save(dst_full, "WEBP", quality=82, method=6)
            card.save(dst, "WEBP", quality=78, method=6)
        entry["_asset"] = f"images/{dst.name}"
        entry["_asset_full"] = f"images/{dst_full.name}"
    return misses


def display_path(path: Path) -> str:
    """试构建常把产物写到仓库外的临时目录，相对路径显示不了就退回绝对路径。"""
    try:
        return path.relative_to(SITE_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def chip_label(feature: str) -> str:
    """卡片上只放短标签，完整句子留在详情里。"""
    label = feature.split("：")[0].strip() if "：" in feature else feature.strip()
    if len(label) > 14:
        label = label[:13].rstrip("，,、/ ") + "…"
    return label


def card_html(entry: dict, index: int) -> str:
    slug = entry["slug"]
    docs = entry.get("kind") == "docs"
    soon = entry.get("status") == "coming_soon"
    feats = [f for f in (entry.get("features") or []) if f]
    chips = "".join(f"<li>{esc(chip_label(f))}</li>" for f in feats[:4])
    extra = f'<li class="more">+{len(feats) - 4}</li>' if len(feats) > 4 else ""
    cover_note = "封面待补" if docs else "界面截图待补"
    if entry.get("_asset"):
        if entry.get("image_kind") == "icon":
            cover = (
                f'<div class="cover cover-typeset"><img src="{esc(entry["_asset"])}" alt="" loading="lazy">'
                f'<span>{esc(entry.get("name_en") or entry.get("exe_name") or "")}</span>'
                f'<span>{cover_note}</span></div>'
            )
        else:
            alt = f'{esc(entry["name"])} 封面' if docs else f'{esc(entry["name"])} 软件界面截图'
            cover = (
                f'<div class="cover"><img src="{esc(entry["_asset"])}" alt="{alt}" loading="lazy">'
                + (f'<span class="ribbon soon">即将上架</span>' if soon else "")
                + "</div>"
            )
    else:
        cover = (
            f'<div class="cover cover-typeset"><span class="big">{esc(entry["name"])}</span>'
            f'<span>{esc(entry.get("name_en") or "")}</span><span>{cover_note}</span></div>'
        )
    platform = (entry.get("platform") or "").strip()
    links = entry.get("_links") or []
    primary = links[0] if links else None
    platform = primary["platform"] if primary else platform
    platform_label = platform + (f" +{len(links) - 1}" if len(links) > 1 else "")
    primary_code = primary["code"] if primary else ""
    cta_label = "获取资料" if docs else "获取安装包"
    if soon:
        cta = '<button class="btn" type="button" disabled>即将上架</button>'
    elif primary:
        code_attr = f' data-code="{esc(primary_code)}"' if primary_code else ""
        cta = f'<a class="btn" href="{esc(primary["url"])}" target="_blank" rel="noopener"{code_attr}>{cta_label}</a>'
    else:
        cta = '<button class="btn" type="button" disabled>暂未开放下载</button>'
    facts = [
        entry.get("chapters") and f"共 {entry['chapters']} 篇" if docs else entry.get("version") and f"v{entry['version']}",
        entry.get("size_mb") and f"{entry['size_mb']} MB",
        entry.get("category"),
        platform_label,
        primary_code and f"提取码 {primary_code}",
    ]
    pills = "".join(f'<span class="pill">{esc(t)}</span>' for t in facts if t)
    group_label = "资料" if docs else "软件"
    return f"""
    <article class="card" id="{esc(slug)}" data-id="{esc(slug)}" data-group="{group_label}">
      {cover}
      <div class="card-body">
        <div class="title-row">
          <h3 class="hl">{esc(entry.get("name"))}</h3>
          <span class="name-en">{esc(entry.get("name_en"))}</span>
        </div>
        <div class="meta-row">{pills}</div>
        <p class="summary hl">{esc(entry.get("summary"))}</p>
        <ul class="feats">{chips}{extra}</ul>
        <div class="card-foot">
          {cta}
          <a class="btn ghost btn-copy" href="#{esc(slug)}" data-more="{esc(slug)}">详情</a>
        </div>
      </div>
    </article>"""


def json_payload(entries: list[dict]) -> str:
    """内嵌给前端的数据。封面一律用相对路径：站点部署在域名根目录，
    绝对地址会随域名变化而失效，只有 og:image 需要绝对 URL。"""
    keep = ("slug", "name", "name_en", "exe_name", "version", "size_mb", "status", "category", "summary",
            "description", "features", "keywords", "aliases", "chapters")
    rows = []
    for e in entries:
        row = {k: e.get(k) or ([] if k in ("features", "keywords", "aliases") else "") for k in keep}
        row["id"] = e["slug"]
        row["kind"] = e.get("kind") or "software"
        row["cover"] = e.get("_asset") or ""
        row["cover_full"] = e.get("_asset_full") or ""
        row["links"] = e.get("_links") or []
        row["updated"] = e.get("updated") or ""
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def app_item(entry: dict, site_url: str) -> dict:
    """单条内容的结构化实体。片段地址目前就是该条目的可寻址位置，
    等详情页拆成独立 URL 后只改 url 一行。"""
    links = entry.get("_links") or []
    docs = entry.get("kind") == "docs"
    item = {
        "@type": "CreativeWork" if docs else "SoftwareApplication",
        "name": entry.get("name"),
        "alternateName": entry.get("name_en") or entry.get("exe_name") or "",
        "description": entry.get("summary") or entry.get("description") or "",
        "featureList": [f for f in (entry.get("features") or []) if f],
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "CNY"},
        "url": f"{site_url}/#{entry['slug']}" if site_url else "",
    }
    if docs:
        item["inLanguage"] = "zh-CN"
        if entry.get("chapters"):
            item["numberOfItems"] = entry["chapters"]
    else:
        item["operatingSystem"] = "Windows 10 / Windows 11 64 位"
        item["applicationCategory"] = "UtilitiesApplication"
        item["softwareVersion"] = entry.get("version") or ""
    if entry.get("size_mb"):
        item["fileSize"] = f"{entry['size_mb']} MB"
    if entry.get("updated"):
        item["dateModified"] = entry["updated"]
    if entry.get("status") != "coming_soon" and links:
        item["downloadUrl"] = links[0]["url"]
    cover = entry.get("_asset_full") or entry.get("_asset") or ""
    if cover and site_url:
        item["image"] = f"{site_url}/{cover}"
    return item


def json_ld(entries: list[dict], site_url: str, desc: str) -> str:
    doc = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{site_url}/#website",
                "url": f"{site_url}/",
                "name": BRAND,
                "description": desc,
                "inLanguage": "zh-CN",
                "publisher": {"@type": "Person", "@id": f"{site_url}/#author", "name": "HRX"},
            },
            {
                "@type": "ItemList",
                "name": PAGE_TITLE,
                "numberOfItems": len(entries),
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "item": app_item(e, site_url)}
                    for i, e in enumerate(entries)
                ],
            },
        ],
    }
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def head_extra(entries: list[dict], site_url: str, desc: str) -> str:
    lines = [
        '<meta property="og:site_name" content="HRX 软件库">',
        '<meta property="og:locale" content="zh_CN">',
    ]
    if site_url:
        # og:image 优先真实界面截图；文档条目只有海报，也不该让分享卡空着图
        first_cover = next((e["_asset"] for e in entries if e.get("_asset") and e.get("image_kind") == "screenshot"), "")
        if not first_cover:
            first_cover = next((e["_asset"] for e in entries if e.get("_asset")), "")
        lines += [
            f'<link rel="canonical" href="{esc(site_url)}/">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:title" content="{esc(PAGE_TITLE)}">',
            f'<meta property="og:description" content="{esc(desc)}">',
            f'<meta property="og:url" content="{esc(site_url)}/">',
        ]
        if first_cover:
            lines.append(f'<meta property="og:image" content="{esc(site_url + "/" + first_cover)}">')
        lines += [
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{esc(PAGE_TITLE)}">',
            f'<meta name="twitter:description" content="{esc(desc)}">',
            f'<script type="application/ld+json">{json_ld(entries, site_url, desc)}</script>',
        ]
    return "\n".join(lines)


def llms_row(e: dict, base: str) -> str:
    links = e.get("_links") or []
    plats = "、".join(l["platform"] for l in links if l["platform"]) or "网盘"
    codes = "；".join(f"{l['platform']} 提取码 {l['code']}" for l in links if l["code"])
    facts = " · ".join(
        t for t in [
            e.get("category") or "",
            f"共 {e['chapters']} 篇" if e.get("chapters") else "",
            f"v{e['version']}" if e.get("version") else "",
            f"{e['size_mb']} MB" if e.get("size_mb") else "",
            f"下载渠道：{plats}" + (f"（{codes}）" if codes else ""),
        ] if t
    )
    feats = "；".join(f for f in (e.get("features") or [])[:4] if f)
    alias = "、".join(a for a in (e.get("aliases") or [])[:5] if a)
    row = f"- [{e.get('name')}]({base}/#{e['slug']}): {e.get('summary') or ''}（{facts}）"
    if feats:
        row += f" {'篇章：' if e.get('kind') == 'docs' else '功能：'}{feats}。"
    if alias:
        row += f" 也叫 {alias}。"
    if e.get("name_en"):
        row += f" 英文名 {e['name_en']}。"
    return row


def llms_txt(entries: list[dict], docs: list[dict], site_url: str, updated: str) -> str:
    """面向 AI 引擎的纯文本目录：逐条写清是什么、什么版本、能干什么、去哪下载。"""
    base = site_url or ""
    out = [
        f"# {BRAND}",
        "",
        "> 本机运行的 Windows 免费桌面小工具目录。绿色免安装、不需要联网、文件不上传，"
        "PDF 合并拆分、证件照、去水印、文件去重等常用办公操作全部在自己电脑上完成。"
        + ("另附成套的实战文档资料，离线可读。" if docs else ""),
        f"> 个人开发者 HRX 维护，共 {len(entries)} 款软件"
        + (f"、{len(docs)} 份文档资料" if docs else "")
        + f"，数据更新于 {updated}。",
        "",
        "## 站点",
        f"- [全部软件目录]({base}/): 卡片式目录，按名称、英文名、功能关键词检索；"
        "「详情」给出完整功能清单与全部下载渠道",
        "",
        "## 软件",
    ]
    out += [llms_row(e, base) for e in entries]
    if docs:
        out += ["", "## 文档资料"] + [llms_row(e, base) for e in docs]
    cats = [c for c in dict.fromkeys(e.get("category") for e in entries + docs) if c]
    out += [
        "",
        "## 分类",
        *(f"- {c}：{CATEGORY_NOTE[c]}" if c in CATEGORY_NOTE else f"- {c}" for c in cats),
        "",
        "## 说明",
        "- 全部软件免费获取，无内购、无广告、不收集使用数据。",
        "- 系统要求：Windows 10 / Windows 11 64 位；解压即用，不需要装运行库。",
        "- 下载经夸克网盘、UC 网盘等渠道分发，提取码在页面上直接展示并可一键复制。",
        "- 分享失效或想要还没做出的工具：微信公众号「HRX 软件库」可提需求，也接受定制开发。",
        "",
    ]
    return "\n".join(out)


def robots_txt(site_url: str) -> str:
    """默认组已全放行，显式点名是为了：上游若改共享域通用规则，本站的收录与 AI 抓取组仍在；
    且训练类与检索类分开声明，将来收紧训练抓取不会连带把收录一起关掉。"""
    lines = ["# 全站开放抓取：无后台、无接口、无用户数据，页面内容即全部内容。", "User-agent: *", "Allow: /", ""]
    for label, agents in ROBOTS_GROUPS:
        lines.append(f"# {label}")
        for ua in agents:
            lines += [f"User-agent: {ua}", "Allow: /", ""]
    if site_url:
        lines.append(f"Sitemap: {site_url}/sitemap.xml")
    return "\n".join(lines).strip() + "\n"


def chips_html(entries: list[dict]) -> str:
    cats: list[str] = []
    for e in entries:
        c = e.get("category") or ""
        if c and c not in cats:
            cats.append(c)
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.get("category") or ""] = counts.get(e.get("category") or "", 0) + 1
    parts = ['<button class="chip" type="button" data-cat="全部" aria-pressed="true">全部<span class="n">%d</span></button>' % len(entries)]
    for c in cats:
        parts.append(f'<button class="chip" type="button" data-cat="{esc(c)}" aria-pressed="false">{esc(c)}<span class="n">{counts[c]}</span></button>')
    return "".join(parts)


def resolve_roots(args: argparse.Namespace) -> dict[str, path_config.Root]:
    overrides = {k: str(v) for k, v in (("jobs_root", args.jobs_root), ("docs_root", args.docs_root)) if v}
    return path_config.resolve_roots(overrides or None)


def root_missing_error(root: path_config.Root, label: str) -> int:
    """换机器后最常见的一课：路径不对就明确失败，别产出一个没有封面的站点。"""
    print(f"{label}根目录不存在：{root.path.as_posix()}")
    print(f"  取值 {root.value}（来源：{root.source}）")
    print("  修法：改 data/paths.yaml，或 python tools/paths.py set --local 指定本机位置，或构建时加 --jobs-root/--docs-root。")
    print("  查看全部取值来源：python tools/paths.py show")
    return 2


def docs_block_html(docs: list[dict]) -> str:
    """文档区块：没有可上架的条目时整段不出现，免得留下一个空标题。"""
    if not docs:
        return ""
    cards = "".join(card_html(e, i) for i, e in enumerate(docs))
    return (
        '\n<section class="group" id="library" aria-labelledby="library-title">\n'
        '  <div class="group-head">\n'
        '    <h2 class="group-title" id="library-title">文档资料</h2>\n'
        "    <p class=\"group-note\">成套教程与速查文档，解压后离线阅读，不需要联网。</p>\n"
        "  </div>\n"
        f'  <div class="catalog">{cards}\n  </div>\n'
        "</section>"
    )


def build(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    if not data_path.is_file():
        print(f"找不到数据文件：{data_path}\n先跑 python tools/scan_jobs.py 生成。")
        return 2
    entries, site = load_entries(data_path)
    docs_path = Path(args.docs_data)
    docs: list[dict] = []
    docs_site: dict = {}
    if docs_path.is_file():
        docs, docs_site = load_entries(docs_path, kind="docs")
    all_rows = [e for e in ((yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}).get("shares") or [])]
    all_docs = [e for e in ((yaml.safe_load(docs_path.read_text(encoding="utf-8")) or {}).get("docs") or [])] if docs_path.is_file() else []
    backlog = [
        e.get("name") or e.get("slug") or "?"
        for e in all_rows + all_docs
        if e.get("status") != "hidden" and not entry_links(e)
    ]
    combined = entries + docs
    if not combined:
        print("没有可上架的条目：所有条目都还没挂网盘链接。")
        print(f"待挂链接 {len(backlog)} 条，填好数据文件里的 share_url 后重新构建。")
        return 0
    roots = resolve_roots(args)
    jobs_root = roots["jobs_root"].path
    docs_root = roots["docs_root"].path
    if not args.no_images:
        if any(e.get("image") for e in entries) and not roots["jobs_root"].exists:
            return root_missing_error(roots["jobs_root"], "软件")
        if any(e.get("image") for e in docs) and not roots["docs_root"].exists:
            return root_missing_error(roots["docs_root"], "文档")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.html"):
        stale.unlink()
    for stale in (out / "images").glob("*"):
        stale.unlink()  # 下架条目的封面不该继续留在发布包里

    misses = 0
    if args.no_images:
        for e in combined:
            e["_asset"] = ""
            e["_asset_full"] = ""
    else:
        misses = make_images(entries, jobs_root, out) + make_images(docs, docs_root, out)

    src = Path(args.src)
    copy_brand_assets(src, out)
    site_url = (args.site_url or "").rstrip("/")
    desc = PAGE_DESC_WITH_DOCS if docs else PAGE_DESC
    updated = str(site.get("updated") or docs_site.get("updated") or date.today())
    count_line = f"共 {len(entries)} 款软件" + (f" · {len(docs)} 份资料" if docs else "")
    template = (src / "template.html").read_text(encoding="utf-8")
    page = (
        template.replace("{{TITLE}}", PAGE_TITLE)
        .replace("{{DESC}}", esc(desc))
        .replace("{{HEAD}}", head_extra(combined, site_url, desc))
        .replace("{{CHIPS}}", chips_html(combined))
        .replace("{{CARDS}}", "".join(card_html(e, i) for i, e in enumerate(entries)))
        .replace("{{DOCS_BLOCK}}", docs_block_html(docs))
        .replace("{{DATA}}", json_payload(combined))
        .replace("{{COUNT}}", count_line)
        .replace("{{UPDATED}}", updated)
        .replace("{{MAINTAINER}}", "HRX")
    )
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "style.css").write_text((src / "style.css").read_text(encoding="utf-8"), encoding="utf-8")
    (out / "app.js").write_text((src / "app.js").read_text(encoding="utf-8"), encoding="utf-8")
    (out / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1f4fd8"/>'
        '<path d="M18 20h9l7 12 7-12h9v24h-8V33l-6 10h-4l-6-10v11h-8z" fill="#fff"/></svg>\n',
        encoding="utf-8",
    )
    (out / "robots.txt").write_text(robots_txt(site_url), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(entries, docs, site_url, updated), encoding="utf-8")
    if site_url:
        # 条目各自带 updated，lastmod 取全站最近一次真实内容变更；
        # 一律写成构建日会让抓取器把整站的更新信号当成噪声。
        lastmod = max([str(e["updated"]) for e in combined if e.get("updated")] + [updated])
        urls = "\n".join([f"  <url><loc>{esc(site_url)}/</loc><lastmod>{esc(lastmod)}</lastmod></url>"])
        (out / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n',
            encoding="utf-8",
        )
    elif (out / "sitemap.xml").is_file():
        (out / "sitemap.xml").unlink()  # 不带域名构建时，别把旧域名的 sitemap 留在发布包里

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1048576
    no_cover = [e["name"] for e in entries if e.get("image_kind") != "screenshot"]
    no_doc_cover = [e["name"] for e in docs if not e.get("image")]
    print(
        f"已上架 {len(entries)} 款软件"
        + (f" + {len(docs)} 份资料" if docs else "")
        + f" → {display_path(out)}/  （{total:.2f} MB）"
    )
    if entries:
        print(f"软件根目录：{jobs_root.as_posix()}（来源：{roots['jobs_root'].source}）")
    if docs:
        print(f"文档根目录：{docs_root.as_posix()}（来源：{roots['docs_root'].source}）")
    if misses:
        print(f"警告：{misses} 条声明了封面却没取到文件，卡片会退化成排版封面——请核对 image 相对路径与根目录配置。")
    if backlog:
        print(f"未挂链接、暂不显示 {len(backlog)} 条：" + "、".join(backlog))
    if no_cover:
        print("缺真实界面截图：" + "、".join(no_cover))
    if no_doc_cover:
        print("文档缺封面图：" + "、".join(no_doc_cover))
    if total > SOFT_LIMIT_MB:
        print(f"警告：产物 {total:.1f} MB 接近发布上限，请下调封面尺寸或质量。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="构建静态站点")
    p.add_argument("--data", default=str(DEFAULT_DATA))
    p.add_argument("--docs-data", default=str(DEFAULT_DOCS), help="文档数据文件（不存在则站点不含文档区块）")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--src", default=str(DEFAULT_SRC))
    p.add_argument("--jobs-root", type=Path, default=None, help="软件根目录（默认取 data/paths.yaml 的 jobs_root）")
    p.add_argument("--docs-root", type=Path, default=None, help="文档根目录（默认取 data/paths.yaml 的 docs_root）")
    p.add_argument("--site-url", default="", help="正式发布域名，用于 canonical/og/sitemap")
    p.add_argument("--no-images", action="store_true", help="跳过封面压缩")
    args = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
