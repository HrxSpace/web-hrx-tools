#!/usr/bin/env python3
"""构建、检查、提交并推送 Gitee/GitHub；Qoder 主站仍需在 Qoder 里发布。"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_PATHS = ("data", "site", "tools", "web", "README.md", "requirements.txt")
REMOTES = ("origin", "github")


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def git(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=capture, check=check)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建站点、运行 SEO 断言、提交并推送 Gitee/GitHub。")
    parser.add_argument("-m", "--message", required=True, help="git 提交信息")
    parser.add_argument("--no-push", action="store_true", help="只构建和提交，不推送")
    args = parser.parse_args()

    try:
        run([sys.executable, "tools/build_site.py"])
        run([sys.executable, "tools/seo_check.py"])
    except subprocess.CalledProcessError as exc:
        print(f"构建或检查失败（退出码 {exc.returncode}），未提交。")
        return exc.returncode or 1

    paths = [p for p in SITE_PATHS if (ROOT / p).exists()]
    git("add", "--", *paths, capture=False)
    staged = git("diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        print("没有可提交的站点改动。")
    elif staged.returncode == 1:
        try:
            git("commit", "-m", args.message, capture=False)
        except subprocess.CalledProcessError as exc:
            print(f"提交失败（退出码 {exc.returncode}），未推送。")
            return exc.returncode or 1
    else:
        print("读取暂存区失败，未推送。")
        return staged.returncode

    if args.no_push:
        print("已跳过推送。")
        return 0

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    failed: list[str] = []
    for remote in REMOTES:
        if git("remote", "get-url", remote, check=False).returncode != 0:
            print(f"远端不存在，跳过：{remote}")
            continue
        if git("push", remote, branch, check=False, capture=False).returncode != 0:
            failed.append(remote)
    if failed:
        print("推送失败：" + "、".join(failed) + "（其它远端已尝试；未使用强推）")
        return 1
    print("已推送到 origin(Gitee) + github。Cloudflare Pages 会自动部署；qoder.zone 仍需在 Qoder 里发布。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
