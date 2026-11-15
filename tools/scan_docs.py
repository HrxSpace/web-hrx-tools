#!/usr/bin/env python3
"""扫描文档工程目录，输出体检报告。**只读，不写任何数据文件。**

用法：
    python tools/scan_docs.py            # 体检 AI_WORD 下的 Wxxx_ 工程
    python tools/scan_docs.py --root P   # 临时指定文档根目录（默认读 data/paths.yaml）

文档工程以目录名（如 W000_WorkBuddy实战文档系列）为唯一主键。目录约定与软件工程不同，
所以单独一个扫描器，不去套 scan_jobs 的 dist/ 与 推广套件/ 假设：

    Wxxx_名称/            ← 工程根，发布版 zip 直接放在这一层
    └─ 名称/              ← 正文目录：README.md + docs/*.md + posters/ + assets/

上架真源在 catalog/：要采集新资料跑 `python tools/catalog.py intake Wxxx_名称 --doc`。
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
from scan_jobs import clean_lines, cut, pick_keywords, read_text

SITE_ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = SITE_ROOT / "catalog"
DOC_DIR = re.compile(r"^W\d{3}_")

# 封面按可信度排序：posters 是专为封面做的图，退到正文插图
POSTER_HINT = re.compile(r"(封面|主图|海报|cover)", re.I)
NOISE_NAME = re.compile(r"(二维码|qrcode|logo|图标|缩略|thumb)", re.I)




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


def catalog_state(slug: str) -> tuple[str, bool, list[dict]]:
    """catalog 里这条走到哪一步了：(status, 是否已采集, 渠道列表)。"""
    meta_file = CATALOG_DIR / slug / "meta.yaml"
    if not meta_file.is_file():
        return "", False, []
    meta = yaml.safe_load(read_text(meta_file)) or {}
    raw = meta.get("downloads")
    if isinstance(raw, dict):
        raw = [raw]
    links = [i for i in raw or [] if isinstance(i, dict) and str(i.get("url") or "").strip()]
    return str(meta.get("status") or ""), True, links


def report(founds: list[FoundDoc], docs_root: Path) -> None:
    print(f"\n文档根目录：{docs_root.as_posix()}")
    print(f"{'目录':<34}{'名称':<26}{'篇数':<6}{'发布包':<10}{'封面':<10}{'catalog':<9}{'状态':<12}链接")
    print("-" * 118)
    todo: list[tuple[str, list[str]]] = []
    for doc in founds:
        status, in_catalog, links = catalog_state(doc.slug)
        pkg = f"{doc.size_mb:.1f}MB" if doc.artifact else "无"
        link = f"{len(links)} 渠道" if links else "待建"
        print(
            f"{doc.slug:<34}{doc.name:<26}{doc.chapters:<6}{pkg:<10}{doc.image_kind or '无':<10}"
            f"{'已采集' if in_catalog else '未采集':<9}{status or '-':<12}{link}"
        )
        gaps = list(doc.warnings)
        if not in_catalog:
            gaps.append(f"未采集：python tools/catalog.py intake {doc.slug} --doc")
        elif status == "live" and not links:
            gaps.append("已上架但缺链接")
        if gaps:
            todo.append((doc.name, gaps))
        if doc.artifact:
            print(f"    {'':<10}分享用文件 → {(docs_root / doc.slug / doc.artifact).as_posix()}")
    print("-" * 118)
    if todo:
        print("\n逐条待办：")
        for name, gaps in todo:
            print(f"· {name}：{'；'.join(gaps)}")
    print(f"\ncatalog 已采集 {sum(1 for d in founds if catalog_state(d.slug)[1])} / {len(founds)} 份。")
    print("本脚本只读：采集用 catalog.py intake --doc，上架真源在 catalog/。")


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描文档工程目录，输出体检报告（只读，不改任何数据）")
    parser.add_argument("--root", type=Path, default=None, help="文档根目录（默认取 data/paths.yaml 的 docs_root）")
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

    report([scan(p) for p in projects], docs_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
