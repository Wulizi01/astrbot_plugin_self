"""Tests for the read-only health check (``tools/verify_live.py``).

The tool is the first thing anyone runs when something looks wrong, and it had
a default DB path that only worked from one of the two plugin locations, so it
gets its own suite: path resolution, the healthy case, and each FAIL branch.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import zipfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import package  # noqa: E402
import verify_live  # noqa: E402
from core.store import SelfStore  # noqa: E402


def make_db() -> tuple[SelfStore, Path]:
    path = Path(tempfile.mkdtemp()) / "self.db"
    return SelfStore(path), path


def rows_by_name(db: Path) -> dict[str, tuple[bool, str]]:
    rows, code = verify_live.check(db)
    assert code == 0, "check() 只在库不存在时返回 2"
    return {name: (ok, detail) for name, ok, detail in rows}


class PathResolutionTests(unittest.TestCase):
    def test_candidates_are_ordered_and_unique(self):
        cands = verify_live._candidates()
        self.assertGreater(len(cands), 1)
        self.assertEqual(len(cands), len(set(cands)), "候选路径不应重复")
        self.assertTrue(all(isinstance(p, Path) for p in cands))

    def test_candidates_look_inside_a_bot_named_directory(self):
        """开发目录下真实库在 <群bot>\\AstrBot\\data\\plugin_data\\...，必须能找到。

        把一个库放进 <base>/<任意机器人目录>/data 下，ROOT 指到 base，
        候选列表里就得出现它——写死一层 parents[1] 的实现过不了这条。
        """
        base = Path(tempfile.mkdtemp())
        target = base / "WhateverBot" / "data" / "plugin_data" / "astrbot_plugin_self"
        target.mkdir(parents=True)
        db = target / "self.db"
        db.write_bytes(b"")
        original = verify_live.ROOT
        try:
            verify_live.ROOT = base
            self.assertIn(db, verify_live._candidates())
        finally:
            verify_live.ROOT = original

    def test_default_db_prefers_the_first_existing_candidate(self):
        base = Path(tempfile.mkdtemp())
        nested = base / "plugin_data" / "astrbot_plugin_self" / "self.db"
        nested.parent.mkdir(parents=True)
        nested.write_bytes(b"")
        original = verify_live.ROOT
        try:
            verify_live.ROOT = base
            self.assertEqual(verify_live.default_db(), nested)
        finally:
            verify_live.ROOT = original


class CheckTests(unittest.TestCase):
    def test_missing_db_returns_two(self):
        rows, code = verify_live.check(Path(tempfile.mkdtemp()) / "nope.db")
        self.assertEqual(code, 2)
        self.assertEqual(rows[0][0], "数据库存在")
        self.assertFalse(rows[0][1])

    def test_healthy_db_passes_every_row(self):
        store, path = make_db()
        store.add_episode("user", "今天聊了很久")
        store.touch_person("1", "甲")
        store.add_memory("1", "甲", "group", "喜欢猫", "low", 1, group_id="9")
        self.assertEqual(rows_by_name(path)["经历条数"][0], True)

    def test_empty_narrative_after_reset_is_pending_not_failed(self):
        store, path = make_db()
        store.add_episode("user", "重置之后")
        store.reset_narrative()
        rows = rows_by_name(path)
        self.assertTrue(rows["叙事状态"][0], "重置后等待反思不算异常")
        self.assertIn("等待反思", rows["叙事状态"][1])

    def test_group_memory_without_group_id_fails(self):
        store, path = make_db()
        store.add_episode("user", "一条经历")
        store.add_memory("1", "甲", "group", "没有群号", "low", 0, group_id="")
        rows = rows_by_name(path)
        self.assertFalse(rows["群记忆都有 group_id"][0])
        self.assertIn("缺失 1 条", rows["群记忆都有 group_id"][1])

    def test_shareable_memory_that_is_not_low_fails(self):
        store, path = make_db()
        store.add_episode("user", "一条经历")
        store.add_memory("1", "甲", "group", "秘密", "high", 1, group_id="9")
        rows = rows_by_name(path)
        self.assertFalse(rows["可转述的都是 low"][0])
        self.assertIn("违规 1 条", rows["可转述的都是 low"][1])

    def test_database_without_schema_reports_instead_of_raising(self):
        path = Path(tempfile.mkdtemp()) / "empty.db"
        sqlite3.connect(path).close()
        rows, code = verify_live.check(path)
        self.assertEqual(code, 0)
        self.assertEqual(rows[0][0], "库结构")
        self.assertFalse(rows[0][1])

    def test_check_is_read_only(self):
        store, path = make_db()
        store.add_episode("user", "只读")
        before = path.read_bytes()
        verify_live.check(path)
        self.assertEqual(before, path.read_bytes(), "体检不能写库")


class PackageTests(unittest.TestCase):
    """打包规则：单层、正斜杠、只收该收的。"""

    def make_tree(self) -> Path:
        base = Path(tempfile.mkdtemp())
        (base / "main.py").write_text("VERSION = '9.9.9'\n", encoding="utf-8")
        (base / "metadata.yaml").write_text("name: x\nversion: 9.9.9\n", encoding="utf-8")
        (base / "README.md").write_text("# x\n", encoding="utf-8")
        (base / "panel_light.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (base / "data").mkdir()
        (base / "data" / "cmd_config.json").write_text('{"password": "leak"}', encoding="utf-8")
        (base / ".github").mkdir()
        (base / ".github" / "ci.yml").write_text("name: ci\n", encoding="utf-8")
        pages = base / "pages" / "自我"
        pages.mkdir(parents=True)
        (pages / "app.js").write_text("// hi\n", encoding="utf-8")
        cache = base / "core" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "store.cpython-312.pyc").write_bytes(b"\x00")
        (base / "core" / "store.py").write_text("x = 1\n", encoding="utf-8")
        return base

    def test_collect_takes_only_shippable_files(self):
        root = self.make_tree()
        rels = [p.as_posix() for p in package.collect(root)]
        self.assertIn("main.py", rels)
        self.assertIn("pages/自我/app.js", rels)
        self.assertIn("core/store.py", rels)
        self.assertIn("panel_light.png", rels)
        self.assertNotIn("data/cmd_config.json", rels)
        self.assertFalse(any(".github" in r for r in rels))
        self.assertFalse(any("__pycache__" in r or r.endswith(".pyc") for r in rels))

    def test_build_is_single_layer_with_posix_names(self):
        root = self.make_tree()
        out = Path(tempfile.mkdtemp())
        target = package.build(root, out)
        self.assertTrue(target.name.startswith("astrbot_plugin_self_v9.9.9_"))
        with zipfile.ZipFile(target) as archive:
            names = archive.namelist()
        self.assertTrue(all(n.startswith("astrbot_plugin_self/") for n in names))
        self.assertFalse(any("\\" in n for n in names))
        self.assertIn("astrbot_plugin_self/pages/自我/app.js", names)
        self.assertEqual(package.verify(target), [])

    def test_no_credentials_ever_ship(self):
        root = self.make_tree()
        target = package.build(root, Path(tempfile.mkdtemp()))
        with zipfile.ZipFile(target) as archive:
            payload = b"".join(archive.read(n) for n in archive.namelist())
        self.assertNotIn(b"leak", payload)

    def test_verify_catches_a_flat_archive(self):
        bad = Path(tempfile.mkdtemp()) / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("main.py", "x = 1\n")
        problems = package.verify(bad)
        self.assertTrue(problems)
        self.assertTrue(any("顶层目录" in p or "不在" in p for p in problems))

    def test_check_importable_on_a_real_build(self):
        root = self.make_tree()
        target = package.build(root, Path(tempfile.mkdtemp()))
        self.assertTrue(package.check_importable(target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
