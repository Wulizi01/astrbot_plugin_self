"""Build the release zip for this plugin.

The packaging rules used to live in throwaway scripts, which is how a zip once
ended up with a doubled top-level directory and, on another occasion, with
backslashes in the entry names (PowerShell's Compress-Archive does that; Linux
unpacks it as one weird filename). This module is the single place that decides
what goes in and how it is named.

    python tools/package.py                    # -> ../astrbot_plugin_self_v<ver>_<stamp>.zip
    python tools/package.py --out D:\\tmp
    python tools/package.py --check            # also extract and compile-check
"""

from __future__ import annotations

import argparse
import compileall
import os
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "astrbot_plugin_self"

# Everything the running plugin needs, plus the docs and the tests that ship
# with it. Deliberately an allowlist: a stray local file should never leak into
# a package the way data/cmd_config.json almost did.
ROOT_FILES = (
    "__init__.py",
    "main.py",
    "page_api.py",
    "metadata.yaml",
    "_conf_schema.json",
    "LICENSE",
    "README.md",
    "CHANGELOG.md",
)
ROOT_GLOBS = ("panel_*.png",)
DIRS = ("core", "pages", "tests", "tools")
SKIP_DIR_NAMES = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def collect(root: Path = ROOT) -> list[Path]:
    """Files to ship, as paths relative to ``root``, sorted for reproducibility."""
    picked: list[Path] = []
    for name in ROOT_FILES:
        path = root / name
        if path.is_file():
            picked.append(path.relative_to(root))
    for pattern in ROOT_GLOBS:
        picked.extend(path.relative_to(root) for path in root.glob(pattern) if path.is_file())
    for dirname in DIRS:
        base = root / dirname
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if SKIP_DIR_NAMES & set(path.parts):
                continue
            if path.suffix in SKIP_SUFFIXES:
                continue
            picked.append(path.relative_to(root))
    return sorted(picked, key=lambda p: p.as_posix())


def build(root: Path = ROOT, out: Path | None = None, prefix: str = PREFIX) -> Path:
    """Write the zip and return its path. Never includes ignored local data."""
    root = Path(root)
    version = read_version(root)
    out = Path(out) if out else root.parent
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    target = out / f"{prefix}_v{version}_{stamp}.zip"
    # One top-level directory, always. zipfile writes forward slashes for the
    # arcname we pass, so as_posix() is all we need.
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in collect(root):
            archive.write(root / rel, f"{prefix}/{rel.as_posix()}")
    return target


def read_version(root: Path = ROOT) -> str:
    text = (Path(root) / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def verify(target: Path, prefix: str = PREFIX) -> list[str]:
    """Structural checks; returns a list of problems (empty means fine)."""
    problems: list[str] = []
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        if not names:
            return ["zip 是空的"]
        for name in names:
            if not name.startswith(f"{prefix}/"):
                problems.append(f"不在 {prefix}/ 下：{name}")
            if "\\" in name:
                problems.append(f"条目里有反斜杠：{name}")
            if "__pycache__" in name or name.endswith((".pyc", ".db")):
                problems.append(f"不该打包：{name}")
        tops = {name.split("/")[0] for name in names}
        if tops != {prefix}:
            problems.append(f"顶层目录不唯一：{sorted(tops)}")
        for info in archive.infolist():
            if any(ord(ch) > 127 for ch in info.filename) and not info.flag_bits & 0x800:
                problems.append(f"非 ASCII 文件名缺 UTF-8 标志：{info.filename}")
    return problems


def check_importable(target: Path) -> bool:
    """Extract to a temp dir and byte-compile everything we ship."""
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(target) as archive:
            archive.extractall(tmp)
        return compileall.compile_dir(os.path.join(tmp, PREFIX), quiet=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打发布包")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out", default="")
    parser.add_argument("--check", action="store_true", help="打包后解压并编译检查")
    args = parser.parse_args(argv)

    root = Path(args.root)
    target = build(root, Path(args.out) if args.out else None)
    problems = verify(target)
    print(f"包：{target}")
    print(f"文件：{len(collect(root))} 个，{target.stat().st_size} 字节")
    if problems:
        for problem in problems:
            print(f"FAIL  {problem}")
        return 1
    print("结构：OK（单层目录、正斜杠、无 pycache）")
    if args.check and not check_importable(target):
        print("FAIL  compileall 未通过")
        return 1
    if args.check:
        print("编译：OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
