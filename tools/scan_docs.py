#!/usr/bin/env python3
"""扫描文档工程目录 → 维护 data/docs.yaml（与 shares.yaml 同规格的第二份真源）。

用法：
    python tools/scan_docs.py            # 扫描并写回 docs.yaml（只补空字段，不覆盖人工内容）
    python tools/scan_docs.py --check    # 只体检，不写文件
    python tools/scan_docs.py --force    # 重新生成自动字段（人工字段保留）
    python tools/scan_docs.py --root P   # 临时指定文档根目录（默认读 data/paths.yaml）

文档工程以目录名（如 W000_WorkBuddy实战文档系列）为唯一主键。目录约定与软件工程不同，
所以单独一个扫描器，不去套 scan_jobs 的 dist/ 与 推广套件/ 假设：

    Wxxx_名称/            ← 工程根，发布版 zip 直接放在这一层
    └─ 名称/              ← 正文目录：README.md + docs/*.md + posters/ + assets/

根目录同样不写进数据文件：那属于机器环境，跨机器会失效，统一由 tools/paths.py 解析（docs_root）。
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

import paths as path_config
from scan_jobs import clean_lines, cut, entry_links, pick_keywords, read_text

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = SITE_ROOT / "data" / "docs.yaml"
DOC_DIR = re.compile(r"^W\d{3}_")

# 封面按可信度排序：posters 是专为封面做的图，退到正文插图
POSTER_HINT = re.compile(r"(封面|主图|海报|cover)", re.I)
NOISE_NAME = re.compile(r"(二维码|qrcode|logo|图标|缩略|thumb)", re.I)

AUTO_KEYS = (
    "name",
    "artifact",
    "size_mb",
    "chapters",
    "summary",
    "description",
    "features",
    "keywords",
    "image",
    "image_kind",
    "copy_source",
)

HEADER = """\
# 文档站点数据源 —— 唯一真源，人工维护（渲染在站点的「文档资料」区块）
#
# 字段说明：
#   slug            主键，等于文档工程目录名，不要手改（改了就等于删旧增新）
#   name            显示名（脚本按正文目录名填，可改成对外品牌名）
#   status          live=上架 / coming_soon=即将上架（灰态卡片） / hidden=完全不渲染
#   downloads       多网盘渠道列表，第一个为主渠道；填了它就忽略下面的三件套（提取码建议加引号）
#   share_url       单渠道快捷写法：网盘分享链接；没有任何渠道的条目不会出现在页面上
#   share_code      单渠道快捷写法：提取码
#   platform        单渠道快捷写法：网盘平台名
#   category        分类标签，用于筛选栏
#   summary         卡片上的一句话（建议 30~60 字）
#   description     详情段落
#   features        篇章要点，参与搜索
#   chapters        正文篇数（脚本按 docs/*.md 计数）
#   keywords        搜索关键词，参与搜索
#   aliases         用户可能的叫法，参与搜索
#   image           封面图，相对本文档工程目录
#   image_kind      poster=宣传海报 / screenshot=正文插图
#   artifact        发布包路径，相对本文档工程目录（你据此去建分享）
#   size_mb         发布包体积
#   copy_source     简介抽取来源
#
# 文档根目录不在本文件里：改 data/paths.yaml 的 docs_root，或 python tools/paths.py set。
# 新增文档：把 Wxxx_ 目录放进文档根目录，跑 `python tools/scan_docs.py`，再填链接。
# 生成站点：`python tools/build_site.py`，产物在 web/。

"""


@dataclass
class FoundDoc:
    """一个 Wxxx_ 目录里挖出来的原始信息。"""

    slug: str
    name: str = ""
    artifact: str = ""
    size_mb: float = 0.0
    status: str = "coming_soon"
    chapters: int = 0
    summary: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    image: str = ""
    image_kind: str = ""
    copy_source: str = ""
    warnings: list[str] = field(default_factory=list)


def locate_body(project: Path) -> Path:
    """正文一般在 Wxxx_名称/名称/ 这一层；退到第一个含 README.md 或 docs/ 的子目录。"""
    if (project / "README.md").is_file() or (project / "docs").is_dir():
        return project
    for child in sorted(project.iterdir()):
        if child.is_dir() and not child.name.startswith((".", "__")):
            if (child / "README.md").is_file() or (child / "docs").is_dir():
                return child
    return project


def read_artifact(project: Path) -> tuple[str, float, str]:
    """发布包在工程根这一层（不套 dist/ 约定）。取最大的 zip，同名时优先带「发布版」的。"""
    zips = sorted(project.glob("*.zip"))
    if not zips:
        return "", 0.0, "未打包，暂无发布包可分享"
    best = max(zips, key=lambda p: (bool(re.search(r"(发布版|release)", p.stem, re.I)), p.stat().st_size))
    return best.name, round(best.stat().st_size / 1048576, 2), ""


def chapter_list(text: str) -> list[str]:
    """目录表格里的篇章名：只取「内容」列，编号列不要。"""
    titles: list[str] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [re.sub(r"\*+", "", c).strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0].replace(" ", "")) <= set("-: "):
            continue
        title = cells[-1]
        if not title or title in ("内容", "说明", "章节"):
            continue
        titles.append(title)
    return titles


def read_copy(body: Path, project: Path) -> tuple[str, list[str], str]:
    """从 README.md 取简介段落与篇章要点，返回 (段落, 要点, 来源相对路径)。"""
    readme = body / "README.md"
    if not readme.is_file():
        return "", [], ""
    lines = clean_lines(read_text(readme))
    description = " ".join(lines[:2])
    titles = chapter_list(read_text(readme))
    bullets = [cut(t, 40) for t in titles[:8]] or [cut(l, 40) for l in lines[2:8]]
    return description, bullets, readme.relative_to(project).as_posix()


def count_chapters(body: Path) -> int:
    docs = body / "docs"
    return len(list(docs.glob("*.md"))) if docs.is_dir() else 0


def pick_doc_image(body: Path, project: Path) -> tuple[str, str]:
    """海报优先，退到正文插图；只收横向宽图，竖图在 16:9 卡片上会被裁掉。"""
    try:
        from PIL import Image
    except ImportError:
        Image = None

    def wide(path: Path) -> bool:
        if Image is None:
            return True
        try:
            with Image.open(io.BytesIO(path.read_bytes())) as im:
                w, h = im.size
        except Exception:
            return False
        return w >= 700 and (h == 0 or w / h >= 1.05)

    for sub, kind in (("posters", "poster"), ("assets", "screenshot"), ("docs", "screenshot")):
        found = [p for d in (sub,) for p in list(body.glob(f"{d}/*.png")) + list(body.glob(f"{d}/*.jpg"))]
        found = [p for p in found if p.stat().st_size > 15_000 and not NOISE_NAME.search(p.stem)]
        found.sort(key=lambda p: (0 if POSTER_HINT.search(p.stem) else 1, p.name))
        for path in found:
            if wide(path):
                return path.relative_to(project).as_posix(), kind
    return "", ""


def scan(project: Path) -> FoundDoc:
    body = locate_body(project)
    name = body.name if body != project else project.name.split("_", 1)[-1]
    artifact, size, art_warn = read_artifact(project)
    description, bullets, copy_source = read_copy(body, project)
    image, kind = pick_doc_image(body, project)
    doc = FoundDoc(
        slug=project.name,
        name=name,
        artifact=artifact,
        size_mb=size,
        status="live" if artifact else "coming_soon",
        chapters=count_chapters(body),
        summary=cut(description, 60) if description else "",
        description=description,
        features=bullets,
        keywords=pick_keywords(description, bullets, {"APP_NAME_CN": name}),
        image=image,
        image_kind=kind,
        copy_source=copy_source,
    )
    if art_warn:
        doc.warnings.append(art_warn)
    if not description:
        doc.warnings.append("未找到介绍文案（正文目录里没有 README.md）")
    if not image:
        doc.warnings.append("无封面图")
    return doc


def to_entry(doc: FoundDoc) -> dict:
    return {
        "slug": doc.slug,
        "name": doc.name,
        "status": doc.status,
        "category": "",
        "share_url": "",
        "share_code": "",
        "platform": "",
        "summary": doc.summary,
        "description": doc.description,
        "features": doc.features,
        "chapters": doc.chapters,
        "keywords": doc.keywords,
        "aliases": [],
        "image": doc.image,
        "image_kind": doc.image_kind,
        "artifact": doc.artifact,
        "size_mb": doc.size_mb,
        "copy_source": doc.copy_source,
        "updated": str(date.today()),
    }


def merge(existing: list[dict], founds: list[FoundDoc], force: bool = False) -> tuple[list[dict], list[str]]:
    """人工填过的字段不再改动；自动字段只在空缺时补，--force 才重新生成。"""
    by_slug = {e.get("slug"): e for e in existing if isinstance(e, dict)}
    notes: list[str] = []
    order = [e.get("slug") for e in existing if e.get("slug")] + [d.slug for d in founds if d.slug not in by_slug]
    for slug in order:
        found = next((d for d in founds if d.slug == slug), None)
        if found is None:
            continue
        entry = by_slug.get(slug)
        if entry is None:
            notes.append(f"新发现文档：{slug}")
            by_slug[slug] = to_entry(found)
            continue
        fresh = to_entry(found)
        for key in AUTO_KEYS:
            if force or not entry.get(key):
                if entry.get(key) and force and entry[key] != fresh[key] and key != "name":
                    notes.append(f"{entry.get('name') or slug}：{key} 重新生成 {entry[key]} → {fresh[key]}")
                elif not entry.get(key) and fresh[key] and key not in ("name",):
                    notes.append(f"{entry.get('name') or slug}：补全自动字段 {key}")
                entry[key] = fresh[key]
    result: list[dict] = []
    for slug in order:
        if slug in by_slug:
            result.append(by_slug[slug])
            if slug not in {d.slug for d in founds} and by_slug[slug].get("status") != "hidden":
                by_slug[slug]["status"] = "hidden"
                notes.append(f"目录消失，置为 hidden：{slug}")
    return sorted(result, key=lambda e: e.get("slug", "")), notes


def report(founds: list[FoundDoc], entries: list[dict], notes: list[str], docs_root: Path) -> None:
    by_slug = {e.get("slug"): e for e in entries if isinstance(e, dict)}
    print(f"\n文档根目录：{docs_root.as_posix()}")
    print(f"{'目录':<34}{'名称':<24}{'篇数':<6}{'发布包':<10}{'封面':<12}链接")
    print("-" * 100)
    for doc in founds:
        entry = by_slug.get(doc.slug) or {}
        links = entry_links(entry)
        pkg = f"{doc.size_mb:.1f}MB" if doc.artifact else "无"
        link = f"已填（{len(links)} 渠道）" if links else "待建"
        print(f"{doc.slug:<34}{doc.name:<24}{doc.chapters:<6}{pkg:<10}{doc.image_kind or '无':<12}{link}")
    print("-" * 100)
    for doc in founds:
        entry = by_slug.get(doc.slug) or {}
        gaps = list(doc.warnings)
        if not entry_links(entry):
            gaps.append("缺分享链接")
        if not entry.get("category"):
            gaps.append("缺分类")
        if gaps:
            print(f"· {doc.name}：{'；'.join(gaps)}")
        share_src = entry.get("artifact")
        if share_src:
            print(f"    分享用文件 → {(docs_root / doc.slug / share_src).as_posix()}")
    if notes:
        print("\n本次数据变更：")
        for note in notes:
            print(f"  {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描文档工程目录并维护 docs.yaml")
    parser.add_argument("--root", type=Path, default=None, help="文档根目录（默认取 data/paths.yaml 的 docs_root）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="数据文件路径")
    parser.add_argument("--check", action="store_true", help="只体检不写文件")
    parser.add_argument("--force", action="store_true", help=f"重新生成自动字段 {', '.join(AUTO_KEYS)}（人工字段保留）")
    args = parser.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = path_config.resolve_roots({"docs_root": str(args.root)} if args.root else None)["docs_root"]
    docs_root = root.path
    if not docs_root.is_dir():
        print(f"文档根目录不存在：{docs_root}")
        print(f"  取值 {root.value}（来源：{root.source}）；改 data/paths.yaml 的 docs_root 或用 --root 指定。")
        print("  查看全部取值来源：python tools/paths.py show")
        return 2
    projects = sorted(p for p in docs_root.iterdir() if p.is_dir() and DOC_DIR.match(p.name))
    if not projects:
        print(f"文档根目录里没有 Wxxx_ 工程：{docs_root}")
        print("  布局与默认不同时，用 `python tools/paths.py set --docs-root 路径` 改配置。")
        return 2

    founds = [scan(p) for p in projects]
    existing: list[dict] = []
    if args.out.is_file():
        loaded = yaml.safe_load(read_text(args.out)) or {}
        existing = loaded.get("docs") or []

    entries, notes = merge(existing, founds, force=args.force)
    payload = {"site": {"updated": str(date.today())}, "docs": entries}
    if not args.check:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            HEADER + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
        )
    report(founds, entries, notes, docs_root)
    print(f"\n条目 {len(entries)} 条" + ("（--check 未写文件）" if args.check else f"，已写入 {args.out.relative_to(SITE_ROOT).as_posix()}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
