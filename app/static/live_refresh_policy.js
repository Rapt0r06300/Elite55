(function () {
  function normalizeText(value) {
    return String(value || "").trim();
  }

  function createState({ cooldownMs = 180, reuseWindowMs = 15000 } = {}) {
    return {
      cooldownMs,
      reuseWindowMs,
      coordinatedSnapshotPromise: null,
      coordinatedSnapshotStartedAt: 0,
      snapshotInFlight: false,
    };
  }

  function canReuseSnapshot(state, now = Date.now()) {
    return Boolean(state.coordinatedSnapshotPromise) && (now - state.coordinatedSnapshotStartedAt) < state.reuseWindowMs;
  }

  function markSnapshotStarted(state, now = Date.now()) {
    state.coordinatedSnapshotStartedAt = now;
    state.snapshotInFlight = true;
  }

  function markSnapshotFinished(state) {
    state.snapshotInFlight = false;
  }

  function schedulePromiseRelease(state) {
    window.setTimeout(() => {
      state.coordinatedSnapshotPromise = null;
    }, state.cooldownMs);
  }

  function hasCommodityQuery(value) {
    return Boolean(normalizeText(value));
  }

  function hasMissionContext(commodityQuery, missionQuery) {
    return Boolean(normalizeText(commodityQuery) || normalizeText(missionQuery));
  }

  function readyMessage(prefix, subject, fallback) {
    const text = normalizeText(subject);
    return text ? `${prefix} ${text} prête.` : fallback;
  }

  window.LiveRefreshPolicy = {
    normalizeText,
    createState,
    canReuseSnapshot,
    markSnapshotStarted,
    markSnapshotFinished,
    schedulePromiseRelease,
    hasCommodityQuery,
    hasMissionContext,
    readyMessage,
  };
})();
