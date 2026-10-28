/**
 * Pure helpers for the self panel, kept free of DOM so they can be unit
 * tested with plain Node.
 */
(function (root) {
  /**
   * Turn raw form values into a settings payload.
   *
   * Empty inputs mean "keep the current value" and are omitted entirely; the
   * server treats "" as "leave alone", so sending 0 here would silently reset
   * numeric settings (Number("") === 0).
   */
  function collect(fields, read) {
    const values = {};
    fields.forEach(([key, , type]) => {
      const raw = read(key);
      if (raw === null || raw === undefined) return;
      if (type === "bool") {
        values[key] = String(raw) === "true";
        return;
      }
      if (type === "int" || type === "float") {
        const text = String(raw).trim();
        if (text === "") return;
        const num = Number(text);
        if (!Number.isFinite(num)) return;
        values[key] = num;
        return;
      }
      values[key] = String(raw);
    });
    return values;
  }

  /** Human readable "几分钟前" for a unix timestamp in seconds. */
  function relTime(seconds, nowSeconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "—";
    const now = Number.isFinite(nowSeconds) ? nowSeconds : Date.now() / 1000;
    const diff = Math.max(0, Math.round(now - value));
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
    return new Date(value * 1000).toLocaleDateString();
  }

  /** Sort people by a key without mutating the input. */
  function sortPeople(items, key) {
    const copy = (items || []).slice();
    copy.sort((a, b) => {
      if (key === "affinity") {
        return Number(b.affinity || 0) - Number(a.affinity || 0);
      }
      if (key === "last_seen") {
        return Number(b.last_seen || 0) - Number(a.last_seen || 0);
      }
      return Number(b.msg_count || 0) - Number(a.msg_count || 0);
    });
    return copy;
  }

  /** Filter advisor log entries by "全部 / 失败 / route". */
  function filterLog(items, mode) {
    if (mode === "fail") {
      return (items || []).filter((item) => Number(item.ok) !== 1);
    }
    if (mode === "route") {
      return (items || []).filter((item) => item.source === "route");
    }
    return (items || []).slice();
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  const api = { collect, relTime, sortPeople, filterLog, escapeHtml };
  root.SelfForm = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
