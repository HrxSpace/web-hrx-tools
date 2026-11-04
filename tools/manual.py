#!/usr/bin/env python3
"""把用户手册（markdown）转成详情页可用的结构化正文。

手册是本项目唯一有保证的长文来源：每款软件的 用户手册/*.md 都是同一套章节意图
（简介 / 运行环境 / 安装启动 / 功能说明 / 常见问题 / 注意事项 / 问题反馈），
所以详情页正文与 FAQ 可以直接抽，不必人工再写一遍。

但章节**编号与章数并不统一**（000/001/009 是七章，006 有十章、常见问题排在第八章），
所以这里一律按标题文字定位章节角色，绝不用"第几章"。

手册里的截图不进详情页：一款手册十几张图，全量复制会把产物推到发布体积上限，
而且手册图片是相对路径、随工程走，站点拿不到稳定的可寻址副本。
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path

# 找手册的优先级：先按命名约定（*使用说明.md），再退回目录里的任意 md
MANUAL_PATTERNS = (
    "用户手册/*使用说明.md",
    "用户手册/*.md",
    "*/用户手册/*使用说明.md",
    "*/用户手册/*.md",
)

# 章节角色按标题文字匹配，顺序即优先级：先判问答，再判简介/环境/安装，最后才是注意事项
ROLE_PATTERNS = (
    ("faq", re.compile(r"常见问题|常见疑问|FAQ")),
    ("intro", re.compile(r"软件简介|产品简介|一句话定位|^简介$")),
    ("env", re.compile(r"运行环境|系统要求")),
    ("install", re.compile(r"安装与启动|安装|启动|快速上手|基本流程|使用流程|上手")),
    ("notes", re.compile(r"注意事项")),
    ("contact", re.compile(r"问题反馈|联系我们|获取支持|意见反馈")),
)

# 简介章里这块内容与卡片的功能要点重复，抽正文时丢掉
DROP_SUBHEADINGS = re.compile(r"主要功能|功能清单|功能总览|功能一览")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 章节序号只认「4.1」「四、」「4、」「4）」这类明确的分节标记；
# 不能顺手剥掉所有前导数字，否则「10 分钟快速上手」会被削成「分钟快速上手」。
NUM_PREFIX_RE = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+、|\d+(?:\.\d+)+[、.）)】]?\s*|\d+[、）)]\s*)"
)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d{1,2}[.)、])\s+")
ORDERED_RE = re.compile(r"^\s*\d{1,2}[.)、]\s+")
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEP_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
QUOTE_RE = re.compile(r"^\s*>\s?")
# 手册里「*图：页面编辑…*」这类句子是给随文截图写的说明。图片不入库，留着就成了无图之注，抽正文时丢掉。
CAPTION_RE = re.compile(r"^(?:图|截图|示意图|配图)\s*[:：]")


@dataclass
class Section:
    title: str
    html: str


@dataclass
class Manual:
    """一份手册抽出来的可渲染内容。缺的章节就是空值，构建器按有无决定渲染。"""

    path: str = ""
    intro: str = ""
    env: str = ""
    install: list[Section] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    faq: list[tuple[str, str]] = field(default_factory=list)
    notes: str = ""
    brand_fixes: int = 0

    @property
    def han_count(self) -> int:
        body = self.intro + self.env + self.notes + "".join(s.html for s in self.sections)
        body += "".join(q + a for q, a in self.faq) + "".join(s.html for s in self.install)
        return len(re.findall(r"[一-鿿]", body))


def find_manual(project_dir: Path) -> Path | None:
    for pattern in MANUAL_PATTERNS:
        hits = sorted(project_dir.glob(pattern))
        if hits:
            return hits[0]
    return None


def clean_title(text: str) -> str:
    title = NUM_PREFIX_RE.sub("", text).strip()
    title = re.sub(r"\*+", "", title).strip()
    return title


def inline_markup(text: str) -> str:
    """行内 markdown → HTML。先整体转义，只放开确实认识的标记，避免把正文当标签吃进去。"""
    out = html.escape(text, quote=False)
    out = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", out)  # 手册截图：丢掉，见模块注释
    out = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        r'<a href="\2" target="_blank" rel="noopener nofollow">\1</a>',
        out,
    )
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    return out


def render_blocks(lines: list[str]) -> str:
    """章内正文 → HTML。认标题、列表、表格、代码块、引用和段落，其余按普通段落处理。"""
    out: list[str] = []
    para: list[str] = []
    items: list[str] = []
    items_ordered = False
    rows: list[list[str]] = []
    in_code = False
    code: list[str] = []

    def flush_para() -> None:
        if para:
            joined = " ".join(para)
            para.clear()
            if CAPTION_RE.match(joined.strip("* ").strip()):
                return
            out.append(f"<p>{inline_markup(joined)}</p>")

    def flush_items() -> None:
        if not items:
            return
        tag = "ol" if items_ordered else "ul"
        out.append(f"<{tag}>" + "".join(f"<li>{inline_markup(it)}</li>" for it in items) + f"</{tag}>")
        items.clear()

    def flush_rows() -> None:
        if not rows:
            return
        head, *body = rows
        cells = lambda r: "".join(f"<td>{inline_markup(c)}</td>" for c in r)  # noqa: E731
        out.append(
            '<table class="md"><thead><tr>'
            + "".join(f"<th>{inline_markup(c)}</th>" for c in head)
            + "</tr></thead><tbody>"
            + "".join(f"<tr>{cells(r)}</tr>" for r in body)
            + "</tbody></table>"
        )
        rows.clear()

    for raw in lines:
        line = raw.rstrip()
        if FENCE_RE.match(line):
            if in_code:
                out.append(f'<pre><code>{html.escape(chr(10).join(code), quote=False)}</code></pre>')
                code, in_code = [], False
            else:
                flush_para(), flush_items(), flush_rows()
                in_code = True
            continue
        if in_code:
            code.append(raw)
            continue
        if not line.strip():
            flush_para(), flush_items(), flush_rows()
            continue
        if TABLE_ROW_RE.match(line):
            flush_para(), flush_items()
            if not TABLE_SEP_RE.match(line):
                rows.append([c.strip() for c in line.strip().strip("|").split("|")])
            continue
        if rows:
            flush_rows()
        hit = HEADING_RE.match(line)
        if hit:
            flush_para(), flush_items()
            depth = len(hit.group(1))
            tag = "h4" if depth <= 4 else "h5"
            out.append(f"<{tag}>{inline_markup(clean_title(hit.group(2)))}</{tag}>")
            continue
        if QUOTE_RE.match(line):
            flush_para(), flush_items()
            out.append(f'<p class="quote">{inline_markup(QUOTE_RE.sub("", line))}</p>')
            continue
        if LIST_RE.match(line):
            flush_para()
            ordered = bool(ORDERED_RE.match(line))
            if items and ordered != items_ordered:
                flush_items()
            items_ordered = ordered
            items.append(LIST_RE.sub("", line).strip())
            continue
        if items:
            flush_items()
        if set(line.strip()) <= set("-—="):  # 分隔线
            flush_para()
            out.append("<hr>")
            continue
        para.append(line.strip())

    if in_code and code:
        out.append(f'<pre><code>{html.escape(chr(10).join(code), quote=False)}</code></pre>')
    flush_para(), flush_items(), flush_rows()
    return "\n".join(out)


def split_chapters(text: str) -> list[tuple[str, list[str]]]:
    """按二级标题切章，返回 (标题, 该章原始行)。第一个 ## 之前的内容归到空标题章。"""
    chapters: list[tuple[str, list[str]]] = []
    title = ""
    buf: list[str] = []
    for line in text.splitlines():
        hit = HEADING_RE.match(line)
        if hit and len(hit.group(1)) == 2:
            if buf or title:
                chapters.append((title, buf))
            title, buf = clean_title(hit.group(2)), []
            continue
        buf.append(line)
    if buf or title:
        chapters.append((title, buf))
    return chapters


def chapter_role(title: str) -> str:
    for role, pattern in ROLE_PATTERNS:
        if pattern.search(title):
            return role
    return "section"


def sub_blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """章内按三级标题切块；没有三级标题就整章一块（标题为空）。"""
    blocks: list[tuple[str, list[str]]] = []
    title = ""
    buf: list[str] = []
    for line in lines:
        hit = HEADING_RE.match(line)
        if hit and len(hit.group(1)) == 3:
            if buf or title:
                blocks.append((title, buf))
            title, buf = clean_title(hit.group(2)), []
            continue
        buf.append(line)
    if buf or title:
        blocks.append((title, buf))
    return blocks


def parse(manual_path: Path, brand: str = "") -> Manual:
    """章节角色以二级标题为准，三级标题只做细化。

    为什么不能整章按小标题判角色：常见问题章的小标题是一个个疑问句
    （「打开加密 PDF 时提示需要密码？」），按小标题判会全被判成普通小节，
    FAQ 就散了。所以 faq/intro/notes 这类章内角色是粘住的，
    只有 env/install/section 允许小标题改写——用来处理「运行环境与安装启动」
    这种一章混了两类内容的写法（006 就是这样）。
    """
    text = read_text(manual_path)
    manual = Manual(path=manual_path.name)
    for title, lines in split_chapters(text):
        if not title:
            continue  # 首个 ## 之前只有文档一级标题，不是内容
        role = chapter_role(title)
        if role == "contact":
            continue
        for sub, sub_lines in sub_blocks(lines):
            sub_role = role if role in ("faq", "intro", "notes") else refine_role(sub, role)
            body = render_blocks(sub_lines)
            if not body:
                continue
            heading = sub or title
            if sub_role == "faq":
                question = sub or first_line(sub_lines)
                if question:
                    manual.faq.append((question, body))
            elif sub_role == "intro":
                if DROP_SUBHEADINGS.search(heading):
                    continue  # 与卡片功能要点重复
                manual.intro = f"{manual.intro}\n{body}".strip()
            elif sub_role == "env":
                manual.env = f"{manual.env}\n{body}".strip()
            elif sub_role == "install":
                manual.install.append(Section(heading, body))
            elif sub_role == "notes":
                manual.notes = f"{manual.notes}\n{body}".strip()
            else:
                manual.sections.append(Section(heading, body))
    if brand:
        manual.brand_fixes = apply_brand(manual, brand)
    return manual


def apply_brand(man: Manual, brand: str) -> int:
    """把正文里残留的旧品牌写法换成站点配置那一个，返回替换处数。"""
    fixes = 0

    def fix(text: str) -> str:
        nonlocal fixes
        new, n = BRAND_VARIANTS.subn(brand, text)
        fixes += n
        return new

    man.intro, man.env, man.notes = fix(man.intro), fix(man.env), fix(man.notes)
    man.sections = [Section(fix(s.title), fix(s.html)) for s in man.sections]
    man.install = [Section(fix(s.title), fix(s.html)) for s in man.install]
    man.faq = [(fix(q), fix(a)) for q, a in man.faq]
    return fixes


def refine_role(sub: str, chapter_role_name: str) -> str:
    """允许小标题把 env/install 章拆开；其余情况沿用章级角色。"""
    if not sub:
        return chapter_role_name
    own = chapter_role(sub)
    return own if own in ("env", "install") else chapter_role_name


def first_line(lines: list[str]) -> str:
    for line in lines:
        if line.strip():
            return clean_title(line)
    return ""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# 手册与推广文里出现过「HRX 工具库」「HRX 软件库」等多种写法。同一页里三个品牌名会让
# 读者困惑，也让搜索引擎与 AI 认不出这是同一个实体，所以抽取时统一成站点配置里那一个。
BRAND_VARIANTS = re.compile(r"HRX\s*(?:工具库|软件库|资源库|工具箱)")
