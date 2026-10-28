const SelfPageApi = (() => {
  async function get(path) {
    return request(path, { method: "GET" });
  }

  async function post(path, body) {
    return request(path, { method: "POST", body });
  }

  async function request(path, options = {}) {
    const bridge = await waitForBridge();
    if (!bridge) {
      throw new Error("没有检测到 AstrBot 插件页桥接，请从插件拓展页打开");
    }
    const url = new URL(path, "https://astrbot-plugin-page.local/");
    const endpoint = `page/${url.pathname.replace(/^\/+/, "")}`.replace(/\/+/g, "/");
    let payload;
    if (options.method === "GET") {
      const params = Object.fromEntries(url.searchParams.entries());
      payload = await bridge.apiGet(endpoint, Object.keys(params).length ? params : undefined);
    } else {
      payload = await bridge.apiPost(endpoint, options.body || {});
    }
    if (typeof payload === "string") {
      try {
        payload = JSON.parse(payload);
      } catch (error) {
        throw new Error(payload);
      }
    }
    if (!payload || payload.success === false) {
      throw new Error(payload?.error || "请求失败");
    }
    return payload.data ?? payload;
  }

  async function waitForBridge() {
    for (let i = 0; i < 30; i += 1) {
      const bridge = getBridge();
      if (bridge && typeof bridge.apiGet === "function" && typeof bridge.apiPost === "function") {
        return bridge;
      }
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
    return null;
  }

  function getBridge() {
    if (window.AstrBotPluginPage) return window.AstrBotPluginPage;
    try {
      if (window.parent && window.parent !== window && window.parent.AstrBotPluginPage) {
        return window.parent.AstrBotPluginPage;
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  return { get, post };
})();
