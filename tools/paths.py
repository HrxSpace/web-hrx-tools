#!/usr/bin/env python3
"""站点路径解析：配置里写相对路径，基准是本站点工程目录，整包放哪台机器都不用改。

用法：
    python tools/paths.py show                 # 打印每个根目录的取值、来源层与解析结果
    python tools/paths.py check                # 同上，任一目录不存在时以退出码 2 结束
    python tools/paths.py set --jobs-root ../AI_SOFT --docs-root ../AI_WORD
    python tools/paths.py set --local --jobs-root E:/Other/AI_SOFT   # 只改本机例外

优先级（命中即止）：
    1. 命令行 --jobs-root / --docs-root
    2. 环境变量 HRX_JOBS_ROOT / HRX_DOCS_ROOT
    3. data/paths.local.yaml   本机例外，不进版本库
    4. data/paths.yaml         团队默认，进版本库
    5. 内置默认 ../AI_SOFT、../AI_WORD
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

SITE_ROOT = Path(__file__).resolve().parents[1]
TRACKED = SITE_ROOT / "data" / "paths.yaml"
LOCAL = SITE_ROOT / "data" / "paths.local.yaml"

KEYS = ("jobs_root", "docs_root")
DEFAULTS = {"jobs_root": "../AI_SOFT", "docs_root": "../AI_WORD"}
ENV_KEYS = {"jobs_root": "HRX_JOBS_ROOT", "docs_root": "HRX_DOCS_ROOT"}


@dataclass(frozen=True)
class Root:
    key: str
    value: str
    source: str
    path: Path

    @property
    def exists(self) -> bool:
        return self.path.is_dir()

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "configured": self.value,
            "source": self.source,
            "resolved": self.path.as_posix(),
            "exists": self.exists,
        }


def resolve(value: object, base: Path = SITE_ROOT) -> Path:
    """相对值一律以站点工程目录为基准，与脚本的当前工作目录无关。"""
    raw = Path(str(value).strip()).expanduser()
    return (base / raw).resolve() if not raw.is_absolute() else raw.resolve()


def to_config_value(target: Path) -> str:
    """能相对表达就存相对形式——绝对路径一进版本库，换台机器就失效。"""
    try:
        rel = os.path.relpath(target, SITE_ROOT)
    except ValueError:  # 跨盘符无从相对，只能存绝对路径
        return target.as_posix()
    return Path(rel).as_posix()


def display_path(path: Path) -> str:
    """数据文件与产物常被写到仓库外的临时目录（试构建、占位数据验收），
    这时相对路径显示不了也不能抛异常——退回绝对路径即可。"""
    try:
        return path.resolve().relative_to(SITE_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_config(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        print(f"配置文件格式不对（应为键值映射）：{path}")
        return {}
    out = {}
    for key, value in doc.items():
        if key not in KEYS:
            print(f"提示：{path.name} 里的 {key} 不是可识别的键，已忽略。可选键：{'、'.join(KEYS)}")
            continue
        if value:
            out[str(key)] = str(value)
    return out


def resolve_roots(cli: dict[str, str] | None = None) -> dict[str, Root]:
    cli = cli or {}
    local, tracked = read_config(LOCAL), read_config(TRACKED)
    roots: dict[str, Root] = {}
    for key in KEYS:
        flag = "--" + key.replace("_", "-")
        layers = [
            (cli.get(key), f"命令行 {flag}"),
            (os.environ.get(ENV_KEYS[key]), f"环境变量 {ENV_KEYS[key]}"),
            (local.get(key), "data/paths.local.yaml（本机例外）"),
            (tracked.get(key), "data/paths.yaml"),
            (DEFAULTS[key], "内置默认（站点工程同级布局）"),
        ]
        for value, source in layers:
            if value:
                roots[key] = Root(key, str(value), source, resolve(value))
                break
    return roots


def print_roots(roots: dict[str, Root], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps([r.as_dict() for r in roots.values()], ensure_ascii=False, indent=2))
        return
    print(f"基准目录（本站点工程）：{SITE_ROOT.as_posix()}")
    for root in roots.values():
        mark = "存在" if root.exists else "不存在 ← 请修正"
        print(f"  {root.key:<10} {root.path.as_posix()}")
        print(f"  {'':<10} 取值 {root.value}（来源：{root.source}）→ {mark}")


def cmd_show(args: argparse.Namespace) -> int:
    print_roots(resolve_roots(), args.json)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    roots = resolve_roots()
    print_roots(roots, args.json)
    missing = [r for r in roots.values() if not r.exists]
    if missing:
        if not args.json:
            print("\n以下根目录在本机不存在，构建会拿不到封面与发行包：")
            for root in missing:
                print(f"  · {root.key} → {root.path.as_posix()}（来自{root.source}）")
            print("修法：改 data/paths.yaml，或写 data/paths.local.yaml，或 python tools/paths.py set --local 指定。")
        return 2
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    target = LOCAL if args.local else TRACKED
    current = read_config(target)
    for key in KEYS:
        value = getattr(args, key)
        if not value:
            continue
        raw = Path(str(value)).expanduser()
        # 相对值此时就能解析出绝对路径，再折回相对形式写盘，避免把本机盘符固化进版本库
        resolved = resolve(raw)
        current[key] = to_config_value(resolved) if raw.is_absolute() else raw.as_posix()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 站点扫描根目录配置 —— 相对路径以本站点工程目录为基准，整包换机器不用改。",
        "# 本机布局不同时，再复制一份到 data/paths.local.yaml（不进版本库），它的优先级更高。",
    ]
    body = yaml.safe_dump(current, allow_unicode=True, sort_keys=False)
    target.write_text("\n".join(lines) + "\n" + body, encoding="utf-8")
    print(f"已写入 {target.relative_to(SITE_ROOT).as_posix()}")
    print_roots(resolve_roots())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="解析/维护站点扫描根目录配置")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("show", "打印当前解析结果"), ("check", "打印并校验目录是否存在")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--json", action="store_true", help="机器可读输出")
        p.set_defaults(func=cmd_show if name == "show" else cmd_check)
    p = sub.add_parser("set", help="写入配置")
    p.add_argument("--jobs-root", dest="jobs_root")
    p.add_argument("--docs-root", dest="docs_root")
    p.add_argument("--local", action="store_true", help="写 data/paths.local.yaml（本机例外）而不是团队默认")
    p.set_defaults(func=cmd_set)
    args = parser.parse_args()
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
