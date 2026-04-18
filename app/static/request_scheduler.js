(function () {
  const Policy = window.LiveRefreshPolicy || {
    createState: () => ({ cooldownMs: 180, reuseWindowMs: 15000, coordinatedSnapshotPromise: null, coordinatedSnapshotStartedAt: 0, snapshotInFlight: false }),
    normalizeText: value => String(value || "").trim(),
    hasCommodityQuery: value => Boolean(String(value || "").trim()),
    hasMissionContext: (commodityQuery, missionQuery) => Boolean(String(commodityQuery || "").trim() || String(missionQuery || "").trim()),
    readyMessage: (prefix, subject, fallback) => (String(subject || "").trim() ? `${prefix} ${String(subject || "").trim()} prête.` : fallback),
    canReuseSnapshot: (state, now = Date.now()) => Boolean(state.coordinatedSnapshotPromise) && (now - state.coordinatedSnapshotStartedAt) < state.reuseWindowMs,
    markSnapshotStarted: (state, now = Date.now()) => { state.coordinatedSnapshotStartedAt = now; state.snapshotInFlight = true; },
    markSnapshotFinished: state => { state.snapshotInFlight = false; },
    schedulePromiseRelease: state => { window.setTimeout(() => { state.coordinatedSnapshotPromise = null; }, state.cooldownMs); },
  };

  const refreshState = Policy.createState({ cooldownMs: 180, reuseWindowMs: 15000 });

  const originalLoadLiveSnapshot = loadLiveSnapshot;
  const originalLoadCommodityIntel = loadCommodityIntel;
  const originalLoadMissionIntel = loadMissionIntel;
  const originalRefreshDashboardFull = refreshDashboardFull;
  const originalLoadLocalPulse = loadLocalPulse;
  const originalRefreshDashboardLive = refreshDashboardLive;

  function activeCommodityQuery() {
    return Policy.normalizeText(state.commodityQuery || "");
  }

  function activeMissionQuery() {
    try {
      return Policy.normalizeText(missionBody()?.commodity_query || "");
    } catch (error) {
      console.warn("missionBody", error);
      return "";
    }
  }

  function shouldCoordinateCommodityRefresh() {
    return Policy.hasCommodityQuery(activeCommodityQuery()) && !refreshState.snapshotInFlight;
  }

  function shouldCoordinateMissionRefresh() {
    return Policy.hasMissionContext(activeCommodityQuery(), activeMissionQuery()) && !refreshState.snapshotInFlight;
  }

  async function coordinatedSnapshot({ silent = true, useFormValues = true } = {}) {
    const now = Date.now();
    if (Policy.canReuseSnapshot(refreshState, now)) {
      return refreshState.coordinatedSnapshotPromise;
    }
    Policy.markSnapshotStarted(refreshState, now);
    refreshState.coordinatedSnapshotPromise = originalLoadLiveSnapshot({ silent, useFormValues, applyFormDefaults: false })
      .catch(error => {
        console.error("coordinated-snapshot", error);
        throw error;
      })
      .finally(() => {
        Policy.markSnapshotFinished(refreshState);
        Policy.schedulePromiseRelease(refreshState);
      });
    return refreshState.coordinatedSnapshotPromise;
  }

  loadCommodityIntel = async function (silent = false) {
    if (shouldCoordinateCommodityRefresh()) {
      await coordinatedSnapshot({ silent: true, useFormValues: true });
      if (!silent) status(Policy.readyMessage("Analyse", state.commodityIntel?.commodity_name || activeCommodityQuery(), "Analyse marchandise prête."));
      return state.commodityIntel;
    }
    return originalLoadCommodityIntel(silent);
  };

  loadMissionIntel = async function (silent = false) {
    if (shouldCoordinateMissionRefresh()) {
      await coordinatedSnapshot({ silent: true, useFormValues: true });
      if (!silent) status(Policy.readyMessage("Plan mission", state.missionIntel?.commodity_name || activeMissionQuery() || activeCommodityQuery(), "Plan mission prêt."));
      return state.missionIntel;
    }
    return originalLoadMissionIntel(silent);
  };

  refreshDashboardFull = async function () {
    if (refreshState.snapshotInFlight && refreshState.coordinatedSnapshotPromise) return refreshState.coordinatedSnapshotPromise;
    return coordinatedSnapshot({ silent: true, useFormValues: true });
  };

  loadLocalPulse = async function (options = {}) {
    if (refreshState.snapshotInFlight || refreshState.coordinatedSnapshotPromise) return null;
    return originalLoadLocalPulse(options);
  };

  refreshDashboardLive = async function () {
    if (refreshState.snapshotInFlight || refreshState.coordinatedSnapshotPromise) return null;
    return originalRefreshDashboardLive();
  };

  window.addEventListener("beforeunload", () => {
    refreshState.coordinatedSnapshotPromise = null;
    refreshState.snapshotInFlight = false;
  });
})();
