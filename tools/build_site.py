#!/usr/bin/env python3
"""把 data/shares.yaml 构建成可发布的静态站点（web/）。

用法：
    python tools/build_site.py                     # 构建到 web/
    python tools/build_site.py --site-url https://xxx.qoder.site   # 带上正式域名（补 canonical/og/sitemap）
    python tools/build_site.py --no-images         # 跳过图片压缩，纯改文案时更快

卡片正文会预渲染进 index.html（搜索引擎可抓取），同一份数据以 JSON 内嵌供前端检索，
因此站点不依赖任何后端接口，也不额外发起网络请求。
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

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = SITE_ROOT / "data" / "shares.yaml"
DEFAULT_OUT = SITE_ROOT / "web"
DEFAULT_SRC = SITE_ROOT / "site"
MAX_WIDTH = 1280
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


def esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def load_entries(path: Path) -> tuple[list[dict], dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    shares = [e for e in (doc.get("shares") or []) if isinstance(e, dict)]
    # 只有挂了网盘链接的条目才上架；没链接的留在数据里当待办，不占页面
    visible = [e for e in shares if e.get("status") != "hidden" and (e.get("share_url") or "").strip()]
    visible.sort(key=lambda e: (e.get("status") == "coming_soon", str(e.get("slug"))))
    return visible, doc.get("site") or {}


def make_images(entries: list[dict], jobs_root: Path, out: Path) -> None:
    try:
        from PIL import Image
    except ImportError:
        print("提示：未安装 Pillow，跳过封面处理（卡片将使用排版封面）。")
        return
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        rel = entry.get("image") or ""
        src = (jobs_root / entry["slug"] / rel) if rel else None
        if not src or not src.is_file():
            entry["_asset"] = ""
            continue
        stem = re.sub(r"[^a-z0-9]+", "", entry["slug"].lower()) or f"e{entries.index(entry)}"
        if entry.get("image_kind") == "icon":
            dst = img_dir / f"{stem}-icon.png"
            with Image.open(src) as im:
                im.convert("RGBA").resize((128, 128), Image.LANCZOS).save(dst, optimize=True)
            entry["_asset"] = f"images/{dst.name}"
            continue
        dst = img_dir / f"{stem}-cover.webp"
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > MAX_WIDTH:
                im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)), Image.LANCZOS)
            im.save(dst, "WEBP", quality=78, method=6)
        entry["_asset"] = f"images/{dst.name}"


def chip_label(feature: str) -> str:
    """卡片上只放短标签，完整句子留在详情里。"""
    label = feature.split("：")[0].strip() if "：" in feature else feature.strip()
    if len(label) > 14:
        label = label[:13].rstrip("，,、/ ") + "…"
    return label


def card_html(entry: dict, index: int) -> str:
    slug = entry["slug"]
    soon = entry.get("status") == "coming_soon"
    url = (entry.get("share_url") or "").strip()
    code = (entry.get("share_code") or "").strip()
    feats = [f for f in (entry.get("features") or []) if f]
    chips = "".join(f"<li>{esc(chip_label(f))}</li>" for f in feats[:4])
    extra = f'<li class="more">+{len(feats) - 4}</li>' if len(feats) > 4 else ""
    if entry.get("_asset"):
        if entry.get("image_kind") == "icon":
            cover = (
                f'<div class="cover cover-typeset"><img src="{esc(entry["_asset"])}" alt="" loading="lazy">'
                f'<span>{esc(entry.get("name_en") or entry.get("exe_name") or "")}</span>'
                f'<span>界面截图待补</span></div>'
            )
        else:
            cover = (
                f'<div class="cover"><img src="{esc(entry["_asset"])}" alt="{esc(entry["name"])} 软件界面截图" loading="lazy">'
                + (f'<span class="ribbon soon">即将上架</span>' if soon else "")
                + "</div>"
            )
    else:
        cover = (
            f'<div class="cover cover-typeset"><span class="big">{esc(entry["name"])}</span>'
            f'<span>{esc(entry.get("name_en") or "")}</span><span>界面截图待补</span></div>'
        )
    platform = (entry.get("platform") or "").strip()
    if soon:
        cta = '<button class="btn" type="button" disabled>即将上架</button>'
    else:
        label = "获取安装包" + (f"（{platform}）" if platform else "")
        cta = f'<a class="btn" href="{esc(url)}" target="_blank" rel="noopener">{esc(label)}</a>'
        copy_text = url + (f"  提取码：{code}" if code else "")
        cta += f'<button class="btn ghost" type="button" data-copy="{esc(copy_text)}">复制链接</button>'
    pills = "".join(
        f'<span class="pill">{esc(t)}</span>'
        for t in [entry.get("version") and f"v{entry['version']}", entry.get("size_mb") and f"{entry['size_mb']} MB", entry.get("category")]
        if t
    )
    return f"""
    <article class="card" data-id="{esc(slug)}">
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
          <button class="btn ghost btn-copy" type="button" data-more="{esc(slug)}">详情</button>
        </div>
      </div>
    </article>"""


def json_payload(entries: list[dict], url_base: str) -> str:
    keep = ("slug", "name", "name_en", "exe_name", "version", "status", "category", "summary",
            "description", "features", "keywords", "aliases", "share_code", "platform")
    rows = []
    for e in entries:
        row = {k: e.get(k) or ([] if k in ("features", "keywords", "aliases") else "") for k in keep}
        row["id"] = e["slug"]
        asset = e.get("_asset") or ""
        row["cover"] = (url_base + asset) if (url_base and asset) else asset
        row["share_url"] = (e.get("share_url") or "").strip()
        row["updated"] = e.get("updated") or ""
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def head_extra(entries: list[dict], site_url: str, desc: str) -> str:
    if not site_url:
        return ""
    first_cover = next((e["_asset"] for e in entries if e.get("_asset") and e.get("image_kind") == "screenshot"), "")
    og = f'<meta property="og:image" content="{esc(site_url + "/" + first_cover)}">\n' if first_cover else ""
    ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": "HRX 软件库 - 本地工具下载目录",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "item": {
                        "@type": "SoftwareApplication",
                        "name": e.get("name"),
                        "alternateName": e.get("name_en") or e.get("exe_name") or "",
                        "operatingSystem": "Windows",
                        "applicationCategory": "UtilitiesApplication",
                        "description": e.get("summary") or e.get("description") or "",
                        "softwareVersion": e.get("version") or "",
                        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "CNY"},
                        "url": f"{site_url}/#{e['slug']}",
                    },
                }
                for i, e in enumerate(entries)
            ],
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    canonical = "\n".join(
        [
            f'<link rel="canonical" href="{esc(site_url)}/">',
            f'<meta property="og:type" content="website">',
            f'<meta property="og:title" content="HRX 软件库 - 本地工具下载目录">',
            f'<meta property="og:description" content="{esc(desc)}">',
            f'<meta property="og:url" content="{esc(site_url)}/">',
            og,
            f'<meta name="twitter:card" content="summary_large_image">',
            f'<script type="application/ld+json">{ld}</script>',
        ]
    )
    return canonical


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


def build(args: argparse.Namespace) -> int:
    data_path = Path(args.data)
    if not data_path.is_file():
        print(f"找不到数据文件：{data_path}\n先跑 python tools/scan_jobs.py 生成。")
        return 2
    entries, site = load_entries(data_path)
    all_rows = [e for e in ((yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}).get("shares") or [])]
    backlog = [e.get("name") or e.get("slug") or "?" for e in all_rows if e.get("status") != "hidden" and not (e.get("share_url") or "").strip()]
    if not entries:
        print("没有可上架的条目：所有条目都还没挂网盘链接。")
        print(f"待挂链接 {len(backlog)} 条，填好 data/shares.yaml 的 share_url 后重新构建。")
        return 0
    jobs_root = Path(site.get("jobs_root") or SITE_ROOT.parent)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.html"):
        stale.unlink()

    if args.no_images:
        for e in entries:
            e["_asset"] = ""
    else:
        make_images(entries, jobs_root, out)

    src = Path(args.src)
    site_url = (args.site_url or "").rstrip("/")
    desc = "本机能离线运行的 Windows 小工具目录：PDF、证件照、图片、音视频、表格、文件批量与系统效率工具，按名称或功能关键词搜索，附网盘分享链接与提取码。"
    template = (src / "template.html").read_text(encoding="utf-8")
    page = (
        template.replace("{{TITLE}}", "HRX 软件库 - 本地工具下载目录")
        .replace("{{DESC}}", esc(desc))
        .replace("{{HEAD}}", head_extra(entries, site_url, desc))
        .replace("{{CHIPS}}", chips_html(entries))
        .replace("{{CARDS}}", "".join(card_html(e, i) for i, e in enumerate(entries)))
        .replace("{{DATA}}", json_payload(entries, site_url))
        .replace("{{COUNT}}", str(len(entries)))
        .replace("{{UPDATED}}", str(site.get("updated") or date.today()))
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
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n{(f'Sitemap: {site_url}/sitemap.xml') if site_url else ''}\n".strip() + "\n",
        encoding="utf-8",
    )
    if site_url:
        urls = "\n".join(f"  <url><loc>{esc(site_url)}/</loc><lastmod>{esc(date.today())}</lastmod></url>")
        (out / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}\n</urlset>\n',
            encoding="utf-8",
        )

    total = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1048576
    no_cover = [e["name"] for e in entries if e.get("image_kind") != "screenshot"]
    print(f"已上架 {len(entries)} 条 → {out.relative_to(SITE_ROOT).as_posix()}/  （{total:.2f} MB）")
    if backlog:
        print(f"未挂链接、暂不显示 {len(backlog)} 条：" + "、".join(backlog))
    if no_cover:
        print("缺真实界面截图：" + "、".join(no_cover))
    if total > SOFT_LIMIT_MB:
        print(f"警告：产物 {total:.1f} MB 接近发布上限，请下调封面尺寸或质量。")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="构建静态站点")
    p.add_argument("--data", default=str(DEFAULT_DATA))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--src", default=str(DEFAULT_SRC))
    p.add_argument("--site-url", default="", help="正式发布域名，用于 canonical/og/sitemap")
    p.add_argument("--no-images", action="store_true", help="跳过封面压缩")
    args = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return build(args)


if __name__ == "__main__":
    raise SystemExit(main())
