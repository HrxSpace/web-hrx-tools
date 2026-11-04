#!/usr/bin/env python3
"""把 data/shares.yaml 构建成可发布的静态站点（web/）。

用法：
    python tools/build_site.py                     # 构建到 web/（站点名与域名取 data/shares.yaml 的 site: 段）
    python tools/build_site.py --offline           # 本地预览：不产 canonical/og/JSON-LD/sitemap，这种产物别发布
    python tools/build_site.py --site-url https://新域名   # 换域名时临时覆盖配置，canonical/sitemap 跟着走
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

import manual
import paths as path_config
from seo_check import display_width

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = SITE_ROOT / "data" / "shares.yaml"
DEFAULT_DOCS = SITE_ROOT / "data" / "docs.yaml"
DEFAULT_OUT = SITE_ROOT / "web"
DEFAULT_SRC = SITE_ROOT / "site"
MAX_WIDTH = 1280
MAX_FULL_WIDTH = 1920
SOFT_LIMIT_MB = 45
# 详情页正文的下限：低于这个量的页面接不住长尾搜索，与其推广不如先承认它薄。
MIN_PAGE_HAN = 600

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

# 站点名与正式发布域名只存在 data/shares.yaml 的 site: 段。写死在这里时，改名要动 5 个地方，
# 而域名靠命令行传、忘传就把 canonical/og/JSON-LD/sitemap 整段静默丢掉——两个都是已经踩过的坑。
PAGE_DESC = (
    "本机能离线运行的 Windows 小工具目录：PDF、证件照、图片、音视频、表格、文件批量与系统效率工具，"
    "按名称或功能关键词搜索，附网盘分享链接与提取码。"
)
PAGE_DESC_WITH_DOCS = PAGE_DESC + "同站另附成套实战文档资料，解压后离线阅读。"


def page_title(brand: str, has_docs: bool) -> str:
    """首页标题只回答「这个站是什么」。功能长尾词（PDF 拆分、OCR）由详情页承接，堆在这里反而稀释。"""
    tail = "Windows 离线小工具与实战资料" if has_docs else "Windows 离线小工具"
    return f"{brand} - {tail}（免安装·不上传）"

# robots 里显式点名放行：默认组虽然是全放行，但共享域名上的通用规则容易被上游改写，
# 而且 AI 爬虫和搜索引擎分开声明，将来要收紧训练类抓取时不会连带影响收录。
ROBOTS_GROUPS = [
    ("搜索引擎", ["Googlebot", "Bingbot", "Baiduspider", "Sogou web spider", "360Spider", "YisouSpider", "YandexBot", "Applebot"]),
    ("AI 检索类：回答中带来源链接，能带来回访", ["OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot", "DuckAssistBot"]),
    ("AI 训练类：决定内容进不进模型长期记忆", ["GPTBot", "ClaudeBot", "anthropic-ai", "Google-Extended", "Bytespider", "CCBot", "Amazonbot"]),
]


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def han_count(text: str) -> int:
    return len(re.findall(r"[一-鿿]", text))


def body_han(page_html: str) -> int:
    """只数正文区的汉字：整页统计会被 JSON-LD 与 meta 灌水，薄页就再也不会被报出来。"""
    body = re.search(r"<main.*?</main>", page_html, re.S)
    return han_count(re.sub(r"<[^>]+>", " ", body.group(0) if body else ""))


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


def resolve_site(site: dict, args: argparse.Namespace) -> tuple[str, str, str, int]:
    """站点品牌、公众号名与正式发布域名。缺配置直接失败并说清改哪里：
    这两种情况过去都会让构建「成功」，只是产出一个没名字或没收录信号的裸页。"""
    brand = str(site.get("name") or "").strip()
    if not brand:
        print("site.name 缺失：品牌名是页面标题、<h1>、og:site_name 与 llms.txt 首行的唯一来源。")
        print("  修法：在 data/shares.yaml 顶部的 site: 段补一行 name: HRX 资源库")
        return "", "", "", 2
    wechat = str(site.get("wechat_name") or "").strip()
    if not wechat:
        print("site.wechat_name 缺失：页面上「微信公众号 ·」后面那个名字得有出处。")
        print("  回落成站点名会写出与真实公众号不符的名字，读者扫码就对不上号——所以要必填。")
        print("  修法：在 data/shares.yaml 顶部的 site: 段补一行 wechat_name: HRX 工具库")
        return brand, "", "", 2
    if args.offline:
        # 本地预览故意不写线上域名：这种产物会被 seo_check 判不通过，正好挡住"预览包误发布"。
        return brand, wechat, "", 0
    site_url = str(args.site_url or site.get("url") or "").strip().rstrip("/")
    if not site_url:
        print("site.url 未配置且没加 --offline：canonical、og、JSON-LD、sitemap 全都不会产出，这样的产物不要发布。")
        print("  正式发布：在 data/shares.yaml 的 site: 段补一行 url: https://你的域名")
        print("  本地预览：python tools/build_site.py --offline")
        return brand, wechat, "", 2
    return brand, wechat, site_url, 0


def write_verify_files(site: dict, out: Path) -> list[str]:
    """站长验证文件由构建器产出，不许手工放进 web/。

    原因很实际：构建每次会清空 web/ 下的 HTML，手工放进去的 googleXXXX.html
    下一次构建就没了，而 Google 的验证会悄悄失效——届时排名数据断档，谁也想不起是构建干的。
    """
    written: list[str] = []
    for item in site.get("verify") or []:
        name = str((item or {}).get("file") if isinstance(item, dict) else "").strip()
        text = str(item.get("text") if isinstance(item, dict) else "")
        if not name or not text:
            print(f"警告：site.verify 有条目缺 file 或 text，已跳过：{item}")
            continue
        (out / name).write_text(text, encoding="utf-8")
        written.append(name)
    return written


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


def chip_label(feature: str) -> str:
    """卡片上只放短标签，完整句子留在详情里。"""
    label = feature.split("：")[0].strip() if "：" in feature else feature.strip()
    if len(label) > 14:
        label = label[:13].rstrip("，,、/ ") + "…"
    return label


def card_html(entry: dict, index: int, paths: dict[str, str]) -> str:
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
    # 标题链到详情页（抓取器与转发地址都走这条），详情按钮仍走原位弹窗（体验不变）
    return f"""
    <article class="card" id="{esc(slug)}" data-id="{esc(slug)}" data-group="{group_label}">
      {cover}
      <div class="card-body">
        <div class="title-row">
          <h3><a class="hl name-link" href="{esc(paths.get(slug) or '#' + slug)}">{esc(entry.get("name"))}</a></h3>
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


def app_item(entry: dict, url: str, site_url: str) -> dict:
    """单条内容的结构化实体。url 必须是详情页自己的地址——
    指向首页片段（/#slug）的话，实体绑不到 URL 上，等于白写。"""
    links = entry.get("_links") or []
    docs = entry.get("kind") == "docs"
    item = {
        "@type": "CreativeWork" if docs else "SoftwareApplication",
        "name": entry.get("name"),
        "alternateName": entry.get("name_en") or entry.get("exe_name") or "",
        "description": entry.get("summary") or entry.get("description") or "",
        "featureList": [f for f in (entry.get("features") or []) if f],
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "CNY"},
        "url": url,
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


def json_ld(entries: list[dict], site_url: str, desc: str, brand: str, title: str, paths: dict[str, str]) -> str:
    doc = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{site_url}/#website",
                "url": f"{site_url}/",
                "name": brand,
                "description": desc,
                "inLanguage": "zh-CN",
                "publisher": {"@type": "Person", "@id": f"{site_url}/#author", "name": "HRX"},
            },
            {
                "@type": "ItemList",
                "name": title,
                "numberOfItems": len(entries),
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1, "item": app_item(e, absolute(site_url, paths[e["slug"]]), site_url)}
                    for i, e in enumerate(entries)
                ],
            },
        ],
    }
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def head_extra(entries: list[dict], site_url: str, desc: str, brand: str, title: str, paths: dict[str, str]) -> str:
    lines = [
        f'<meta property="og:site_name" content="{esc(brand)}">',
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
            f'<meta property="og:title" content="{esc(title)}">',
            f'<meta property="og:description" content="{esc(desc)}">',
            f'<meta property="og:url" content="{esc(site_url)}/">',
        ]
        if first_cover:
            lines.append(f'<meta property="og:image" content="{esc(site_url + "/" + first_cover)}">')
        lines += [
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{esc(title)}">',
            f'<meta name="twitter:description" content="{esc(desc)}">',
            f'<script type="application/ld+json">{json_ld(entries, site_url, desc, brand, title, paths)}</script>',
        ]
    return "\n".join(lines)


def llms_row(e: dict, base: str, paths: dict[str, str]) -> str:
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
    row = f"- [{e.get('name')}]({base}/{paths[e['slug']]}): {e.get('summary') or ''}（{facts}）"
    if feats:
        row += f" {'篇章：' if e.get('kind') == 'docs' else '功能：'}{feats}。"
    if alias:
        row += f" 也叫 {alias}。"
    if e.get("name_en"):
        row += f" 英文名 {e['name_en']}。"
    return row


def llms_txt(entries: list[dict], docs: list[dict], site_url: str, updated: str, brand: str, wechat: str, paths: dict[str, str]) -> str:
    """面向 AI 引擎的纯文本目录：逐条写清是什么、什么版本、能干什么、去哪下载。"""
    base = site_url or ""
    out = [
        f"# {brand}",
        "",
        "> 本机运行的 Windows 免费桌面小工具目录。绿色免安装、不需要联网、文件不上传，"
        "PDF 合并拆分、证件照、去水印、文件去重等常用办公操作全部在自己电脑上完成。"
        + ("另附成套的实战文档资料，离线可读。" if docs else ""),
        f"> 个人开发者 HRX 维护，共 {len(entries)} 款软件"
        + (f"、{len(docs)} 份文档资料" if docs else "")
        + f"，数据更新于 {updated}。",
        "",
        "## 站点",
        f"- [全部资源目录]({base}/): 卡片式首页，按名称、英文名、功能关键词检索；"
        "下面每条资源另有独立页面，含完整功能详解、使用步骤与常见问题",
        "",
        "## 软件",
    ]
    out += [llms_row(e, base, paths) for e in entries]
    if docs:
        out += ["", "## 文档资料"] + [llms_row(e, base, paths) for e in docs]
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
        f"- 分享失效或想要还没做出的工具：微信公众号「{wechat}」可提需求，也接受定制开发。",
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


def docs_block_html(docs: list[dict], paths: dict[str, str]) -> str:
    """文档区块：没有可上架的条目时整段不出现，免得留下一个空标题。"""
    if not docs:
        return ""
    cards = "".join(card_html(e, i, paths) for i, e in enumerate(docs))
    return (
        '\n<section class="group" id="library" aria-labelledby="library-title">\n'
        '  <div class="group-head">\n'
        '    <h2 class="group-title" id="library-title">文档资料</h2>\n'
        "    <p class=\"group-note\">成套教程与速查文档，解压后离线阅读，不需要联网。</p>\n"
        "  </div>\n"
        f'  <div class="catalog">{cards}\n  </div>\n'
        "</section>"
    )


# --------------------------------------------------------------------------- 详情页

# title 预算比 seo_check 的 60 少 2：宁可构建时先缩，也不要发布前被断言拦下来才发现。
TITLE_WIDTH = 58


def ascii_slug(entry: dict) -> str:
    """URL 只用 ASCII：中文名进 URL 会让部分引擎与爬虫做编码歧义处理。
    优先英文名/exe 名；都不是 ASCII 时退回目录名里的 ASCII 片段（W000_WorkBuddy实战… → w000-workbuddy）。
    驼峰要拆成词（PDFSuperToolbox → pdf-super-toolbox）：连成一串的单词丢了词边界，URL 里也是搜索信号。"""
    base = entry.get("name_en") or entry.get("exe_name") or ""
    if not base.isascii():
        base = entry["slug"]
    stem = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])", "-", base)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", stem).lower()
    stem = re.sub(r"-{2,}", "-", stem).strip("-")
    return stem or entry["slug"].split("_")[0].lower()


def page_paths(entries: list[dict]) -> dict[str, str]:
    """slug → 产物内的相对路径。一条内容一个可索引 URL，这是长尾词唯一的承接位。"""
    paths: dict[str, str] = {}
    used: set[str] = set()
    for e in entries:
        folder = "doc" if e.get("kind") == "docs" else "soft"
        stem = ascii_slug(e)
        cand = f"{folder}/{stem}.html"
        if cand in used:  # 英文名撞车时加目录编号，保证两个 URL 都还在
            cand = f"{folder}/{e['slug'].split('_')[0].lower()}-{stem}.html"
        used.add(cand)
        paths[e["slug"]] = cand
    return paths


def absolute(site_url: str, path: str) -> str:
    """对外绝对地址。没有站点域名时返回空串：结构化数据里的相对 URL 会被引擎当成无效声明。"""
    return f"{site_url}/{path}" if site_url else ""


def title_words(entry: dict, limit: int = 2) -> list[str]:
    """从功能要点里取 2 个短词拼进 title，承接"PDF 拆分"这类任务词搜索。"""
    words: list[str] = []
    for feat in entry.get("features") or []:
        word = re.sub(r"\s+", "", chip_label(feat)).strip("…")
        if 2 <= len(word) <= 8 and word not in words:
            words.append(word)
        if len(words) >= limit:
            break
    return words


def detail_title(entry: dict, brand: str) -> str:
    """标题用固定形状 `{资源名}_{用途}_离线不上传 - {品牌}`，装不下就从后往前丢段落。

    品牌尾巴永远保留（多页一致的实体信号），"离线不上传"是本站区别于其他下载站的
    卖点，优先级放在第二个功能词之前；宁可少一个词，也不把任何一段截成半个词。
    """
    docs = entry.get("kind") == "docs"
    tail = f" - {brand}"
    name = entry.get("name", "")
    action = "_离线阅读" if docs else "_离线不上传"
    lead = ""
    if docs and entry.get("chapters"):
        lead = f"共{entry['chapters']}篇资料"
    else:
        words = title_words(entry, 1)
        lead = words[0] if words else ""
    for body in (f"{name}_{lead}{action}" if lead else "", f"{name}{action}", name):
        if body and display_width(body + tail) <= TITLE_WIDTH:
            return body + tail
    return name + tail  # 名字本身就超预算：不截名字，交给 seo_check 报出来


def detail_desc(entry: dict) -> str:
    docs = entry.get("kind") == "docs"
    bits = [
        entry.get("summary") or entry.get("description") or "",
        f"v{entry['version']}" if entry.get("version") else "",
        f"共 {entry['chapters']} 篇" if entry.get("chapters") else "",
        f"{entry['size_mb']} MB" if entry.get("size_mb") else "",
    ]
    tail = (
        "解压后离线阅读，不需要联网"
        if docs
        else "解压即用，全程在本机运行、文件不上传"
    )
    plats = "、".join(l["platform"] for l in (entry.get("_links") or []) if l["platform"])
    if plats:
        tail += f"；{plats} 分发"
    if any(l["code"] for l in (entry.get("_links") or [])):
        tail += "，提取码页面直接给出"
    desc = " · ".join(b for b in bits if b) + "。" + tail + "。"
    return desc[:158]


def plain_text(fragment: str) -> str:
    """HTML 片段 → 纯文本。FAQPage 结构化数据要的是答案原文，不能带标签。"""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def block(title: str, inner: str, anchor: str) -> str:
    inner = inner.strip()
    if not inner:
        return ""
    return f'    <section class="block" id="{anchor}">\n      <h2>{esc(title)}</h2>\n{inner}\n    </section>'


def subsections(items: list) -> str:
    return "\n".join(
        f'      <section class="sub">\n        <h3>{esc(item.title)}</h3>\n{indent(item.html)}\n      </section>'
        for item in items
    )


def indent(fragment: str, spaces: int = 6) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in fragment.splitlines())


def cover_block_html(entry: dict, root: str) -> str:
    """详情页配图：只放真实界面截图或资料海报，128px 的应用图标放大只会糊。"""
    if entry.get("image_kind") not in ("screenshot", "poster") or not entry.get("_asset"):
        return ""
    docs = entry.get("kind") == "docs"
    thumb = esc(root + entry["_asset"])
    alt = f'{esc(entry["name"])}{"封面" if docs else "软件界面截图"}'
    full = entry.get("_asset_full")
    img = f'<a href="{esc(root + full)}" class="zoom-link"><img src="{thumb}" alt="{alt}" loading="lazy"></a>' if full else f'<img src="{thumb}" alt="{alt}" loading="lazy">'
    return f'    <figure class="detail-cover">\n      {img}\n      <figcaption>{alt}{"（点开看原图）" if full else ""}</figcaption>\n    </figure>'


def downloads_block_html(entry: dict) -> str:
    links = entry.get("_links") or []
    if not links:
        return ""
    docs = entry.get("kind") == "docs"
    rows = []
    for i, link in enumerate(links):
        primary = i == 0
        platform = link["platform"] or "网盘链接"
        main = [f'<span class="dl-platform">{esc(platform)}</span>']
        if primary and len(links) > 1:
            main.append('<span class="dl-tag">推荐</span>')
        if link["note"]:
            main.append(f'<span class="dl-note">{esc(link["note"])}</span>')
        side = []
        if link["code"]:
            side.append(f'<span class="dl-code">提取码 <b>{esc(link["code"])}</b></span>')
        side.append(
            f'<a class="btn dl-open{"" if primary else " ghost"}" href="{esc(link["url"])}"'
            f' target="_blank" rel="noopener">{esc("打开" + platform)}</a>'
        )
        rows.append(
            f'      <div class="dl-item{" primary" if primary else ""}">'
            f'<div class="dl-main">{"".join(main)}</div><div class="dl-side">{"".join(side)}</div></div>'
        )
    tip = (
        "解压后即可离线阅读，全程在你自己的电脑上打开，不需要联网。"
        if docs
        else "下载后解压即用，不需要装运行库；软件全程在本机运行，文件不上传。"
    )
    if any(l["code"] for l in links):
        tip = "提取码随链接给出，打开前记得填。" + tip
    inner = "\n".join([f'      <div class="dl-list">', *rows, "      </div>", f'      <p class="dl-tip">{esc(tip)}</p>'])
    return block("下载渠道", inner, "download")


def faq_block_html(faq: list[tuple[str, str]]) -> str:
    if not faq:
        return ""
    pairs = "\n".join(
        f"      <dt>{esc(q)}</dt>\n      <dd>{indent(a)}\n      </dd>" for q, a in faq
    )
    return block("常见问题", f'      <dl class="faq">\n{pairs}\n      </dl>', "faq")


def also_block_html(entry: dict) -> str:
    """把 aliases/keywords 写成自然句子，而不是塞一堆 meta keywords——
    前者人和引擎都能读，后者是已被降权处理的写法。"""
    alias = [a for a in (entry.get("aliases") or []) if a and not a.isdigit()]
    words = [k for k in (entry.get("keywords") or []) if k and len(k) <= 12]
    sentences = []
    if alias:
        sentences.append(f"也有人叫它{'、'.join(alias[:6])}。")
    if entry.get("name_en"):
        sentences.append(f"英文名 {esc(entry['name_en'])}，")
    if entry.get("exe_name") and entry["exe_name"] != entry.get("name_en"):
        sentences.append(f"程序名 {esc(entry['exe_name'])}。")
    if words:
        sentences.append("想找这类工具时常见的说法：" + "、".join(words[:12]) + "。")
    body = "\n".join(f'      <p>{s}</p>' for s in sentences if s)
    return block("其它叫法与搜索词", body, "words")


def related_block_html(entry: dict, peers: list[dict], paths: dict[str, str], root: str) -> str:
    if not peers:
        return ""
    items = "".join(
        f'<li><a href="{esc(root + paths[p["slug"]])}">{esc(p["name"])}</a>'
        f'<span class="rl-note">{esc(p.get("summary") or "")}</span></li>'
        for p in peers
    )
    inner = (
        f'      <p class="rl-lead">同属「{esc(entry.get("category") or "其它")}」的其他资源：</p>\n'
        f'      <ul class="related-list">\n      {items}\n      </ul>\n'
        f'      <p class="rl-all"><a href="{esc(root)}index.html">全部资源 →</a></p>'
    )
    return block("同类资源", inner, "related")


def crumbs_html(entry: dict, brand: str, root: str) -> str:
    return (
        f'<a href="{esc(root)}index.html">{esc(brand)}</a><span class="sep">›</span>'
        f'<span aria-current="page">{esc(entry["name"])}</span>'
    )


def detail_json_ld(entry: dict, path: str, site_url: str, brand: str, faq: list[tuple[str, str]]) -> str:
    page_url = absolute(site_url, path) or f"/{path}"
    graph = [
        app_item(entry, page_url, site_url),
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": brand, "item": f"{site_url}/" if site_url else "/"},
                {"@type": "ListItem", "position": 2, "name": entry["name"], "item": page_url},
            ],
        },
    ]
    if faq:
        graph.append(
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": plain_text(a)}}
                    for q, a in faq
                ],
            }
        )
    doc = {"@context": "https://schema.org", "@graph": graph}
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def detail_head(entry: dict, path: str, site_url: str, title: str, desc: str, brand: str) -> str:
    url = absolute(site_url, path)
    lines = [
        f'<meta property="og:site_name" content="{esc(brand)}">',
        '<meta property="og:locale" content="zh_CN">',
    ]
    if site_url:
        cover = entry.get("_asset_full") or entry.get("_asset") or ""
        lines += [
            f'<link rel="canonical" href="{esc(url)}">',
            '<meta property="og:type" content="website">',
            f'<meta property="og:title" content="{esc(title)}">',
            f'<meta property="og:description" content="{esc(desc)}">',
            f'<meta property="og:url" content="{esc(url)}">',
        ]
        if cover:
            lines.append(f'<meta property="og:image" content="{esc(site_url + "/" + cover)}">')
        lines += [
            f'<meta name="twitter:card" content="{"summary_large_image" if cover else "summary"}">',
            f'<meta name="twitter:title" content="{esc(title)}">',
            f'<meta name="twitter:description" content="{esc(desc)}">',
        ]
    return "\n".join(lines)


def load_manual(entry: dict, jobs_root: Path, brand: str, wechat: str) -> tuple[object, str]:
    """按软件目录现取手册：正文留在手册里，不抄进 shares.yaml，
    否则两份内容必然漂移，而人工真源会被 4000 字散文挤到读不动。"""
    if entry.get("kind") == "docs":
        return None, ""
    path = manual.find_manual(jobs_root / entry["slug"])
    if not path:
        return None, ""
    return manual.parse(path, brand, wechat), path.as_posix()


def detail_html(entry: dict, ctx: dict) -> str:
    """一版详情页。缺手册不是错误：正文退到 description + 功能清单，
    但要把这一条打印出来，否则没人知道某款软件其实是空壳页。"""
    man, _ = ctx["manuals"].get(entry["slug"], (None, ""))
    root = "../"
    paths: dict[str, str] = ctx["paths"]
    brand: str = ctx["brand"]
    wechat: str = ctx["wechat"]
    site_url: str = ctx["site_url"]
    title = detail_title(entry, brand)
    desc = detail_desc(entry)
    docs = entry.get("kind") == "docs"
    faq = list(man.faq) if man else []

    facts = [
        entry.get("chapters") and f"共 {entry['chapters']} 篇" if docs else entry.get("version") and f"v{entry['version']}",
        entry.get("size_mb") and f"{entry['size_mb']} MB",
        entry.get("category"),
        entry.get("updated") and f"更新 {entry['updated']}",
    ]
    pills = "".join(f'<span class="pill">{esc(t)}</span>' for t in facts if t)
    # 英文名与程序名经常相同（000 就是），并列显示只会显得这页在凑字数
    alt_names = " · ".join(dict.fromkeys(v for v in (entry.get("name_en"), entry.get("exe_name")) if v))

    intro_inner = (man.intro if man else "") or f"      <p>{esc(entry.get('description') or entry.get('summary') or '')}</p>"
    intro_block = block("这是什么", indent(intro_inner), "about")
    sections = subsections(man.sections) if man else ""
    if not sections:
        feats = "".join(f"<li>{esc(f)}</li>" for f in (entry.get("features") or []))
        sections = f"      <ul class=\"feature-list\">\n      {feats}\n      </ul>" if feats else ""
    sections_title = "篇章清单" if docs else "功能详解"
    install_block = block("怎么用", subsections(man.install), "install") if man and man.install else ""
    env_block = block("运行环境", indent(man.env), "requirements") if man and man.env else ""
    notes_block = block("注意事项", indent(man.notes), "notes") if man and man.notes else ""

    peers = [p for p in ctx["entries"] if p is not entry and p.get("category") == entry.get("category")][:3]
    template: str = ctx["template"]
    page = (
        template.replace("{{TITLE}}", esc(title))
        .replace("{{DESC}}", esc(desc))
        .replace("{{BRAND}}", esc(brand))
        .replace("{{WECHAT}}", esc(wechat))
        .replace("{{ROOT}}", root)
        .replace("{{HEAD}}", detail_head(entry, paths[entry["slug"]], site_url, title, desc, brand))
        .replace("{{CRUMBS}}", crumbs_html(entry, brand, root))
        .replace("{{NAME}}", esc(entry["name"]))
        .replace("{{ALT_NAME}}", esc(alt_names))
        .replace("{{PILLS}}", pills)
        .replace("{{SUMMARY}}", esc(entry.get("summary") or ""))
        .replace("{{COVER_BLOCK}}", cover_block_html(entry, root))
        .replace("{{INTRO_BLOCK}}", intro_block)
        .replace("{{DL_BLOCK}}", downloads_block_html(entry))
        .replace("{{INSTALL_BLOCK}}", install_block)
        .replace("{{SECTIONS_BLOCK}}", block(sections_title, sections, "features"))
        .replace("{{ENV_BLOCK}}", env_block)
        .replace("{{FAQ_BLOCK}}", faq_block_html(faq))
        .replace("{{NOTES_BLOCK}}", notes_block)
        .replace("{{ALSO_BLOCK}}", also_block_html(entry))
        .replace("{{RELATED_BLOCK}}", related_block_html(entry, peers, paths, root))
        .replace("{{UPDATED}}", esc(entry.get("updated") or ctx["updated"]))
    )
    ld = detail_json_ld(entry, paths[entry["slug"]], site_url, brand, faq)
    if site_url:
        page = page.replace("</head>", f'<script type="application/ld+json">{ld}</script>\n</head>', 1)
    return page



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
    brand, wechat, site_url, config_error = resolve_site(site, args)
    if config_error:
        return config_error
    title = page_title(brand, bool(docs))
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
    for stale in out.rglob("*.html"):
        stale.unlink()  # 详情页在子目录里，只清顶层会把下架的旧页留在发布包里
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
    desc = PAGE_DESC_WITH_DOCS if docs else PAGE_DESC
    updated = str(site.get("updated") or docs_site.get("updated") or date.today())
    count_line = f"共 {len(entries)} 款软件" + (f" · {len(docs)} 份资料" if docs else "")
    paths = page_paths(combined)
    manuals = {e["slug"]: load_manual(e, jobs_root, brand, wechat) for e in combined}
    no_manual = [e["name"] for e in entries if not manuals[e["slug"]][0]]
    brand_fixes = sum(m.brand_fixes for m, _ in manuals.values() if m)
    wechat_fixes = sum(m.wechat_fixes for m, _ in manuals.values() if m)
    ctx = {
        "paths": paths,
        "manuals": manuals,
        "brand": brand,
        "wechat": wechat,
        "site_url": site_url,
        "template": (src / "detail.html").read_text(encoding="utf-8"),
        "entries": combined,
        "updated": updated,
    }
    template = (src / "template.html").read_text(encoding="utf-8")
    pages: dict[str, str] = {
        "index.html": (
            template.replace("{{TITLE}}", esc(title))
            .replace("{{BRAND}}", esc(brand))
            .replace("{{WECHAT}}", esc(wechat))
            .replace("{{DESC}}", esc(desc))
            .replace("{{HEAD}}", head_extra(combined, site_url, desc, brand, title, paths))
            .replace("{{CHIPS}}", chips_html(combined))
            .replace("{{CARDS}}", "".join(card_html(e, i, paths) for i, e in enumerate(entries)))
            .replace("{{DOCS_BLOCK}}", docs_block_html(docs, paths))
            .replace("{{DATA}}", json_payload(combined))
            .replace("{{COUNT}}", count_line)
            .replace("{{UPDATED}}", updated)
            .replace("{{MAINTAINER}}", "HRX")
        )
    }
    for e in combined:
        pages[paths[e["slug"]]] = detail_html(e, ctx)
    for rel, content in pages.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    (out / "style.css").write_text((src / "style.css").read_text(encoding="utf-8"), encoding="utf-8")
    (out / "app.js").write_text((src / "app.js").read_text(encoding="utf-8"), encoding="utf-8")
    (out / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1f4fd8"/>'
        '<path d="M18 20h9l7 12 7-12h9v24h-8V33l-6 10h-4l-6-10v11h-8z" fill="#fff"/></svg>\n',
        encoding="utf-8",
    )
    (out / "robots.txt").write_text(robots_txt(site_url), encoding="utf-8")
    (out / "llms.txt").write_text(llms_txt(entries, docs, site_url, updated, brand, wechat, paths), encoding="utf-8")
    verify = write_verify_files(site, out)
    if site_url:
        # 每条 URL 的 lastmod 用该条自己的 updated：
        # 全站写同一个日期，抓取器会把"这站在动"的信号当成噪声。
        by_path = {paths[e["slug"]]: e for e in combined}
        rows = []
        for rel in pages:
            loc = f"{site_url}/" if rel == "index.html" else f"{site_url}/{rel}"
            rows.append(f'  <url><loc>{esc(loc)}</loc><lastmod>{esc(by_path.get(rel, {}).get("updated") or updated)}</lastmod></url>')
        urls = "\n".join(rows)
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
        + f"，{len(pages)} 个页面 → {path_config.display_path(out)}/  （{total:.2f} MB）"
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
    if no_manual:
        print("详情页缺用户手册正文（退到简介+功能清单，正文会偏薄）：" + "、".join(no_manual))
    if verify:
        print("站长验证文件已随构建产出：" + "、".join(verify))
    if brand_fixes:
        print(f"提示：手册里有 {brand_fixes} 处旧品牌写法，已按 site.name 统一渲染；源头在各软件工程的 md 里，建议顺手改掉。")
    if wechat_fixes:
        print(f"提示：手册里有 {wechat_fixes} 处提到公众号，已按 site.wechat_name 渲染（公众号名不跟着站点品牌走）。")
    thin = [rel for rel, content in pages.items() if rel != "index.html" and body_han(content) < MIN_PAGE_HAN]
    if thin:
        print(f"警告：{len(thin)} 个详情页正文少于 {MIN_PAGE_HAN} 汉字，承接不住长尾搜索，先补内容再对外推广：")
        for rel in thin:
            print(f"  · {rel}（正文 {body_han(pages[rel])} 汉字）")
    leftovers = [rel for rel, content in pages.items() if "{{" in content]
    if leftovers:
        print("警告：页面里还有没替换掉的模板占位符：" + "、".join(leftovers))
    if total > SOFT_LIMIT_MB:
        print(f"警告：产物 {total:.1f} MB 接近发布上限，请下调封面尺寸或质量。")
    if not site_url:
        print("注意：本次是 --offline 构建，canonical/og/JSON-LD/sitemap 全部缺失，这份产物不要发布。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="构建静态站点")
    p.add_argument("--data", default=str(DEFAULT_DATA))
    p.add_argument("--docs-data", default=str(DEFAULT_DOCS), help="文档数据文件（不存在则站点不含文档区块）")
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--src", default=str(DEFAULT_SRC))
    p.add_argument("--jobs-root", type=Path, default=None, help="软件根目录（默认取 data/paths.yaml 的 jobs_root）")
    p.add_argument("--docs-root", type=Path, default=None, help="文档根目录（默认取 data/paths.yaml 的 docs_root）")
    p.add_argument("--site-url", default="", help="临时覆盖 data/shares.yaml 的 site.url（换域名试构建用，正式值请写进配置）")
    p.add_argument("--offline", action="store_true", help="本地预览：忽略 site.url，不产 canonical/og/JSON-LD/sitemap（这种产物 seo_check 判不通过）")
    p.add_argument("--no-images", action="store_true", help="跳过封面压缩")
    args = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
