(function () {
  const LIVE_ENDPOINTS = [
    "/api/local-pulse",
    "/api/live-snapshot",
    "/api/commodity-intel",
    "/api/mission-intel",
    "/api/routes",
  ];
  const REQUEST_TIMEOUT_MS = 12000;
  const activeControllers = new Map();
  const recentStatus = { message: null, at: 0 };

  function shouldGuard(path) {
    return LIVE_ENDPOINTS.some(prefix => typeof path === "string" && path.startsWith(prefix));
  }

  function guardedStatus(message) {
    const now = Date.now();
    if (recentStatus.message === message && now - recentStatus.at < 1200) return;
    recentStatus.message = message;
    recentStatus.at = now;
    status(message);
  }

  const originalApi = api;
  api = async function (path, options = {}) {
    const key = typeof path === "string" ? path.split("?")[0] : String(path || "");
    const guarded = shouldGuard(key);
    const nextOptions = { ...options };
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(new Error("timeout")), REQUEST_TIMEOUT_MS);

    if (guarded) {
      const previous = activeControllers.get(key);
      if (previous) {
        try {
          previous.abort(new Error("superseded"));
        } catch (error) {
          console.warn("abort-previous", error);
        }
      }
      activeControllers.set(key, controller);
    }

    nextOptions.signal = controller.signal;

    try {
      const payload = await originalApi(path, nextOptions);
      return payload;
    } catch (error) {
      const message = String(error?.message || error || "Erreur inconnue");
      if (/superseded|AbortError/i.test(message)) {
        throw error;
      }
      if (/timeout/i.test(message)) {
        guardedStatus("Une requete a pris trop de temps. Le logiciel garde la derniere vue stable.");
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
      if (guarded && activeControllers.get(key) === controller) {
        activeControllers.delete(key);
      }
    }
  };

  const originalLoadLocalPulse = loadLocalPulse;
  loadLocalPulse = async function (options = {}) {
    try {
      return await originalLoadLocalPulse(options);
    } catch (error) {
      const message = String(error?.message || error || "Erreur inconnue");
      if (/superseded|AbortError/i.test(message)) return null;
      throw error;
    }
  };

  const originalRefreshDashboardLive = refreshDashboardLive;
  refreshDashboardLive = async function () {
    try {
      return await originalRefreshDashboardLive();
    } catch (error) {
      const message = String(error?.message || error || "Erreur inconnue");
      if (/superseded|AbortError/i.test(message)) return null;
      throw error;
    }
  };

  const originalRefreshDashboardFull = refreshDashboardFull;
  refreshDashboardFull = async function () {
    try {
      return await originalRefreshDashboardFull();
    } catch (error) {
      const message = String(error?.message || error || "Erreur inconnue");
      if (/superseded|AbortError/i.test(message)) return null;
      throw error;
    }
  };

  window.addEventListener("unhandledrejection", event => {
    const reason = String(event.reason?.message || event.reason || "Erreur inconnue");
    if (/superseded|AbortError/i.test(reason)) {
      event.preventDefault();
      return;
    }
    console.error("unhandledrejection", event.reason);
  });
})();
