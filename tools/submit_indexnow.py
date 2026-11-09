#!/usr/bin/env python3
"""把 sitemap 里的 URL 通过 IndexNow 即时提交给 Bing/Yandex 等搜索引擎。

用法：
    python tools/submit_indexnow.py               # 确认线上已更新后提交全部 URL
    python tools/submit_indexnow.py --wait 180    # 推送后调用：轮询等 Cloudflare 部署生效再提交
    python tools/submit_indexnow.py --dry-run     # 只打印要提交的 URL，不发请求

为什么先验证线上 200：IndexNow 提交的是"已经可访问的页面"，部署还没生效就提交，
引擎抓到旧内容或 404，反而损耗站点信用。key 文件本身也要在线上可达，否则验证不过。

退出码：0 提交成功（或 dry-run）；1 提交失败/超时；2 配置缺失。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import yaml

SITE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = SITE_ROOT / "data" / "shares.yaml"
DEFAULT_OUT = SITE_ROOT / "web"
ENDPOINT = "https://api.indexnow.org/indexnow"
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")


def http_status(url: str) -> int:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "HRX-Site-Publisher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0


def wait_live(urls: list[str], seconds: int) -> list[str]:
    """轮询直到全部 URL 返回 200；超时返回仍不可达的清单。"""
    deadline = time.monotonic() + seconds
    pending = list(urls)
    while pending:
        pending = [u for u in pending if http_status(u) != 200]
        if not pending:
            return []
        if time.monotonic() >= deadline:
            return pending
        print(f"等待部署生效：还有 {len(pending)} 个 URL 未就绪，10 秒后重试……", flush=True)
        time.sleep(10)
    return []


def submit(site_url: str, key: str, urls: list[str]) -> int:
    host = urlsplit(site_url).netloc
    payload = {
        "host": host,
        "key": key,
        "keyLocation": f"{site_url}/{key}.txt",
        "urlList": urls,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"IndexNow 提交成功：HTTP {resp.status}，{len(urls)} 个 URL（{host}）")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"IndexNow 提交失败：HTTP {exc.code}。")
        if exc.code == 403:
            print(f"  403 通常是 key 文件在线上不可达或内容不符：确认 https://{host}/{key}.txt 已部署且内容就是 key。")
        elif exc.code == 422:
            print("  422 通常是 URL 与 host 不匹配或页面不可访问：确认提交的都是主站域名下的线上页面。")
        elif exc.code == 429:
            print("  429 是请求过频：稍后手动重跑 python tools/submit_indexnow.py。")
        return 1
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"IndexNow 提交失败：网络错误 {exc}。稍后手动重跑 python tools/submit_indexnow.py。")
        return 1


def main() -> int:
    p = argparse.ArgumentParser(description="IndexNow 即时提交 sitemap 里的 URL")
    p.add_argument("--data", default=str(DEFAULT_DATA))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--wait", type=int, default=0, metavar="秒", help="提交前轮询等待线上部署生效的最长时间")
    p.add_argument("--dry-run", action="store_true", help="只打印要提交的 URL")
    args = p.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    doc = yaml.safe_load(Path(args.data).read_text(encoding="utf-8")) or {}
    site = doc.get("site") or {}
    site_url = str(site.get("url") or "").strip().rstrip("/")
    key = str(site.get("indexnow_key") or "").strip()
    if not site_url or not key:
        print("data/shares.yaml 的 site.url 或 site.indexnow_key 缺失，无法提交。")
        return 2
    sitemap = Path(args.out) / "sitemap.xml"
    if not sitemap.is_file():
        print(f"sitemap 不存在：{sitemap}\n先跑 python tools/build_site.py。")
        return 2
    host = urlsplit(site_url).netloc
    urls = [u for u in LOC_RE.findall(sitemap.read_text(encoding="utf-8")) if urlsplit(u).netloc == host]
    if not urls:
        print("sitemap 里没有主站域名下的 URL，无可提交。")
        return 2
    if args.dry_run:
        print(f"将提交 {len(urls)} 个 URL（dry-run，未发请求）：")
        for u in urls:
            print(f"  {u}")
        return 0

    check_urls = urls + [f"{site_url}/{key}.txt"]
    if args.wait > 0:
        not_ready = wait_live(check_urls, args.wait)
        if not_ready:
            print(f"等待 {args.wait} 秒后仍有 URL 不可达，未提交（避免把 404 推给引擎）：")
            for u in not_ready:
                print(f"  {u}")
            print("部署生效后手动重跑：python tools/submit_indexnow.py")
            return 1
    else:
        not_ready = [u for u in check_urls if http_status(u) != 200]
        if not_ready:
            print("以下 URL 线上不可达，未提交（部署还没生效？试试 --wait 180）：")
            for u in not_ready:
                print(f"  {u}")
            return 1
    return submit(site_url, key, urls)


if __name__ == "__main__":
    raise SystemExit(main())