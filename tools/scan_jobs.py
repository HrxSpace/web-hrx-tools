#!/usr/bin/env python3
"""扫描编号软件目录，生成/增量维护 data/shares.yaml，并输出内容体检报告。

用法：
    python tools/scan_jobs.py              # 扫描并写回 shares.yaml（只补空字段，不覆盖人工内容）
    python tools/scan_jobs.py --check      # 只体检，不写文件
    python tools/scan_jobs.py --root PATH  # 指定软件根目录（默认取本站点同级目录）

条目以目录名（如 000_PDF超级工具箱）为唯一主键。人工维护的字段一旦填写就不再被脚本改动，
脚本只负责发现新软件、填空缺字段，并把漂移（版本变化/发行包更换/缺链接/缺封面）报告出来。
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

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS_ROOT = SITE_ROOT.parent
DEFAULT_OUT = SITE_ROOT / "data" / "shares.yaml"
NUM_DIR = re.compile(r"^\d{3}_")

HEADER = """\
# 网盘分享站点数据源 —— 唯一真源，人工维护
#
# 字段说明：
#   slug            主键，等于软件目录名，不要手改（改了就等于删旧增新）
#   name / name_en  商品名（卡片主标题）与英文名（搜索用）
#   exe_name        发行包/进程名，用户搜索时可能直接搜它
#   version         对外版本号
#   status          live=上架 / coming_soon=即将上架（灰态卡片） / hidden=完全不渲染
#   downloads       多网盘渠道列表，填了优先于下面的三件套（提取码建议加引号）：
#                     - platform: 夸克网盘
#                       url: https://pan.quark.cn/s/xxxx
#                       code: '1A2B'        # 可留空
#                       note: 无需登录        # 可留空
#   share_url       单渠道快捷写法：网盘分享链接；留空则不下发到页面
#   share_code      单渠道快捷写法：提取码/访问码，随链接展示并支持复制
#   platform        单渠道快捷写法：网盘平台名
#   category        分类标签，用于筛选栏
#   summary         卡片上的一句话（建议 30~60 字）
#   description     详情段落，建议直接取自用户手册的软件简介
#   features        功能要点列表，参与搜索
#   keywords        额外搜索词（用户可能的叫法、同义词）
#   image           封面图路径，相对软件根目录；脚本会自动挑选真实界面截图
#   artifact        发行包路径，相对软件根目录（你据此去建分享）
#   size_mb         发行包体积（MB），仅用于分享前核对
#   copy_source     简介抽取来源，人工改写后仍可保留作为出处
#   discovered      脚本自动发现的值，仅供对照，不参与渲染
#
# 新增软件：把目录放进软件根目录，跑 `python tools/scan_jobs.py`，再填链接。
# 生成站点：`python tools/build_site.py`，产物在 web/。

"""

# 简介抽取优先级：越靠前越接近最终用户口径
COPY_SOURCES = (
    ("用户手册/*使用说明.md", "section"),
    ("推广套件/共享信息.md", "table"),
    ("README.md", "section"),
    ("*/README.md", "section"),
    ("README.txt", "block"),
    ("dist/*/README.txt", "block"),
    ("dist/*/使用说明.txt", "block"),
    ("docs/00-设计总览.md", "section"),
    ("*/docs/00-设计总览.md", "section"),
)
INTRO_HEADINGS = r"(软件简介|一句话定位|产品简介|^简介|功能简介)"
# 目录名可信度：推广/手册目录是成品截图，docs 下多是开发验收图
IMAGE_DIRS = ("推广套件", "用户手册", "推广文章", "演示视频")
META_LINE = re.compile(
    r"^(技术栈|版本|平台|网络|操作系统|主程序|主窗口标题|配置与日志目录|源码|依赖|作者|安装|运行|打包|环境)"
)
NOISE_NAME = re.compile(r"(改前|支持作者|关于|硬广|qrcode|gaoyong|jixiang|promo|icon_|logo|海报|缩略)")
CONST_RE = re.compile(
    r"^\s*(APP_NAME_EN|APP_NAME|APP_SLUG|APP_VERSION|PROCESS_NAME|__version__)"
    r"\s*=\s*[\"']([^\"']+)[\"']",
    re.M,
)
SENT_SPLIT = re.compile(r"(?<=[。！？])\s*")
CLAUSE_SPLIT = re.compile(r"(?<=[。！？：、，;；])")

# --force 会重新生成的字段（人工填写的 share_*/category/aliases/name/status 等永不动）
AUTO_KEYS = (
    "name_en",
    "exe_name",
    "version",
    "artifact",
    "artifact_dir",
    "size_mb",
    "summary",
    "description",
    "features",
    "keywords",
    "image",
    "image_kind",
    "copy_source",
)


@dataclass
class Found:
    """一个编号目录里挖出来的原始信息。"""

    slug: str
    name: str = ""
    name_en: str = ""
    exe_name: str = ""
    version: str = ""
    artifact: str = ""
    artifact_dir: str = ""
    size_mb: float = 0.0
    status: str = "coming_soon"
    summary: str = ""
    description: str = ""
    features: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    image: str = ""
    image_kind: str = ""
    copy_source: str = ""
    project_dir: str = ""
    warnings: list[str] = field(default_factory=list)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def locate_project(project: Path) -> Path:
    """003 这类项目在子目录里，找到真正含 pyproject/src 的那层。"""
    if (project / "src").is_dir() or (project / "pyproject.toml").is_file():
        return project
    for child in sorted(project.iterdir()):
        if child.is_dir() and not child.name.startswith((".", "__")):
            if (child / "src").is_dir() or (child / "pyproject.toml").is_file():
                return child
    return project


def read_identity(base: Path) -> dict[str, str]:
    """按 app_info/info.py > 包 __init__.py > pyproject 的优先级合并身份常量。"""
    ordered: list[Path] = []
    for pattern in (
        "src/*/config/info.py",
        "src/common/app_info.py",
        "src/common/paths.py",
        "src/*/__init__.py",
        "src/__init__.py",
        "*/config/info.py",
        "*/info.py",
        "*/paths.py",
        "*/__init__.py",
        "common/app_info.py",
    ):
        ordered.extend(sorted(base.glob(pattern)))
    merged: dict[str, str] = {}
    for path in ordered:
        rel = path.relative_to(base).as_posix()
        if re.match(r"^(build|dist|legacy_[^/]|tests)[/]", rel) or "_internal" in rel:
            continue
        for key, value in CONST_RE.findall(read_text(path)):
            merged.setdefault(key, value)
    name = merged.get("APP_NAME", "")
    if name:
        # 「窗口管家 WinButler」这类中文名里混了英文后缀，拆到 name_en
        parts = name.split()
        if len(parts) == 2 and re.match(r"^[A-Za-z]", parts[1]):
            merged.setdefault("APP_NAME_CN", parts[0])
            merged.setdefault("APP_NAME_EN", parts[1])
    py = base / "pyproject.toml"
    if py.is_file():
        text = read_text(py)
        for key, pattern in (
            ("PY_NAME", r'^name\s*=\s*"([^"]+)"'),
            ("PY_VERSION", r'^version\s*=\s*"([^"]+)"'),
            ("PY_DESC", r'^description\s*=\s*"([^"]+)"'),
        ):
            hit = re.search(pattern, text, re.M)
            if hit:
                merged.setdefault(key, hit.group(1))
    if "APP_NAME_EN" not in merged:
        readme = base / "README.md"
        if readme.is_file():
            generic = {"GUI", "CLI", "API", "APP", "TOOL", "TOOLS", "WIN", "WINDOWS", "PRO", "DESKTOP"}
            for hit in re.finditer(r"^#\s+\S+\s+([A-Za-z][\w\-]{2,})\s*$", read_text(readme), re.M):
                if hit.group(1).upper() not in generic:
                    merged["APP_NAME_EN"] = hit.group(1)
                    break
    return merged


def read_artifact(base: Path, project: Path) -> tuple[str, float, str, str, str]:
    """返回 (zip相对路径, 体积MB, exe名, 警告, onedir相对路径)。exe 名以 spec 声明为准。"""
    zips = sorted(project.glob("dist/*.zip")) + sorted(project.glob("*/dist/*.zip"))
    onedir = ""
    for dist_dir in sorted(project.glob("dist")) + sorted(project.glob("*/dist")):
        subs = [d for d in dist_dir.iterdir() if d.is_dir() and (d / f"{d.name}.exe").exists()] if dist_dir.is_dir() else []
        if subs:
            onedir = max(subs, key=lambda d: d.stat().st_mtime).relative_to(project).as_posix()
            break
    spec_names = []
    for spec in sorted(base.glob("*.spec")):
        spec_names += re.findall(r'^\s*name\s*=\s*[\'"]([^\'"]+)[\'"]', read_text(spec), re.M)
    if not zips:
        return "", 0.0, (spec_names or [""])[0], "", onedir
    newest = max(zips, key=lambda p: p.stat().st_mtime)
    rel = newest.relative_to(project).as_posix()
    stem = newest.stem
    hit = re.match(r"^(?P<exe>.+?)_v(?P<ver>\d[\w.\-]*?)(?:_win[_-]?x64)?$", stem, re.I)
    exe = hit.group("exe") if hit else stem
    warn = ""
    if spec_names and exe not in spec_names:
        warn = f"发行包名 {exe} 与 spec 声明 {spec_names[0]} 不一致，对外名称需统一"
    return rel, round(newest.stat().st_size / 1048576, 1), exe or (spec_names or [""])[0], warn, onedir


def clean_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "|", ">", "!", "```", "---", "==")):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = re.sub(r"^\d{1,2}[.、]\s*", "", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        if set(line) <= set("=-—*·. "):
            continue
        if META_LINE.match(line):
            continue
        out.append(line)
    return out


def cut(text: str, limit: int) -> str:
    """取一句话作为卡片副标题：优先完整首句，超长则退到子句边界，而不是跳到第二句。"""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    first = next((p.strip() for p in SENT_SPLIT.split(text) if p.strip()), text)
    if len(first) <= limit:
        return first
    window = first[:limit]
    for marker in ("：", ":", "、", "，", ","):
        idx = window.rfind(marker)
        if idx >= max(14, limit // 3):
            return window[:idx].strip()
    return window.rstrip("，,、;；:： ") + "…"


def _from_markdown(path: Path) -> tuple[str, list[str]]:
    text = read_text(path)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("#") and re.search(INTRO_HEADINGS, line):
            start = i + 1
            break
        if re.match(r"^\*\*[^*]+[:：]\*\*\s*\S", line):
            return line, []
    if start is None:  # 退而取一级标题后的第一段
        for i, line in enumerate(lines):
            if line.startswith("# "):
                start = i + 1
                break
    body: list[str] = []
    rows: list[str] = []
    for line in lines[start:] if start is not None else []:
        if line.startswith("#"):
            if re.search(r"(主要功能|功能清单|功能总览|功能一览)", line):
                body += [l for l in lines[start:] if re.match(r"^\s*[-*]\s+", l)]
            break
        if line.lstrip().startswith("|"):
            rows.append(line)
            continue
        body.append(line)
    prose_lines = [l for l in body if not re.match(r"^\s*[-*+]\s+", l)]
    bullet_lines = [l for l in body if re.match(r"^\s*[-*+]\s+", l)]
    prose = clean_lines("\n".join(prose_lines))
    bullets = clean_lines("\n".join(bullet_lines))
    cells = [
        re.sub(r"\*+", "", c.strip().strip("|"))
        for c in rows
        if not set(c.replace("|", "").strip()) <= set("-: ")
    ]
    modules = [c.split("|")[0].strip() for c in cells]
    modules = [m for m in modules if m and m not in ("模块", "功能", "能力") and len(m) <= 16]
    return " ".join(prose[:4]), (bullets + modules)[:8]


def _from_table(path: Path) -> tuple[str, list[str]]:
    for line in read_text(path).splitlines():
        if "一句话定位" in line and "|" in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[-1]:
                return cells[-1], []
    return "", []


def _from_block(path: Path) -> tuple[str, list[str]]:
    text = read_text(path)
    slogan = next((l for l in clean_lines("\n".join(text.splitlines()[:6])) if "——" in l), "")
    for tag in ("简介", "产品简介", "软件简介", "软件说明"):
        block = re.search(rf"【{tag}】\s*\n(.*?)(?=\n【|\Z)", text, re.S)
        if not block:
            continue
        prose = clean_lines(block.group(1))
        if tag == "软件说明" and slogan:
            return slogan, prose[:8]
        if slogan and tag != "软件说明":
            return " ".join([slogan] + prose[:3]), prose[:8]
        return " ".join(prose[:3]), prose[:8]
    lines = clean_lines(text)
    return (slogan or " ".join(lines[1:4])), lines[1:8]


def extract_copy(base: Path, project: Path, identity: dict[str, str]) -> tuple[str, list[str], str]:
    """按优先级找简介，返回 (段落, 功能要点, 来源相对路径)。"""
    for pattern, kind in COPY_SOURCES:
        for path in sorted(base.glob(pattern)) or []:
            if any(part.startswith(".") for part in path.parts) or "_internal" in path.parts:
                continue
            getter = {"section": _from_markdown, "table": _from_table, "block": _from_block}[kind]
            try:
                para, bullets = getter(path)
            except (OSError, IndexError):
                continue
            if len(para) >= 15:
                rel = path.relative_to(project).as_posix()
                head = re.sub(r"\s+", " ", para)
                bullets = [b for b in bullets if b and b not in head and head.find(b[:12]) < 0]
                return para, bullets, rel
    desc = identity.get("PY_DESC", "")
    return desc, [], "pyproject.toml description" if desc else ""


def pick_keywords(description: str, bullets: list[str], identity: dict[str, str]) -> list[str]:
    words: list[str] = []
    for source in (description, *bullets):
        tail = re.search(r"支持[:：]?(.*)", source)
        for piece in re.split(r"[/、，,；;]| \+ ", tail.group(1) if tail else source):
            piece = piece.strip(" 。.（）()「」\"'\"")
            piece = re.sub(r"[——\-].*$", "", piece).strip()
            piece = re.sub(r"[\"'“”]", "", piece)
            if 2 <= len(piece) <= 10 and not piece.isdigit():
                words.append(piece)
            if len(words) > 24:
                break
    for key in ("APP_NAME_CN", "APP_NAME_EN", "PY_NAME"):
        if identity.get(key):
            words.append(identity[key])
    seen: list[str] = []
    for w in words:
        if w in seen or re.search(r"[：:|。！]|的\s|了\s|\d+\s*个|等$", w):
            continue
        seen.append(w)
    return seen[:12]


def pick_image(project: Path, base: Path) -> tuple[str, str]:
    """优先真实界面截图（按目录可信度打分），退到应用图标。"""
    try:
        from PIL import Image
    except ImportError:
        Image = None

    scored: list[tuple[float, Path]] = []
    for rank, sub in enumerate(IMAGE_DIRS):
        for path in project.glob(f"**/{sub}/images/*.png"):
            if path.stat().st_size < 15_000 or NOISE_NAME.search(path.stem):
                continue
            bonus = -6 if re.search(r"(主界面|主窗口)", path.stem) else 0.0
            bonus += -2 if path.stem.startswith("01") else 0.0
            scored.append((rank * 20 + bonus, path))
    for path in project.glob("**/docs/**/*.png"):
        if re.search(r"(主界面|主窗口)", path.stem) and not NOISE_NAME.search(path.stem):
            scored.append((90.0, path))

    def ok(path: Path, min_w: int) -> bool:
        if Image is None:
            return True
        try:
            with Image.open(io.BytesIO(path.read_bytes())) as im:
                w, h = im.size
        except Exception:
            return False
        return w >= min_w and (h == 0 or w / h >= 1.05)

    for _, path in sorted(scored, key=lambda c: (c[0], c[1].as_posix())):
        if ok(path, 900):
            return path.relative_to(project).as_posix(), "screenshot"

    icons = [p for pat in ("**/resources/icon*/*.png", "**/resources/icons/*.png") for p in base.glob(pat)]
    icons += [base / "app.png", base / "icon.png"]
    for path in icons:
        stem = path.stem.lower()
        if stem in ("app", "icon", "app_icon", "application") and path.is_file():
            return path.relative_to(project).as_posix(), "icon"
    return "", ""


def scan(project: Path) -> Found:
    base = locate_project(project)
    identity = read_identity(base)
    artifact, size, exe, art_warn, artifact_dir = read_artifact(base, project)
    description, bullets, copy_source = extract_copy(base, project, identity)
    image, kind = pick_image(project, base)
    name = identity.get("APP_NAME_CN") or identity.get("APP_NAME") or project.name.split("_", 1)[-1]
    ascii_names = [
        v
        for v in (identity.get("APP_NAME_EN"), exe, identity.get("PY_NAME", "").replace("-", " ").title())
        if v and v.isascii()
    ]
    name_en = ascii_names[0] if ascii_names else ""
    found = Found(
        slug=project.name,
        name=name,
        name_en=name_en,
        exe_name=exe or identity.get("APP_SLUG", ""),
        version=identity.get("APP_VERSION") or identity.get("__version__") or identity.get("PY_VERSION", ""),
        artifact=artifact,
        artifact_dir=artifact_dir,
        size_mb=size,
        status="live" if (artifact or artifact_dir) else "coming_soon",
        summary=cut(description, 60) if description else "",
        description=description,
        features=[cut(b, 40) for b in bullets[:8]] if bullets else [],
        keywords=pick_keywords(description, bullets, identity),
        image=image,
        image_kind=kind,
        copy_source=copy_source,
        project_dir=project.name if base == project else base.relative_to(project).as_posix(),
    )
    if art_warn:
        found.warnings.append(art_warn)
    if not artifact and not artifact_dir:
        found.warnings.append("未打包，暂无发行包可分享")
    elif not artifact:
        found.warnings.append(f"只有 onedir 目录，分享前需压缩：{artifact_dir}")
    if not description:
        found.warnings.append("未找到用户向简介")
    if kind != "screenshot":
        found.warnings.append("无真实界面截图" + (f"（退到 {kind}）" if kind else ""))
    if found.version and artifact and found.version not in artifact:
        found.warnings.append(f"版本漂移：源码 {found.version}，发行包 {artifact}")
    return found


def to_entry(found: Found) -> dict:
    return {
        "slug": found.slug,
        "name": found.name,
        "name_en": found.name_en,
        "exe_name": found.exe_name,
        "version": found.version,
        "status": found.status,
        "category": "",
        "share_url": "",
        "share_code": "",
        "platform": "",
        "summary": found.summary,
        "description": found.description,
        "features": found.features,
        "keywords": found.keywords,
        "aliases": [],
        "image": found.image,
        "image_kind": found.image_kind,
        "artifact": found.artifact,
        "artifact_dir": found.artifact_dir,
        "size_mb": found.size_mb,
        "copy_source": found.copy_source,
        "updated": str(date.today()),
    }


def merge(existing: list[dict], founds: list[Found], force: bool = False) -> tuple[list[dict], list[str]]:
    by_slug = {e.get("slug"): e for e in existing if isinstance(e, dict)}
    notes: list[str] = []
    order = [e.get("slug") for e in existing if e.get("slug")] + [f.slug for f in founds if f.slug not in by_slug]
    result = []
    for found in founds:
        entry = by_slug.get(found.slug)
        if entry is None:
            result.append(to_entry(found))
            notes.append(f"新增 {found.slug}")
            continue
        draft = to_entry(found)
        for key, value in draft.items():
            if key in ("slug", "updated"):
                continue
            cur = entry.get(key)
            if force and key in AUTO_KEYS and value and cur != value:
                entry[key] = value
                notes.append(f"刷新 {found.slug}.{key}")
            elif cur in (None, "", []) and value:
                entry[key] = value
                notes.append(f"补全 {found.slug}.{key}")
        entry["discovered"] = {
            "version": found.version,
            "artifact": found.artifact,
            "image": found.image,
            "project_dir": found.project_dir,
        }
        result.append(entry)
    for slug in order:
        if slug and not any(r.get("slug") == slug for r in result):
            by_slug[slug]["status"] = "hidden"
            notes.append(f"目录消失，置为 hidden：{slug}")
            result.append(by_slug[slug])
    return sorted(result, key=lambda e: e.get("slug", "")), notes


def entry_links(entry: dict) -> list[dict]:
    raw = entry.get("downloads")
    if isinstance(raw, dict):
        raw = [raw]
    links = [i for i in raw or [] if isinstance(i, dict) and str(i.get("url") or "").strip()]
    if not links and str(entry.get("share_url") or "").strip():
        links = [{"url": entry["share_url"]}]
    return links


def report(founds: list[Found], entries: list[dict], notes: list[str], jobs_root: Path) -> None:
    by_slug = {e.get("slug"): e for e in entries if isinstance(e, dict)}
    pairs = [(f, by_slug.get(f.slug) or {}) for f in founds]
    print(f"\n扫描根目录：{jobs_root}")
    print(f"{'目录':<26}{'商品名':<16}{'版本':<9}{'发行包':<10}{'封面':<12}链接")
    print("-" * 100)
    for found, entry in pairs:
        pkg = f"{found.size_mb:.0f}MB" if found.artifact else ("onedir" if found.artifact_dir else "无")
        img = found.image_kind or "无"
        links = entry_links(entry)
        link = f"已填（{len(links)} 渠道）" if links else "待建"
        print(f"{found.slug:<26}{found.name:<16}{found.version or '-':<9}{pkg:<10}{img:<12}{link}")
    print("-" * 100)
    for found, entry in pairs:
        gaps = list(found.warnings)
        if not entry_links(entry):
            gaps.append("缺分享链接")
        if not entry.get("category"):
            gaps.append("缺分类")
        if gaps:
            print(f"· {found.name}：{'；'.join(gaps)}")
        share_src = entry.get("artifact") or entry.get("artifact_dir")
        if share_src:
            print(f"    分享用文件 → {(jobs_root / found.slug / share_src).as_posix()}")
    if notes:
        print("\n本次数据变更：")
        for note in notes:
            print(f"  {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描软件目录并维护 shares.yaml")
    parser.add_argument("--root", type=Path, default=DEFAULT_JOBS_ROOT, help="软件根目录")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="数据文件路径")
    parser.add_argument("--check", action="store_true", help="只体检不写文件")
    parser.add_argument("--force", action="store_true", help=f"重新生成自动字段 {', '.join(AUTO_KEYS)}（人工字段保留）")
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    jobs_root = args.root.resolve()
    if not jobs_root.is_dir():
        print(f"软件根目录不存在：{jobs_root}")
        return 2
    projects = sorted(p for p in jobs_root.iterdir() if p.is_dir() and NUM_DIR.match(p.name))
    if not projects:
        print(f"{jobs_root} 下没有以三位数字开头的目录")
        return 2

    founds = [scan(p) for p in projects]
    existing = []
    if args.out.is_file():
        loaded = yaml.safe_load(read_text(args.out)) or {}
        existing = loaded.get("shares") or []

    entries, notes = merge(existing, founds, force=args.force)
    payload = {
        "site": {"jobs_root": str(jobs_root).replace("\\", "/"), "updated": str(date.today())},
        "shares": entries,
    }
    if args.check:
        notes = []
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(HEADER + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8")
    report(founds, entries, notes, jobs_root)
    print(f"\n条目 {len(entries)} 条" + ("（--check 未写文件）" if args.check else f"，已写入 {args.out.relative_to(SITE_ROOT).as_posix()}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
