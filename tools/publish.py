#!/usr/bin/env python3
"""构建、检查、提交并推送 Gitee/GitHub；只有 web/ 变动时才需要再发布 Qoder。"""
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


def changed_paths(*rev_args: str) -> list[str]:
    result = git("diff", "--name-only", *rev_args, check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


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

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    paths = [p for p in SITE_PATHS if (ROOT / p).exists()]
    git("add", "--", *paths, capture=False)

    staged = changed_paths("--cached")
    web_changed = any(p.startswith("web/") for p in staged)
    if staged:
        try:
            git("commit", "-m", args.message, capture=False)
        except subprocess.CalledProcessError as exc:
            print(f"提交失败（退出码 {exc.returncode}），未推送。")
            return exc.returncode or 1
    else:
        print("没有可提交的站点改动。")

    if not web_changed:
        for remote in REMOTES:
            ref = git("rev-parse", "--verify", "--quiet", f"{remote}/{branch}", check=False)
            if ref.returncode != 0:
                web_changed = True
                break
            if any(p.startswith("web/") for p in changed_paths(f"{remote}/{branch}..HEAD")):
                web_changed = True
                break

    if args.no_push:
        print("已跳过推送；" + ("web/ 有变动，推送后仍需发布 Qoder。" if web_changed else "web/ 无变动，无需发布 Qoder。"))
        return 0

    pushed: list[str] = []
    failed: list[str] = []
    for remote in REMOTES:
        if git("remote", "get-url", remote, check=False).returncode != 0:
            print(f"远端不存在，跳过：{remote}")
            continue
        if git("push", remote, branch, check=False, capture=False).returncode != 0:
            failed.append(remote)
        else:
            pushed.append(remote)
    if failed:
        print("推送失败：" + "、".join(failed) + "（其它远端已尝试；未使用强推）")
        return 1
    targets = " + ".join(pushed) or "无远端"
    print(
        f"已推送到 {targets}。Cloudflare Pages 会自动部署；"
        + ("web/ 有变动，qoder.zone 仍需在 Qoder 里发布。" if web_changed else "web/ 无变动，qoder.zone 无需发布。")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
