(function () {
  const SNAPSHOT_COOLDOWN_MS = 120;
  let coordinatedSnapshotPromise = null;
  let coordinatedSnapshotStartedAt = 0;

  const originalLoadLiveSnapshot = loadLiveSnapshot;
  const originalLoadCommodityIntel = loadCommodityIntel;
  const originalLoadMissionIntel = loadMissionIntel;
  const originalRefreshDashboardFull = refreshDashboardFull;
  const originalLoadLocalPulse = loadLocalPulse;
  const originalRefreshDashboardLive = refreshDashboardLive;

  function activeCommodityQuery() {
    return String(state.commodityQuery || "").trim();
  }

  function activeMissionQuery() {
    try {
      return String(missionBody()?.commodity_query || "").trim();
    } catch (error) {
      console.warn("missionBody", error);
      return "";
    }
  }

  function shouldCoordinateCommodityRefresh() {
    return Boolean(activeCommodityQuery());
  }

  function shouldCoordinateMissionRefresh() {
    return Boolean(activeCommodityQuery() || activeMissionQuery());
  }

  async function coordinatedSnapshot({ silent = true, useFormValues = true } = {}) {
    const now = Date.now();
    if (coordinatedSnapshotPromise && now - coordinatedSnapshotStartedAt < 15000) {
      return coordinatedSnapshotPromise;
    }
    coordinatedSnapshotStartedAt = now;
    coordinatedSnapshotPromise = originalLoadLiveSnapshot({ silent, useFormValues, applyFormDefaults: false })
      .catch(error => {
        console.error("coordinated-snapshot", error);
        throw error;
      })
      .finally(() => {
        window.setTimeout(() => {
          coordinatedSnapshotPromise = null;
        }, SNAPSHOT_COOLDOWN_MS);
      });
    return coordinatedSnapshotPromise;
  }

  loadCommodityIntel = async function (silent = false) {
    if (shouldCoordinateCommodityRefresh()) {
      await coordinatedSnapshot({ silent: true, useFormValues: true });
      if (!silent) status(`Analyse ${state.commodityIntel?.commodity_name || activeCommodityQuery()} prête.`);
      return state.commodityIntel;
    }
    return originalLoadCommodityIntel(silent);
  };

  loadMissionIntel = async function (silent = false) {
    if (shouldCoordinateMissionRefresh()) {
      await coordinatedSnapshot({ silent: true, useFormValues: true });
      if (!silent) status(`Plan mission prêt pour ${state.missionIntel?.commodity_name || activeMissionQuery() || activeCommodityQuery()}.`);
      return state.missionIntel;
    }
    return originalLoadMissionIntel(silent);
  };

  refreshDashboardFull = async function () {
    return coordinatedSnapshot({ silent: true, useFormValues: true });
  };

  loadLocalPulse = async function (options = {}) {
    if (coordinatedSnapshotPromise) return null;
    return originalLoadLocalPulse(options);
  };

  refreshDashboardLive = async function () {
    if (coordinatedSnapshotPromise) return null;
    return originalRefreshDashboardLive();
  };

  window.addEventListener("beforeunload", () => {
    coordinatedSnapshotPromise = null;
  });
})();
