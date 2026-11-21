#!/usr/bin/env python3
"""上架目录（catalog）维护工具 —— 站点要展示什么，只由这个目录决定。

用法：
    python tools/catalog.py index                     # 导出 catalog/index.csv（只读总览，Excel 直接打开）
    python tools/catalog.py list                      # 命令行看一遍上架/草稿/隐藏
    python tools/catalog.py check                     # 体检：必填、封面、链接、手册、重名
    python tools/catalog.py import-legacy             # 一次性迁移：data/*.yaml → catalog（已经迁完，别重复跑）
    python tools/catalog.py intake 012_老照片修复工具   # 从 AI_SOFT 采集一条，默认 draft（不上页）
    python tools/catalog.py intake W001_某文档 --doc    # 从 AI_WORD 采集文档类条目
    python tools/catalog.py refresh 001_证件照制作工具 --cover|--manual|--all
    python tools/catalog.py link 009_AI缓存专清 --platform 夸克网盘 --url https://... --code 1A2B
    python tools/catalog.py links out|in              # 链接表往返：Excel 批量改链接
    python tools/catalog.py drift                     # 源工程改了、目录没跟 → 只报告，不自动覆盖

目录约定（一个条目一个文件夹，目录名即 slug，改目录名等于换 URL）：

    catalog/
      site.yaml                站点级配置（品牌名、域名、验证文件、常见需求导航）
      index.csv                自动导出，别手改
      links.csv                链接往返专用（links out 产出、links in 写回）
      000_PDF超级工具箱/
          meta.yaml            名称/版本/分类/状态/渠道 —— 人改这个
          manual.md            详情页正文（原 用户手册/*使用说明.md 的副本，可以直接改）
          cover.png            卡片封面原图（构建转 webp）
          detail.png           详情放大图（可选）
          _source.json         采集时记的源文件与 sha1，人不用动

状态：live 上架 / coming_soon 灰卡（两者都必须有链接）/ draft 收着不上页 / hidden 完全不渲染。
新采集进来的条目一律 draft —— 扫描不再能把工程直接推上线。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import yaml

import manual as manual_mod
import paths as path_config
import scan_docs
import scan_jobs

SITE_ROOT = Path(__file__).resolve().parents[1]
CATALOG = SITE_ROOT / "catalog"
SITE_FILE = CATALOG / "site.yaml"
INDEX_FILE = CATALOG / "index.csv"
LINKS_FILE = CATALOG / "links.csv"
LEGACY_SHARES = SITE_ROOT / "data" / "shares.yaml"
LEGACY_DOCS = SITE_ROOT / "data" / "docs.yaml"

STATUSES = ("live", "coming_soon", "draft", "hidden")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
DOC_DIR = re.compile(r"^W\d{3}_")
ITEM_META_ORDER = (
    "slug", "kind", "name", "name_en", "exe_name", "status", "category",
    "summary", "description", "features", "keywords", "aliases", "tags", "downloads",
    "cover", "detail_image", "image_kind", "updated", "chapters",
    "local_artifact", "copy_source",
)

META_HEADER = """\
# 上架目录条目 —— 站点展示的唯一真源，人改这个文件
#
# slug           默认等于目录名，改名字段无效（目录名就是主键）
# kind           soft 软件 / doc 资料
# name/name_en   商品名（卡片主标题）/ 英文名（决定详情页 URL，别轻易改）
# exe_name       进程名或发行包名，用户可能直接搜它
# status         live 上架 / coming_soon 灰卡（两者必须有链接）/ draft 收着不上页 / hidden 不渲染
# category       分类筛选栏就是它的去重结果
# summary        卡片上一句话（30~60 字）
# description    详情页简介段落
# features       功能要点（列表，参与搜索，卡片取前 3 条做标签）
# keywords/aliases  额外搜索词 / 用户可能的叫法
# tags           卡片上的可点标签（3~4 个），脚本不生成也不覆盖
# downloads      多网盘渠道，第一个是主渠道；提取码建议加引号，避免 0101 被当成数字
# cover          卡片封面，相对本目录的文件名；没有就留空（卡片退成排版封面并标注待补）
# detail_image   详情放大图（可选）
# updated        手填值仅作兜底：构建时优先用 git 里本目录的真实提交日期，
#                因为手填靠人记得改，漏一次页面上就永远是旧日期。
#                取不到 git 才用它，两者都没有就不输出 lastmod，绝不写「今天」。
# local_artifact 本机发行包路径，只给人看，构建不读，跨机器失效也不报错
# copy_source    简介抽取来源（留档用）
#
# 版本号与体积不再是条目字段：它们要手工跟住网盘里的包，一漏就是对用户
# 和搜索引擎说假话，而代码里没有任何机制能发现。体积在网盘页面本来就有且实时准确。
#
# 改完跑：python tools/catalog.py check && python tools/catalog.py index
# 本文件的注释在你用 links in / link 子命令改写时会被重新生成，手写的额外注释请放进「notes」不合适的位置——直接写在字段旁边即可。
"""


# --------------------------------------------------------------------------- 基础读写

def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def item_dirs() -> list[Path]:
    if not CATALOG.is_dir():
        return []
    return sorted(p for p in CATALOG.iterdir() if p.is_dir() and not p.name.startswith((".", "_")))


def load_meta(d: Path) -> dict:
    meta = yaml.safe_load((d / "meta.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(meta, dict):
        raise SystemExit(f"{d.name}/meta.yaml 不是键值映射，请修好再跑。")
    meta["slug"] = d.name  # 目录名就是主键，yaml 里写错也不生效
    meta["kind"] = "doc" if str(meta.get("kind") or "").strip() == "doc" else "soft"
    meta["_dir"] = d
    return meta


def load_items(include_hidden: bool = True) -> list[dict]:
    items = []
    for d in item_dirs():
        if not (d / "meta.yaml").is_file():
            continue
        meta = load_meta(d)
        if not include_hidden and meta.get("status") == "hidden":
            continue
        items.append(meta)
    return items


def save_meta(meta: dict) -> None:
    d: Path = meta["_dir"]
    clean = {k: v for k, v in meta.items() if not k.startswith("_")}
    ordered = {k: clean[k] for k in ITEM_META_ORDER if k in clean}
    for key, value in clean.items():
        if key not in ordered:
            ordered[key] = value
    body = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, width=10000)
    (d / "meta.yaml").write_text(META_HEADER + body, encoding="utf-8")


def load_site() -> dict:
    if not SITE_FILE.is_file():
        return {}
    doc = yaml.safe_load(SITE_FILE.read_text(encoding="utf-8")) or {}
    return doc.get("site") or doc or {}


def entry_links(meta: dict) -> list[dict]:
    """归一化渠道：downloads 数组优先，兼容旧的 share_url 三件套。"""
    raw = meta.get("downloads")
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
    legacy_url = str(meta.get("share_url") or "").strip()
    if not legacy_url:
        return []
    return [{
        "platform": str(meta.get("platform") or "").strip(),
        "url": legacy_url,
        "code": str(meta.get("share_code") or "").strip(),
        "note": "",
    }]


def copy_asset(src: Path, dst_dir: Path, stem: str) -> str:
    """把源工程里的图片拷进条目目录，返回写进 meta 的文件名。"""
    suffix = src.suffix.lower() if src.suffix.lower() in IMAGE_SUFFIXES else ".png"
    dst = dst_dir / f"{stem}{suffix}"
    dst.write_bytes(src.read_bytes())
    for old in dst_dir.glob(f"{stem}.*"):
        if old != dst and old.suffix.lower() in IMAGE_SUFFIXES:
            old.unlink()  # 换格式时清掉旧图，避免目录里留两张封面
    return dst.name


def write_source(d: Path, root: Path, project: Path, cover_from: str, manual_from: str, origin: str) -> None:
    record = {
        "origin": origin,
        "root": root.name,
        "project_dir": project.name,
        "cover_from": cover_from,
        "cover_sha1": sha1((project / cover_from).resolve()) if cover_from and (project / cover_from).is_file() else "",
        "manual_from": manual_from,
        "manual_sha1": sha1(project / manual_from) if manual_from and (project / manual_from).is_file() else "",
        "intake_at": date.today().isoformat(),
    }
    (d / "_source.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- 导出 / 体检

def protect(value: object) -> str:
    """CSV 里给 Excel 看的纯数字（提取码 0101）会被吃掉前导零，包成 ="0101" 保持文本。"""
    text = "" if value is None else str(value)
    return f'="{text}"' if text.isdigit() else text


def unprotect(value: str) -> str:
    text = (value or "").strip()
    hit = re.fullmatch(r'="(.*)"', text)
    return hit.group(1) if hit else text.lstrip("'")


INDEX_COLUMNS = (
    "目录", "类型", "名称", "英文名", "分类", "状态", "渠道数", "主渠道",
    "主链接", "主提取码", "封面", "详情图", "手册", "更新时间", "简介",
)


def index_row(meta: dict) -> list[str]:
    d: Path = meta["_dir"]
    links = entry_links(meta)
    main = links[0] if links else {}
    cover = str(meta.get("cover") or "")
    detail = str(meta.get("detail_image") or "")
    manual_file = d / "manual.md"
    return [
        meta["slug"],
        "软件" if meta["kind"] == "soft" else "资料",
        str(meta.get("name") or ""),
        str(meta.get("name_en") or ""),
        str(meta.get("category") or ""),
        str(meta.get("status") or ""),
        str(len(links)),
        str(main.get("platform") or ""),
        str(main.get("url") or ""),
        protect(main.get("code") or ""),
        cover if cover and (d / cover).is_file() else (f"缺 {cover}" if cover else "无"),
        detail if detail and (d / detail).is_file() else "",
        "有" if manual_file.is_file() else ("不需要" if meta["kind"] == "doc" else "缺"),
        str(meta.get("updated") or ""),
        str(meta.get("summary") or ""),
    ]


def cmd_index(args: argparse.Namespace) -> int:
    items = load_items(include_hidden=args.all)
    CATALOG.mkdir(exist_ok=True)
    with INDEX_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(INDEX_COLUMNS)
        for meta in items:
            writer.writerow(index_row(meta))
    shown = len(items)
    print(f"已导出 {path_config.display_path(INDEX_FILE)}（{shown} 条{'' if args.all else '，不含 hidden'}）")
    for status in ("live", "coming_soon", "draft", "hidden"):
        count = sum(1 for m in items if str(m.get("status") or "") == status)
        if count:
            print(f"  {status:<12}{count} 条")
    return 0


def check_item(meta: dict) -> tuple[list[str], list[str], list[str]]:
    """返回 (错误, 警告, 提示)。错误会让 check 退出 1。"""
    errors: list[str] = []
    warns: list[str] = []
    notes: list[str] = []
    d: Path = meta["_dir"]
    slug = meta["slug"]
    status = str(meta.get("status") or "")
    if not str(meta.get("name") or "").strip():
        errors.append(f"{slug}：name 为空（卡片主标题没有出处）")
    if status not in STATUSES:
        errors.append(f"{slug}：status = {status or '空'}，只能是 {'/'.join(STATUSES)}")
    if not str(meta.get("category") or "").strip() and status in ("live", "coming_soon"):
        warns.append(f"{slug}：category 为空，分类筛选栏会少一格")
    links = entry_links(meta)
    if status in ("live", "coming_soon") and not links:
        errors.append(f"{slug}：status={status} 但没挂任何渠道 —— 要么补链接，要么改成 draft")
    for i, link in enumerate(links, 1):
        url = link["url"]
        if not re.match(r"^https?://", url):
            errors.append(f"{slug}：第 {i} 个渠道链接不是 http(s)：{url}")
        if not link["platform"]:
            warns.append(f"{slug}：第 {i} 个渠道没写 platform，卡片上会显示成空平台")
    cover = str(meta.get("cover") or "")
    if cover:
        if not (d / cover).is_file():
            errors.append(f"{slug}：cover = {cover} 不存在，卡片会退成排版封面")
    else:
        warns.append(f"{slug}：没设置 cover，卡片用排版封面并标注「截图待补」")
    detail = str(meta.get("detail_image") or "")
    if detail and not (d / detail).is_file():
        warns.append(f"{slug}：detail_image = {detail} 不存在")
    if meta["kind"] == "soft" and not (d / "manual.md").is_file():
        warns.append(f"{slug}：缺 manual.md，详情页正文会退成简介+功能清单（偏薄）")
    if meta["kind"] == "doc" and (d / "manual.md").is_file():
        notes.append(f"{slug}：资料条目不渲染 manual.md，这个文件可以删")
    for extra in d.iterdir():
        if extra.is_dir() and extra.name != "images":
            notes.append(f"{slug}：目录里有个子目录 {extra.name}，构建不会用它")
        elif extra.is_file() and extra.name not in ("meta.yaml", "manual.md", "_source.json", cover, detail):
            if extra.suffix.lower() in IMAGE_SUFFIXES:
                notes.append(f"{slug}：多余的图片 {extra.name}（构建只用 cover/detail）")
            else:
                notes.append(f"{slug}：目录里有未被使用的文件 {extra.name}")
    return errors, warns, notes


def cmd_check(args: argparse.Namespace) -> int:
    items = load_items()
    site = load_site()
    errors: list[str] = []
    warns: list[str] = []
    notes: list[str] = []

    if not items:
        print("catalog 里一个条目都没有。先跑 python tools/catalog.py import-legacy 或 intake。")
        return 2
    if not str(site.get("name") or "").strip():
        errors.append("catalog/site.yaml：site.name 缺失（页面标题、h1、llms.txt 都取它）")
    if not str(site.get("wechat_name") or "").strip():
        errors.append("catalog/site.yaml：site.wechat_name 缺失（页面上公众号名得有真名）")
    if not str(site.get("url") or "").strip():
        errors.append("catalog/site.yaml：site.url 缺失（canonical/sitemap/JSON-LD 全靠它，本地预览请用 --offline）")

    seen_en: dict[str, str] = {}
    seen_url: dict[str, str] = {}
    for meta in items:
        item_errors, item_warns, item_notes = check_item(meta)
        errors += item_errors
        warns += item_warns
        notes += item_notes
        en = str(meta.get("name_en") or "").strip()
        if en and not en.isascii():
            warns.append(f"{meta['slug']}：name_en 不是 ASCII，详情页 URL 会退回目录名")
        if en:
            if en.lower() in seen_en:
                warns.append(f"{meta['slug']}：name_en 与 {seen_en[en.lower()]} 重复，详情页 URL 会加编号前缀")
            seen_en.setdefault(en.lower(), meta["slug"])
        for link in entry_links(meta):
            if link["url"] in seen_url:
                warns.append(f"{meta['slug']}：链接与 {seen_url[link['url']]} 相同（同一渠道挂了两条）")
            seen_url.setdefault(link["url"], meta["slug"])

    for task in site.get("tasks") or []:
        label = str((task or {}).get("label") or "").strip()
        slug = str((task or {}).get("slug") or "").strip()
        if slug and slug not in {m["slug"] for m in items}:
            warns.append(f"site.tasks：{label or slug} 指向的 {slug} 不在 catalog 里，这一格不会渲染")

    counts = {s: sum(1 for m in items if str(m.get("status") or "") == s) for s in STATUSES}
    print(
        "catalog 共 %d 条：live %d / coming_soon %d / draft %d / hidden %d"
        % (len(items), counts["live"], counts["coming_soon"], counts["draft"], counts["hidden"])
    )
    for title, rows in (("错误", errors), ("警告", warns), ("提示", notes)):
        if rows:
            print(f"\n{title}（{len(rows)}）：")
            for row in rows:
                print(f"  · {row}")
    if errors:
        print("\n有错误，先修掉再构建。")
        return 1
    if INDEX_FILE.is_file():
        print(f"\n体检通过。index.csv 需刷新就跑 python tools/catalog.py index。")
    else:
        print("\n体检通过。还没有 index.csv，跑 python tools/catalog.py index 生成。")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    items = load_items(include_hidden=args.all)
    print(f"{'状态':<12}{'类型':<6}{'目录':<30}{'主渠道':<10}{'封面':<8}链接")
    for meta in items:
        links = entry_links(meta)
        main = links[0] if links else {}
        cover = str(meta.get("cover") or "")
        has_cover = "有" if cover and (meta["_dir"] / cover).is_file() else "缺"
        print(
            f"{str(meta.get('status')):<12}{'软件' if meta['kind'] == 'soft' else '资料':<6}"
            f"{meta['slug']:<30}{str(main.get('platform') or '-'):<10}{has_cover:<8}"
            f"{str(main.get('url') or '-')}"
        )
    return 0


# --------------------------------------------------------------------------- 迁移 / 采集

def cmd_import_legacy(args: argparse.Namespace) -> int:
    """把 data/shares.yaml + data/docs.yaml 一次性搬进 catalog，字段照抄，不做二次抽取。"""
    if not LEGACY_SHARES.is_file():
        print(f"找不到 {LEGACY_SHARES}（已经迁移过就别再跑这个命令）。")
        return 2
    doc = yaml.safe_load(LEGACY_SHARES.read_text(encoding="utf-8")) or {}
    site = doc.get("site") or {}
    shares = [e for e in (doc.get("shares") or []) if isinstance(e, dict)]
    docs: list[dict] = []
    docs_site: dict = {}
    if LEGACY_DOCS.is_file():
        d_doc = yaml.safe_load(LEGACY_DOCS.read_text(encoding="utf-8")) or {}
        docs = [e for e in (d_doc.get("docs") or []) if isinstance(e, dict)]
        docs_site = d_doc.get("site") or {}

    CATALOG.mkdir(exist_ok=True)
    if not SITE_FILE.is_file():
        header = (
            "# 站点级配置 —— 品牌名、公众号名、正式域名、站长验证文件、常见需求导航\n"
            "# 只有这里一份，页面标题/h1/og/canonical/sitemap/llms.txt/JSON-LD 全部从这里拼出来。\n"
            "# 缺 name/wechat_name/url 时构建直接失败：这三种沉默都曾在线上发生过。\n"
        )
        merged_site = dict(site)
        if docs_site.get("updated") and not merged_site.get("updated"):
            merged_site["updated"] = docs_site["updated"]
        SITE_FILE.write_text(
            header + yaml.safe_dump({"site": merged_site}, allow_unicode=True, sort_keys=False, width=10000),
            encoding="utf-8",
        )
        print(f"已写入 {path_config.display_path(SITE_FILE)}")

    roots = path_config.resolve_roots()
    jobs_root = roots["jobs_root"].path
    docs_root = roots["docs_root"].path

    written: list[str] = []
    for meta_row, kind in [(e, "soft") for e in shares] + [(e, "doc") for e in docs]:
        slug = str(meta_row.get("slug") or "").strip()
        if not slug:
            print("跳过一条没有 slug 的旧数据。")
            continue
        root = jobs_root if kind == "soft" else docs_root
        project = root / slug
        d = CATALOG / slug
        d.mkdir(exist_ok=True)
        meta: dict = meta_from_legacy(meta_row, kind)
        meta["slug"] = slug
        meta["_dir"] = d
        cover_from = str(meta_row.get("image") or "").strip()
        manual_from = ""
        if cover_from and (project / cover_from).is_file():
            meta["cover"] = copy_asset(project / cover_from, d, "cover")
        else:
            meta["cover"] = ""
            if cover_from:
                print(f"  ! {slug}：源封面不存在 {cover_from}，cover 留空")
        if kind == "soft":
            found_manual = manual_mod.find_manual(project)
            if found_manual:
                (d / "manual.md").write_bytes(found_manual.read_bytes())
                manual_from = found_manual.relative_to(project).as_posix()
        artifact = str(meta_row.get("artifact") or "").strip()
        if artifact:
            meta["local_artifact"] = Path(os.path.relpath(project / artifact, d)).as_posix()
        if not meta.get("updated"):
            meta["updated"] = date.today().isoformat()
        save_meta(meta)
        write_source(d, root, project, cover_from, manual_from, "legacy data/shares.yaml")
        written.append(f"{slug}（{meta['status']}）")

    print(f"已迁入 {len(written)} 条：")
    for line in written:
        print(f"  · {line}")
    print("下一步：python tools/catalog.py check && python tools/catalog.py index")
    return 0


def meta_from_legacy(row: dict, kind: str) -> dict:
    """旧 yaml 的字段原样搬过来；没挂链接的一律 draft（旧规则是"有链接才上架"）。"""
    links = entry_links(row)
    status = str(row.get("status") or "live")
    if status not in STATUSES:
        status = "live"
    if not links:
        status = "draft"
    meta: dict = {"kind": kind, "status": status}
    for key in (
        "name", "name_en", "exe_name", "version", "category", "summary", "description",
        "features", "keywords", "aliases", "tags", "size_mb", "updated", "chapters",
        "copy_source", "image_kind",
    ):
        value = row.get(key)
        if isinstance(value, list):
            if value:
                meta[key] = value
        elif value not in (None, ""):
            meta[key] = value
    meta["downloads"] = links
    meta.setdefault("updated", "")
    return meta


def cmd_intake(args: argparse.Namespace) -> int:
    roots = path_config.resolve_roots()
    root = (roots["docs_root"] if args.doc else roots["jobs_root"]).path
    project = root / args.slug
    if not project.is_dir():
        print(f"找不到工程目录：{project.as_posix()}\n  取值来源：{roots['docs_root' if args.doc else 'jobs_root'].source}")
        return 2
    d = CATALOG / args.slug
    if (d / "meta.yaml").is_file() and not args.force:
        print(f"{args.slug} 已经在 catalog 里了（要重新采集请加 --force）。")
        return 2
    d.mkdir(parents=True, exist_ok=True)

    if args.doc:
        found_doc = scan_docs.scan(project)
        meta: dict = {
            "kind": "doc",
            "status": "draft",
            "name": found_doc.name,
            "category": "",
            "summary": found_doc.summary,
            "description": found_doc.description,
            "features": found_doc.features,
            "chapters": found_doc.chapters,
            "keywords": found_doc.keywords,
            "aliases": [],
            "downloads": [],
            "updated": date.today().isoformat(),
            "image_kind": found_doc.image_kind,
            "copy_source": found_doc.copy_source,
        }
        cover_from = found_doc.image
        manual_from = ""
    else:
        found = scan_jobs.scan(project)
        meta = {
            "kind": "soft",
            "status": "draft",
            "name": found.name,
            "name_en": found.name_en,
            "exe_name": found.exe_name,
            "category": "",
            "summary": found.summary,
            "description": found.description,
            "features": found.features,
            "keywords": found.keywords,
            "aliases": [],
            "downloads": [],
            "updated": date.today().isoformat(),
            "image_kind": found.image_kind,
            "copy_source": found.copy_source,
        }
        cover_from = found.image
        found_manual = manual_mod.find_manual(project)
        manual_from = ""
        if found_manual:
            (d / "manual.md").write_bytes(found_manual.read_bytes())
            manual_from = found_manual.relative_to(project).as_posix()
        if found.artifact:
            meta["local_artifact"] = Path(os.path.relpath(project / found.artifact, d)).as_posix()

    if cover_from and (project / cover_from).is_file():
        meta["cover"] = copy_asset(project / cover_from, d, "cover")
    else:
        meta["cover"] = ""
    meta["slug"] = args.slug
    meta["_dir"] = d
    save_meta(meta)
    write_source(d, root, project, cover_from, manual_from, "intake")
    print(f"已采集 {args.slug} → catalog/{args.slug}/（status=draft，不上页）")
    for warn in (found_doc.warnings if args.doc else found.warnings):
        print(f"  ! {warn}")
    print("填好封面/简介/链接后把 status 改成 live：python tools/catalog.py link ...")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    d = CATALOG / args.slug
    if not (d / "meta.yaml").is_file():
        print(f"catalog/{args.slug} 不存在，先用 intake 采集。")
        return 2
    meta = load_meta(d)
    source_file = d / "_source.json"
    if not source_file.is_file():
        print(f"{args.slug} 没有 _source.json，不知道该从哪个工程重取（手工覆盖文件即可）。")
        return 2
    record = json.loads(source_file.read_text(encoding="utf-8"))
    roots = path_config.resolve_roots()
    root = roots["docs_root" if meta["kind"] == "doc" else "jobs_root"].path
    project = root / (record.get("project_dir") or args.slug)
    if not project.is_dir():
        print(f"源工程不存在：{project.as_posix()}")
        return 2

    do_cover = args.cover or args.all
    do_manual = args.manual or args.all
    if do_cover:
        rel = str(record.get("cover_from") or "")
        src = project / rel if rel else None
        if not src or not src.is_file():
            print(f"源封面不存在：{(src or project).as_posix()}")
        else:
            meta["cover"] = copy_asset(src, d, "cover")
            print(f"已更新封面：{meta['cover']}（源 {rel}）")
    if do_manual and meta["kind"] == "soft":
        found = manual_mod.find_manual(project)
        if not found:
            print("源工程里没找到用户手册，manual.md 保持原样。")
        else:
            (d / "manual.md").write_bytes(found.read_bytes())
            record["manual_from"] = found.relative_to(project).as_posix()
            print(f"已更新正文：manual.md（源 {record['manual_from']}）")
    record["cover_sha1"] = sha1(project / record["cover_from"]) if record.get("cover_from") and (project / record["cover_from"]).is_file() else record.get("cover_sha1", "")
    record["manual_sha1"] = sha1(project / record["manual_from"]) if record.get("manual_from") and (project / record["manual_from"]).is_file() else record.get("manual_sha1", "")
    record["refreshed_at"] = date.today().isoformat()
    source_file.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_meta(meta)
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    d = CATALOG / args.slug
    if not (d / "meta.yaml").is_file():
        print(f"catalog/{args.slug} 不存在。")
        return 2
    meta = load_meta(d)
    links = entry_links(meta)
    entry = {"platform": args.platform or "", "url": args.url, "code": args.code or "", "note": args.note or ""}
    replaced = False
    for i, link in enumerate(links):
        if link["platform"] == entry["platform"] or (args.replace_platform and link["platform"] == args.replace_platform):
            links[i] = entry
            replaced = True
            break
    if not replaced:
        if args.main:
            links.insert(0, entry)
        else:
            links.append(entry)
    meta["downloads"] = links
    meta.pop("share_url", None)
    meta.pop("share_code", None)
    meta.pop("platform", None)
    save_meta(meta)
    print(f"{args.slug}：渠道 {len(links)} 个 → " + "、".join(f"{l['platform'] or '?'}" for l in links))
    return 0


def cmd_links(args: argparse.Namespace) -> int:
    if args.action == "out":
        items = load_items()
        rows = []
        for meta in items:
            for link in entry_links(meta):
                rows.append([
                    meta["slug"],
                    "软件" if meta["kind"] == "soft" else "资料",
                    link["platform"],
                    link["url"],
                    protect(link["code"]),
                    link["note"],
                ])
        with LINKS_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(("目录", "类型", "平台", "链接", "提取码", "备注"))
            writer.writerows(rows)
        print(f"已导出 {path_config.display_path(LINKS_FILE)}（{len(rows)} 行，一条渠道一行）")
        print("改完跑 python tools/catalog.py links in 写回；整行删除等于下掉该渠道。")
        return 0

    if not LINKS_FILE.is_file():
        print("还没有 links.csv，先跑 python tools/catalog.py links out。")
        return 2
    rows: dict[str, list[dict]] = {}
    with LINKS_FILE.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            slug = (row.get("目录") or "").strip()
            url = (row.get("链接") or "").strip()
            if not slug:
                continue
            if not url:
                print(f"  ! {slug} 有一行没填链接，跳过（整行删除才算下掉渠道）")
                continue
            rows.setdefault(slug, []).append({
                "platform": (row.get("平台") or "").strip(),
                "url": url,
                "code": unprotect(row.get("提取码") or ""),
                "note": (row.get("备注") or "").strip(),
            })
    unknown = [slug for slug in rows if not (CATALOG / slug / "meta.yaml").is_file()]
    if unknown:
        print("以下目录在 catalog 里不存在，已跳过：" + "、".join(unknown))
    changed = 0
    for slug, links in rows.items():
        d = CATALOG / slug
        if not (d / "meta.yaml").is_file():
            continue
        meta = load_meta(d)
        if entry_links(meta) != links:
            meta["downloads"] = links
            meta.pop("share_url", None)
            meta.pop("share_code", None)
            meta.pop("platform", None)
            save_meta(meta)
            changed += 1
    print(f"已写回 {changed} 条的渠道配置。记得跑 check + build。")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    roots = path_config.resolve_roots()
    rows: list[str] = []
    for d in item_dirs():
        source_file = d / "_source.json"
        if not source_file.is_file():
            continue
        record = json.loads(source_file.read_text(encoding="utf-8"))
        meta = load_meta(d) if (d / "meta.yaml").is_file() else {"kind": "soft"}
        root = roots["docs_root" if meta.get("kind") == "doc" else "jobs_root"].path
        project = root / str(record.get("project_dir") or d.name)
        if not project.is_dir():
            rows.append(f"{d.name}：源工程已不存在 {project.as_posix()}")
            continue
        for rel_key, sha_key, label, hint in (
            ("cover_from", "cover_sha1", "封面", "--cover"),
            ("manual_from", "manual_sha1", "正文", "--manual"),
        ):
            rel = str(record.get(rel_key) or "")
            if not rel:
                continue
            src = project / rel
            if not src.is_file():
                rows.append(f"{d.name}：源{label}已删除 {rel}")
                continue
            if sha1(src) != str(record.get(sha_key) or ""):
                rows.append(f"{d.name}：源{label}有改动 {rel} → 需要就 refresh {d.name} {hint}")
    if not rows:
        print("没有漂移：catalog 里的封面与正文都和采集时的源文件一致。")
        return 0
    print(f"发现 {len(rows)} 处漂移（只报告，不自动覆盖）：")
    for row in rows:
        print(f"  · {row}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="上架目录（catalog）维护工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("index", help="导出 catalog/index.csv")
    sp.add_argument("--all", action="store_true", help="连 hidden 一起导出")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("list", help="命令行总览")
    sp.add_argument("--all", action="store_true", help="连 hidden 一起列")
    sp.set_defaults(func=cmd_list)

    sub.add_parser("check", help="体检").set_defaults(func=cmd_check)
    sub.add_parser("import-legacy", help="一次性迁移 data/*.yaml → catalog").set_defaults(func=cmd_import_legacy)
    sub.add_parser("drift", help="报告源工程与目录的差异").set_defaults(func=cmd_drift)

    sp = sub.add_parser("intake", help="从源工程采集一条（默认 draft）")
    sp.add_argument("slug")
    sp.add_argument("--doc", action="store_true", help="从文档根目录（AI_WORD）采集")
    sp.add_argument("--force", action="store_true", help="已存在也重新采集")
    sp.set_defaults(func=cmd_intake)

    sp = sub.add_parser("refresh", help="从源工程重取封面/正文")
    sp.add_argument("slug")
    sp.add_argument("--cover", action="store_true", help="只重取封面")
    sp.add_argument("--manual", action="store_true", help="只重取正文")
    sp.add_argument("--all", action="store_true", help="两者都重取")
    sp.set_defaults(func=cmd_refresh)

    sp = sub.add_parser("link", help="加/改一条网盘渠道")
    sp.add_argument("slug")
    sp.add_argument("--platform", default="", help="网盘平台名，如 夸克网盘")
    sp.add_argument("--url", required=True)
    sp.add_argument("--code", default="", help="提取码，没有就留空")
    sp.add_argument("--note", default="", help="渠道说明（可选）")
    sp.add_argument("--main", action="store_true", help="插到第一位当主渠道")
    sp.add_argument("--replace-platform", default="", help="按这个平台名替换已有渠道")
    sp.set_defaults(func=cmd_link)

    sp = sub.add_parser("links", help="链接表往返")
    sp.add_argument("action", choices=("out", "in"))
    sp.set_defaults(func=cmd_links)

    args = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
