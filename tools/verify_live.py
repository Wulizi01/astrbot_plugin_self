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
DEFAULT_DB = ROOT.parents[1] / "plugin_data" / "astrbot_plugin_self" / "self.db"


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
        print("先启动一次插件让库初始化。")
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
