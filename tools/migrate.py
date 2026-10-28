"""Import data from the three plugins this one replaces.

Dry-run by default; pass --apply to write. Sources are only ever read.

    python tools/migrate.py                 # 预览
    python tools/migrate.py --apply         # 写入叙事 / 倾向 / 经历
    python tools/migrate.py --apply --with-memories   # 连历史记忆一起导

默认不导记忆：旧记忆没有群号，导入后既不能在群里转述、也不会在私聊被查到，
只会在面板上变成一个会误导人的数字。真要导，它们会被标成 scope=legacy。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # `python tools\migrate.py` puts tools\ on sys.path

DATA = ROOT.parents[1]  # <AstrBot>/data
PLUGIN_DATA = DATA / "plugin_data"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def plan_profile() -> dict:
    """plastic_persona: profiles.json -> narrative / traits / episodes / born_at."""
    path = PLUGIN_DATA / "astrbot_plugin_plastic_persona" / "profiles.json"
    data = read_json(path)
    profile = data.get("__self__") or next(
        (value for value in data.values() if isinstance(value, dict)), {}
    )
    traits = profile.get("traits") or {}
    return {
        "source": str(path),
        "narrative": str(profile.get("self_narrative") or ""),
        "traits": {
            key: float(traits.get(key, default))
            for key, default in (
                ("verbosity", 0.45),
                ("warmth", 0.35),
                ("emoji", 0.15),
                ("initiative", 0.2),
            )
        },
        "samples": int(profile.get("samples") or 0),
        "born_at": float(profile.get("created_at") or 0),
        "episodes": [
            item for item in (profile.get("episodes") or []) if isinstance(item, dict)
        ][-30:],
    }


def plan_memories() -> list[dict]:
    """private_memory: private_memory.db -> memories rows."""
    path = PLUGIN_DATA / "astrbot_plugin_private_memory" / "private_memory.db"
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT speaker_id,speaker_name,scope,text,sensitivity,shareable,created_at "
                "FROM memories ORDER BY id"
            ).fetchall()
        ]
        conn.close()
        return rows
    except Exception as exc:  # noqa: BLE001
        print(f"读取 private_memory 失败: {exc}")
        return []


def apply(
    profile: dict, memories: list[dict], db_path: Path, *, with_memories: bool
) -> dict:
    from core.store import SelfStore

    store = SelfStore(db_path)
    result = {"episodes": 0, "memories": 0, "skipped_episodes": 0}

    values = {
        "narrative": profile["narrative"],
        "samples": profile["samples"],
        # Mark the imported narrative as already reflected, otherwise the first
        # reply would immediately rewrite it (samples - last >= interval).
        "last_reflection": profile["samples"],
        **profile["traits"],
    }
    if profile.get("born_at"):
        values["born_at"] = profile["born_at"]
    if profile["narrative"]:
        store.set_profile(**values)
    else:
        store.set_profile(**{k: v for k, v in values.items() if k != "narrative"})

    for episode in profile["episodes"]:
        role = str(episode.get("role") or "user")
        text = str(episode.get("text") or "")
        if not text:
            continue
        if store.episode_exists(role, text):
            result["skipped_episodes"] += 1
            continue
        store.add_episode(
            role,
            text,
            float(episode.get("importance") or 0.5),
            at=float(episode.get("at") or 0) or None,
        )
        result["episodes"] += 1

    if with_memories:
        for row in memories:
            store.add_memory(
                str(row.get("speaker_id") or ""),
                str(row.get("speaker_name") or ""),
                "legacy",
                str(row.get("text") or ""),
                str(row.get("sensitivity") or "low"),
                0,
                group_id="",
                at=float(row.get("created_at") or 0) or None,
            )
            result["memories"] += 1

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写入")
    parser.add_argument(
        "--with-memories",
        action="store_true",
        help="同时导入历史记忆（标为 legacy，不会被转述）",
    )
    parser.add_argument("--db", default=str(PLUGIN_DATA / "astrbot_plugin_self" / "self.db"))
    args = parser.parse_args()

    profile = plan_profile()
    memories = plan_memories()

    print("来源：")
    print(f"  人格  {profile['source']}")
    print("将写入：")
    print(f"  叙事  {len(profile['narrative'])} 字")
    print(f"  倾向  {profile['traits']}")
    print(f"  经历  {len(profile['episodes'])} 条")
    print(f"  样本  {profile['samples']}（并同步 last_reflection，避免立刻反思覆盖）")
    if args.with_memories:
        print(f"  记忆  {len(memories)} 条（scope=legacy，不可转述）")
    else:
        print(f"  记忆  跳过（可用 --with-memories 导入 {len(memories)} 条）")

    if not args.apply:
        print("\n这是预览。加 --apply 才会写入。")
        return 0

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"\n目标库不存在：{db_path}")
        print("先启动一次插件让库初始化，再运行本脚本。")
        return 1
    result = apply(profile, memories, db_path, with_memories=args.with_memories)
    print(
        f"\n已写入 {db_path}\n"
        f"  新增经历 {result['episodes']} 条，跳过重复 {result['skipped_episodes']} 条"
        f"，记忆 {result['memories']} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
