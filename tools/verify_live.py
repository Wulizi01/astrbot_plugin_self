"""只读体检：检查已安装的自我插件数据是否正常。

不写库、不连 bot、不依赖 AstrBot。库不存在时返回 2。

    python tools/verify_live.py
    python tools/verify_live.py --db "C:\\...\\self.db"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "astrbot_plugin_self"
REL = Path("plugin_data") / NAME / "self.db"


def _candidates() -> list[Path]:
    """库可能落在这几种位置，按发现顺序排。

    ROOT 有两种身份，所以往上找而不是写死一层：
      已安装    <AstrBot>\\data\\plugins\\astrbot_plugin_self  ->  <AstrBot>\\data\\plugin_data\\...
      开发目录  <群bot>\\projects\\astrbot_plugin_self        ->  本机真实库在
                                                                 <群bot>\\AstrBot\\data\\plugin_data\\...
    末段那条 <*>/data/plugin_data/... 就是为开发目录准备的，AstrBot 目录叫什么都能找到。
    """
    exact: list[Path] = []
    found: list[Path] = []
    for parent in [ROOT, *ROOT.parents][:5]:
        for cand in (parent / REL, parent / "data" / REL):
            if cand not in exact:
                exact.append(cand)
        try:
            hits = sorted(parent.glob(f"*/data/{REL}"))
        except OSError:
            hits = []
        for hit in hits:
            if hit not in found:
                found.append(hit)
    return exact + found


def default_db() -> Path:
    for cand in _candidates():
        if cand.exists():
            return cand
    return _candidates()[0]


DEFAULT_DB = default_db()


def check(db: Path) -> tuple[list[tuple[str, bool, str]], int]:
    rows: list[tuple[str, bool, str]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        rows.append((name, ok, detail))

    if not db.exists():
        add("数据库存在", False, str(db))
        return rows, 2

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        profile = {
            row["key"]: row["value"] for row in conn.execute("SELECT key,value FROM profile")
        }
        narrative = str(profile.get("narrative", "")).strip('"')
        samples = int(float(profile.get("samples", 0)))
        last = int(float(profile.get("last_reflection", 0)))
        # After a reset the narrative is empty until the next reflection fires,
        # so "empty" is only a problem if samples already passed the interval.
        pending = not narrative and last == 0 and samples < 20
        add(
            "叙事状态",
            bool(narrative) or pending,
            f"{len(narrative)} 字" + ("（重置后等待反思）" if pending else ""),
        )
        add("样本数", samples > 0 or not narrative, str(samples))
        add(
            "反思标记",
            last > 0 or pending,
            f"last_reflection={last}",
        )

        born = float(profile.get("born_at", 0))
        days = int((time.time() - born) / 86400) + 1 if born else 0
        add("born_at 已写入", born > 0, f"{days} 天")

        episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        add("经历条数", episodes > 0, str(episodes))

        memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        legacy = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE scope='legacy'"
        ).fetchone()[0]
        add("记忆条数", True, f"{memories}（legacy {legacy}）")

        invalid = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE scope='group' AND (group_id IS NULL OR group_id='')"
        ).fetchone()[0]
        add("群记忆都有 group_id", invalid == 0, f"缺失 {invalid} 条")

        leak = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE scope='group' AND shareable=1 AND sensitivity<>'low'"
        ).fetchone()[0]
        add("可转述的都是 low", leak == 0, f"违规 {leak} 条")

        people = conn.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        add("成员表", True, f"{people} 人")

        advisor = conn.execute("SELECT COUNT(*) FROM advisor_log").fetchone()[0]
        add("顾问日志", True, f"{advisor} 条")
    except sqlite3.Error as exc:
        # 空文件、半截库、别的插件的库：给一句能看懂的结论，不要甩 traceback。
        add("库结构", False, f"{type(exc).__name__}: {exc}")
    finally:
        conn.close()
    return rows, 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args()
    db = Path(args.db)

    rows, code = check(db)
    if code == 2:
        print(f"找不到数据库：{db}")
        if args.db == str(DEFAULT_DB):
            print("找过这些位置：")
            for cand in _candidates():
                print(f"  {'有' if cand.exists() else '无'}  {cand}")
        print("先启动一次插件让库初始化，或用 --db 指定。")
        return 2

    width = max(len(name) for name, _, _ in rows)
    for name, ok, detail in rows:
        mark = "OK  " if ok else "FAIL"
        print(f"{mark}  {name.ljust(width)}  {detail}")
    failed = [name for name, ok, _ in rows if not ok]
    print()
    print(f"{len(rows) - len(failed)}/{len(rows)} 通过" + (f"；失败：{failed}" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
