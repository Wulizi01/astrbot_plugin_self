/**
 * Node tests for the panel's pure helpers.
 *
 *   node tests/test_form.js
 *
 * Locks two classes of bug:
 *   - Number("") === 0: empty numeric fields must be omitted, not written as 0
 *   - display helpers (relative time, sorting, filtering) must stay pure
 */
const assert = require("assert");
const {
  collect,
  relTime,
  sortPeople,
  filterLog,
  escapeHtml,
} = require("../pages/自我/form.js");

const FIELDS = [
  ["advisor_temperature", "温度", "float"],
  ["advisor_per_hour", "每小时上限", "int"],
  ["advisor_trigger_policy", "触发策略", "select"],
  ["advisor_enabled", "启用", "bool"],
];
const DEFAULTS = { advisor_trigger_policy: "keywords", advisor_enabled: "true" };

function run(overrides) {
  return collect(FIELDS, (key) =>
    Object.prototype.hasOwnProperty.call(overrides, key)
      ? overrides[key]
      : DEFAULTS[key] ?? ""
  );
}

// Empty numeric fields are omitted, not turned into 0.
const emptied = run({ advisor_temperature: "", advisor_per_hour: "" });
assert.ok(!("advisor_temperature" in emptied), "empty float must be omitted");
assert.ok(!("advisor_per_hour" in emptied), "empty int must be omitted");
assert.strictEqual(emptied.advisor_trigger_policy, "keywords");

// Real values are parsed.
const filled = run({ advisor_temperature: "0.8", advisor_per_hour: "5" });
assert.strictEqual(filled.advisor_temperature, 0.8);
assert.strictEqual(filled.advisor_per_hour, 5);

// Garbage is ignored instead of written as 0.
assert.ok(!("advisor_temperature" in run({ advisor_temperature: "abc" })));

// Whitespace counts as empty.
assert.ok(!("advisor_per_hour" in run({ advisor_per_hour: "   " })));

// Booleans come from the select, not from truthiness of "false".
assert.strictEqual(run({ advisor_enabled: "false" }).advisor_enabled, false);

// Relative time.
const now = 1_700_000_000;
assert.strictEqual(relTime(now - 10, now), "刚刚");
assert.strictEqual(relTime(now - 180, now), "3 分钟前");
assert.strictEqual(relTime(now - 7200, now), "2 小时前");
assert.strictEqual(relTime(now - 86400 * 3, now), "3 天前");
assert.strictEqual(relTime(0, now), "—");

// Sorting must not mutate the input and must honour the key.
const people = [
  { name: "a", msg_count: 3, affinity: 0.1, last_seen: 30 },
  { name: "b", msg_count: 9, affinity: 0.6, last_seen: 10 },
  { name: "c", msg_count: 5, affinity: 0.3, last_seen: 20 },
];
assert.deepStrictEqual(
  sortPeople(people, "msg_count").map((p) => p.name),
  ["b", "c", "a"]
);
assert.deepStrictEqual(
  sortPeople(people, "affinity").map((p) => p.name),
  ["b", "c", "a"]
);
assert.deepStrictEqual(
  sortPeople(people, "last_seen").map((p) => p.name),
  ["a", "c", "b"]
);
assert.strictEqual(people[0].name, "a", "input must not be reordered");

// Log filtering.
const log = [
  { ok: 1, source: "route" },
  { ok: 0, source: "route" },
  { ok: 1, source: "page" },
];
assert.strictEqual(filterLog(log, "all").length, 3);
assert.strictEqual(filterLog(log, "fail").length, 1);
assert.strictEqual(filterLog(log, "route").length, 2);

// Escaping covers quotes too (attributes, not just text nodes).
assert.strictEqual(escapeHtml('a"b'), "a&quot;b");
assert.strictEqual(escapeHtml("a'b"), "a&#39;b");
assert.strictEqual(escapeHtml("<x>"), "&lt;x&gt;");

console.log("test_form.js: all assertions passed");
