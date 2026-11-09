#!/usr/bin/env python3
"""发布前的 SEO 断言：检查 web/ 产物，不过就别发布。

这个脚本存在的理由：构建时站点域名缺失，canonical/og/JSON-LD/sitemap 会整段消失，
而构建本身照样"成功"、产物照样能打开——这个项目踩过一次，所以把检查固化成一条命令，
而不是靠人记得去看 head。

用法：
    python tools/seo_check.py                    # 检查默认产物目录 web/
    python tools/seo_check.py --out /path/to/试构建
    python tools/seo_check.py --verbose          # 打印每一页的 title 与 canonical

退出码：0 全部通过；1 有不通过项；2 产物目录或数据文件不在。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = SITE_ROOT / "web"
DEFAULT_DATA = SITE_ROOT / "data" / "shares.yaml"

# 搜索结果里的标题按半角宽度截断，中文算 2、ASCII 算 1；超过这个宽度会被省略号砍掉。
MAX_TITLE_WIDTH = 60
MAX_LLMS_BYTES = 10 * 1024

CANONICAL_RE = re.compile(r'<link\s+rel="canonical"\s+href="([^"]+)"')
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
H1_RE = re.compile(r"<h1[\s>]")
DESC_RE = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"')
LD_JSON_RE = re.compile(r'<script\s+type="application/ld\+json">(.*?)</script>', re.S)
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")

TASK_LINK_RE = re.compile(r'<a class="task" href="([^"]+)">([^<]+)</a>')

# 「微信公众号 · X」这类写法里的 X 是外部事实（公众号名），不能拿站点品牌顶替：
# 名字对不上，读者扫码就会发现。构建改对了也得防着下次被人改回去。
WECHAT_MENTION_RE = re.compile(
    r"(?:微信公众号|关注作者公众号|关注官方公众号|扫码关注|公众号)[^。\n；;]{0,8}?HRX\s*(?:工具库|软件库|资源库|工具箱)"
)


def display_width(text: str) -> int:
    return sum(2 if ord(ch) > 0xFF else 1 for ch in text)


def expected_url(site_url: str, rel: str) -> str:
    """产物相对路径 → 对外 URL。index.html 就是站点根；其余去掉 .html 后缀——
    Cloudflare Pages 把 .html 308 到无后缀形式，收录信号必须指向最终 200 的地址。"""
    if rel == "index.html":
        return f"{site_url}/"
    return f"{site_url}/{rel[:-5] if rel.endswith('.html') else rel}"


def read_site(data_path: Path) -> dict:
    doc = yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}
    return doc.get("site") or {}


def check_wechat_names(text: str, rel: str, wechat: str) -> list[str]:
    """页面上所有提到公众号的地方，名字都得是 site.wechat_name。"""
    problems: list[str] = []
    for m in WECHAT_MENTION_RE.finditer(text):
        said = m.group(0)
        if wechat not in said:
            problems.append(f"{rel}：公众号名写成了「{said}」，应为 site.wechat_name = {wechat}")
    return problems


def check_page(html_path: Path, rel: str, site_url: str, wechat: str, titles: dict[str, str]) -> list[str]:
    problems: list[str] = []
    text = html_path.read_text(encoding="utf-8")
    want = expected_url(site_url, rel)

    canonicals = CANONICAL_RE.findall(text)
    if not canonicals:
        problems.append(f"{rel}：没有 canonical（构建时 site.url 缺失就会这样）")
    elif len(canonicals) > 1:
        problems.append(f"{rel}：canonical 有 {len(canonicals)} 个，应为 1 个")
    elif canonicals[0] != want:
        problems.append(f"{rel}：canonical 指向 {canonicals[0]}，应为 {want}")

    titles_found = TITLE_RE.findall(text)
    title = titles_found[0].strip() if titles_found else ""
    if not title:
        problems.append(f"{rel}：没有 <title>")
    else:
        width = display_width(title)
        if width > MAX_TITLE_WIDTH:
            problems.append(f"{rel}：title 半角宽度 {width} > {MAX_TITLE_WIDTH}，搜索结果里会被截断 → {title}")
        if title in titles:
            problems.append(f"{rel}：title 与 {titles[title]} 完全相同，搜索引擎会当成重复页")
        titles[title] = rel

    h1s = H1_RE.findall(text)
    if len(h1s) != 1:
        problems.append(f"{rel}：<h1> 有 {len(h1s)} 个，应为 1 个")

    if not DESC_RE.search(text):
        problems.append(f"{rel}：没有 meta description")

    blocks = LD_JSON_RE.findall(text)
    if not blocks:
        problems.append(f"{rel}：没有 JSON-LD 结构化数据")
    for i, raw in enumerate(blocks):
        try:
            json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{rel}：第 {i + 1} 段 JSON-LD 解析失败（{exc}）——引擎会整段丢弃")

    if "{{" in text:
        problems.append(f"{rel}：还留着没替换的模板占位符（{{{{...}}}}），页面有段落没渲染出来")

    if wechat:
        problems += check_wechat_names(text, rel, wechat)

    return problems


def check(out: Path, data_path: Path, verbose: bool) -> tuple[list[str], list[str]]:
    """返回 (不通过项, 参与检查的页面)。验证文件不算页面，计数也不该把它算进去。"""
    problems: list[str] = []
    site = read_site(data_path)
    brand = str(site.get("name") or "").strip()
    wechat = str(site.get("wechat_name") or "").strip()
    site_url = str(site.get("url") or "").strip().rstrip("/")
    if not site_url:
        return [f"{data_path.name} 的 site.url 未配置：没有域名就无法核对 canonical/sitemap，产物也不该发布"], []
    if not wechat:
        problems.append(
            f"{data_path.name} 的 site.wechat_name 未配置：页面提到公众号时必须用真实公众号名，"
            "拿站点品牌顶替会写出扫码对不上号的名字"
        )

    pages = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html"))
    if not pages:
        return [f"{out} 下没有任何 HTML 产物"], []
    # 站长验证文件也是 .html，但它不是页面：没有 title/h1，也绝不该进 sitemap。
    # 404.html 同理：它是错误页，noindex、无 canonical，Cloudflare Pages 靠它返回真 404。
    verify_names = {
        str(item.get("file") or "").strip() for item in (site.get("verify") or []) if isinstance(item, dict)
    }
    pages = [rel for rel in pages if rel not in verify_names and rel != "404.html"]

    notfound = out / "404.html"
    if not notfound.is_file():
        problems.append("404.html 不存在：Cloudflare Pages 对未知路径会回首页内容且状态码 200（软 404）")
    else:
        nf_text = notfound.read_text(encoding="utf-8")
        if 'name="robots"' not in nf_text or "noindex" not in nf_text:
            problems.append("404.html 缺 noindex：错误页不该被收录")

    titles: dict[str, str] = {}
    for rel in pages:
        problems += check_page(out / rel, rel, site_url, wechat, titles)
        if verbose:
            text = (out / rel).read_text(encoding="utf-8")
            print(f"  {rel}  title={TITLE_RE.findall(text)[0].strip() if TITLE_RE.search(text) else '(无)'}")

    sitemap = out / "sitemap.xml"
    if not sitemap.is_file():
        problems.append("sitemap.xml 不存在：抓取器只能靠外链偶然发现你")
    else:
        locs = set(LOC_RE.findall(sitemap.read_text(encoding="utf-8")))
        expected = {expected_url(site_url, rel) for rel in pages}
        for missing in sorted(expected - locs):
            problems.append(f"页面存在但没进 sitemap：{missing}")
        for ghost in sorted(locs - expected):
            problems.append(f"sitemap 里有页面但产物找不到：{ghost}")

    robots = out / "robots.txt"
    if not robots.is_file():
        problems.append("robots.txt 不存在")
    elif f"Sitemap: {site_url}/sitemap.xml" not in robots.read_text(encoding="utf-8"):
        problems.append("robots.txt 缺 Sitemap: 行，或指向的域名与 site.url 不一致")

    llms = out / "llms.txt"
    if not llms.is_file():
        problems.append("llms.txt 不存在")
    else:
        raw = llms.read_text(encoding="utf-8")
        if len(llms.read_bytes()) > MAX_LLMS_BYTES:
            problems.append(f"llms.txt {len(llms.read_bytes())} 字节 > {MAX_LLMS_BYTES}，AI 引擎读不完")
        if brand and not raw.startswith(f"# {brand}"):
            problems.append(f"llms.txt 首行不是站点名，应为 `# {brand}`")
        if wechat:
            problems += check_wechat_names(raw, "llms.txt", wechat)

    tasks = [t for t in (site.get("tasks") or []) if isinstance(t, dict) and str(t.get("label") or "").strip()]
    index_text = (out / "index.html").read_text(encoding="utf-8") if (out / "index.html").is_file() else ""
    rendered = TASK_LINK_RE.findall(index_text)
    if tasks and len(rendered) != len(tasks):
        problems.append(
            f"site.tasks 配了 {len(tasks)} 个任务词，首页只渲染出 {len(rendered)} 个："
            "slug 写错或目标条目没上架时，构建会静默丢掉这一项"
        )
    for href, label in rendered:
        if not (out / href).is_file():
            problems.append(f"常见需求「{label}」指向 {href}，产物里没有这个页面：这是送人进 404 的导航")
    labels = [label for _, label in rendered]
    dupes = [label for label in dict.fromkeys(labels) if labels.count(label) > 1]
    if dupes:
        problems.append("常见需求里有重复任务词：" + "、".join(dupes))

    for item in site.get("verify") or []:
        name = str(item.get("file") if isinstance(item, dict) else "").strip()
        text = str(item.get("text") if isinstance(item, dict) else "")
        if not name or not text:
            problems.append(f"site.verify 有条目缺 file 或 text：{item}")
            continue
        target = out / name
        if not target.is_file():
            problems.append(f"站长验证文件不在产物里：{name}（手工放会被下次构建清掉，要写进 site.verify）")
        elif target.read_text(encoding="utf-8") != text:
            problems.append(f"站长验证文件内容与配置不一致：{name}")

    key = str(site.get("indexnow_key") or "").strip()
    if key:
        key_file = out / f"{key}.txt"
        if not key_file.is_file():
            problems.append(f"IndexNow key 文件不在产物里：{key}.txt（搜索引擎抓不到它就无法确认推送权限）")
        elif key_file.read_text(encoding="utf-8") != key:
            problems.append(f"IndexNow key 文件内容与配置不一致：{key}.txt")

    return problems, pages


def main() -> int:
    p = argparse.ArgumentParser(description="发布前 SEO 断言")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="产物目录，默认 web/")
    p.add_argument("--data", default=str(DEFAULT_DATA), help="站点配置来源，默认 data/shares.yaml")
    p.add_argument("--verbose", action="store_true", help="打印每页 title")
    args = p.parse_args()

    out = Path(args.out).resolve()
    data_path = Path(args.data)
    if not out.is_dir():
        print(f"产物目录不存在：{out}\n先跑 python tools/build_site.py。")
        return 2
    if not data_path.is_file():
        print(f"数据文件不存在：{data_path}")
        return 2

    problems, pages = check(out, data_path, args.verbose)
    if problems:
        print(f"SEO 检查不通过（{len(problems)} 项，共 {len(pages)} 个页面）：")
        for line in problems:
            print(f"  · {line}")
        print("\n修好后重跑；确认无误再发布。")
        return 1
    print(f"SEO 检查通过：{len(pages)} 个页面，canonical/title/h1/JSON-LD/sitemap/robots/llms 全部一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
