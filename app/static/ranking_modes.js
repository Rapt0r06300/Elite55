(function () {
  const STORAGE_KEY = "elite55_route_ranking_mode";
  const LABELS = {
    profit_total: { label: "Profit brut", title: "Route la plus rentable", note: "Classe surtout par bénéfice total du trajet." },
    profit_hour: { label: "Profit / heure", title: "Route la plus rentable / h", note: "Classe surtout par rendement horaire réel." },
    fast: { label: "Trajet rapide", title: "Route la plus rapide", note: "Classe surtout par temps estimé et fluidité." },
    fresh: { label: "Ultra frais", title: "Route la plus fraîche", note: "Classe surtout par fraîcheur et confiance des données." },
  };

  state.routeRankingMode = LABELS[localStorage.getItem(STORAGE_KEY)] ? localStorage.getItem(STORAGE_KEY) : "profit_hour";

  function rankingLabel(mode = state.routeRankingMode) {
    return LABELS[mode]?.label || LABELS.profit_hour.label;
  }

  function rankingTitle(mode = state.routeRankingMode) {
    return LABELS[mode]?.title || LABELS.profit_hour.title;
  }

  function rankingNote(mode = state.routeRankingMode) {
    return LABELS[mode]?.note || LABELS.profit_hour.note;
  }

  function currentRankingMode() {
    return LABELS[state.routeRankingMode] ? state.routeRankingMode : "profit_hour";
  }

  function num(value, fallback = 0) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function asc(a, b) {
    return a - b;
  }

  function desc(a, b) {
    return b - a;
  }

  function routeByMetric(routes = [], metric = "profit_per_minute") {
    const list = [...(routes || [])];
    if (!list.length) return null;
    return list.sort((a, b) => {
      if (metric === "freshness") {
        return asc(num(a?.freshness_hours, 999999), num(b?.freshness_hours, 999999))
          || desc(num(a?.confidence_score ?? a?.route_score, 0), num(b?.confidence_score ?? b?.route_score, 0))
          || desc(num(a?.profit_per_hour, 0), num(b?.profit_per_hour, 0));
      }
      if (metric === "minutes") {
        return asc(num(a?.estimated_minutes, 999999), num(b?.estimated_minutes, 999999))
          || desc(num(a?.profit_per_minute, 0), num(b?.profit_per_minute, 0))
          || desc(num(a?.confidence_score ?? a?.route_score, 0), num(b?.confidence_score ?? b?.route_score, 0));
      }
      return desc(num(a?.[metric], 0), num(b?.[metric], 0))
        || desc(num(a?.confidence_score ?? a?.route_score, 0), num(b?.confidence_score ?? b?.route_score, 0))
        || asc(num(a?.freshness_hours, 999999), num(b?.freshness_hours, 999999));
    })[0];
  }

  function applyRankingUi() {
    document.querySelectorAll("[data-route-ranking-mode]").forEach(button => {
      button.classList.toggle("active", button.getAttribute("data-route-ranking-mode") === currentRankingMode());
    });
    const note = document.getElementById("route-ranking-note");
    if (note) note.textContent = `${rankingLabel()} • ${rankingNote()}`;
  }

  function routeRankingButtons(extraClass = "") {
    return [
      ["profit_total", "Profit brut"],
      ["profit_hour", "Profit / h"],
      ["fast", "Rapide"],
      ["fresh", "Ultra frais"],
    ].map(([mode, label]) => {
      const classes = ["preset-chip", extraClass].filter(Boolean).join(" ");
      return `<button class="${classes}" type="button" data-route-ranking-mode="${mode}">${label}</button>`;
    }).join("");
  }

  function injectRouteRankingControls() {
    if (document.getElementById("route-ranking-row")) {
      applyRankingUi();
      return;
    }

    const presetGroup = document.getElementById("route-preset-row")?.closest(".control-group");
    if (presetGroup?.parentElement) {
      const wrapper = document.createElement("div");
      wrapper.className = "control-group";
      wrapper.innerHTML = `
        <span>Classement des routes</span>
        <div id="route-ranking-row" class="chip-row">
          ${routeRankingButtons()}
        </div>
        <small id="route-ranking-note" class="mini-note"></small>
      `;
      presetGroup.parentElement.insertBefore(wrapper, presetGroup.nextSibling);
    }

    const topbarPreset = document.querySelector(".topbar-tools .preset-row");
    if (topbarPreset && !document.getElementById("route-ranking-top-row")) {
      const topbarRow = document.createElement("div");
      topbarRow.id = "route-ranking-top-row";
      topbarRow.className = "preset-row";
      topbarRow.innerHTML = routeRankingButtons("route-ranking-top-chip");
      topbarPreset.insertAdjacentElement("afterend", topbarRow);
    }

    applyRankingUi();
  }

  function withRankingModeInPath(path) {
    if (!path || typeof path !== "string") return path;
    const selectedMode = currentRankingMode();
    if (!selectedMode) return path;
    if (path.startsWith("/api/commodity-intel") || path.startsWith("/api/dashboard")) {
      const url = new URL(path, window.location.origin);
      url.searchParams.set("ranking_mode", selectedMode);
      return `${url.pathname}${url.search}${url.hash}`;
    }
    return path;
  }

  function withRankingModeInBody(body) {
    const selectedMode = currentRankingMode();
    if (!selectedMode) return body;
    if (!body || typeof body !== "string") return body;
    try {
      const parsed = JSON.parse(body);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return body;
      if (parsed.route && typeof parsed.route === "object") {
        parsed.route.ranking_mode = selectedMode;
      }
      if (parsed.mission && typeof parsed.mission === "object") {
        parsed.mission.ranking_mode = selectedMode;
      }
      parsed.ranking_mode = selectedMode;
      return JSON.stringify(parsed);
    } catch (error) {
      console.warn("ranking-body", error);
      return body;
    }
  }

  const originalApi = api;
  api = async function (path, options = {}) {
    const nextOptions = { ...options };
    const method = String(nextOptions.method || "GET").toUpperCase();
    const targetPath = withRankingModeInPath(path);
    if (["POST", "PUT", "PATCH"].includes(method) && typeof nextOptions.body === "string") {
      if (
        targetPath.startsWith("/api/routes")
        || targetPath.startsWith("/api/live-snapshot")
        || targetPath.startsWith("/api/mission-intel")
      ) {
        nextOptions.body = withRankingModeInBody(nextOptions.body);
      }
    }
    return originalApi(targetPath, nextOptions);
  };

  async function reloadRankingViews() {
    if (typeof loadLiveSnapshot === "function") {
      await loadLiveSnapshot({ silent: true, useFormValues: true });
      return;
    }
    if (typeof refreshDashboardFull === "function") {
      await refreshDashboardFull();
    }
  }

  async function setRouteRankingMode(mode) {
    if (!LABELS[mode]) mode = "profit_hour";
    if (state.routeRankingMode === mode) {
      applyRankingUi();
      return;
    }
    state.routeRankingMode = mode;
    localStorage.setItem(STORAGE_KEY, mode);
    applyRankingUi();
    status(`Classement automatique : ${rankingLabel()}.`);
    try {
      await reloadRankingViews();
      status(`Classement automatique appliqué : ${rankingLabel()}.`);
    } catch (error) {
      console.error(error);
      status(`Erreur classement : ${error.message}`);
    }
  }

  const originalRenderDashboard = renderDashboard;
  renderDashboard = function (dashboard) {
    const result = originalRenderDashboard(dashboard);
    applyRankingUi();
    return result;
  };

  const originalRenderCommodityIntel = renderCommodityIntel;
  renderCommodityIntel = function (intel) {
    const result = originalRenderCommodityIntel(intel);
    applyRankingUi();
    return result;
  };

  const originalRenderMissionIntel = renderMissionIntel;
  renderMissionIntel = function (payload) {
    const result = originalRenderMissionIntel(payload);
    applyRankingUi();
    return result;
  };

  renderHighlights = function (dashboard) {
    const commodityIntel = state.commodityIntel?.resolved ? state.commodityIntel : null;
    const route = commodityIntel?.best_routes?.[0] || dashboard?.routes?.[0] || null;
    const loop = dashboard?.loops?.[0] || null;
    const quick = commodityIntel?.quick_trade || {};
    const bestBuy = quick.best_buy;
    const bestSell = quick.best_sell;
    const bestLiveSell = quick.best_live_sell;
    const spread = quick.spread;

    document.getElementById("best-route-card").innerHTML = route
      ? `<div class="spotlight-card"><h3>${escapeHtml(rankingTitle())}</h3><span class="spotlight-main">${escapeHtml(route.commodity_name)}</span><span class="spotlight-sub">${escapeHtml(route.source_system)} / ${escapeHtml(route.source_station)} vers ${escapeHtml(route.target_system)} / ${escapeHtml(route.target_station)}</span><div class="spotlight-list"><div class="spotlight-line"><span>Profit trajet</span><strong>${escapeHtml(credits(route.trip_profit))}</strong></div><div class="spotlight-line"><span>Profit heure</span><strong>${escapeHtml(credits(route.profit_per_hour))}</strong></div><div class="spotlight-line"><span>Temps estime</span><strong>${escapeHtml(minutesLabel(route.estimated_minutes))}</strong></div><div class="spotlight-line"><span>Fraicheur / confiance</span><strong>${escapeHtml(formatHours(route.freshness_hours))} • ${escapeHtml(number(route.confidence_score || route.route_score || 0))}/100</strong></div></div></div>`
      : spotlightEmpty("Route prioritaire", "Scanne la region et laisse le moteur filtrer les routes accessibles et vraiment utiles.");

    document.getElementById("best-loop-card").innerHTML = commodityIntel
      ? `<div class="spotlight-card"><h3>Prix cibles</h3><span class="spotlight-main">${escapeHtml(commodityIntel.commodity_name || "Marchandise")}</span><span class="spotlight-sub">${bestBuy ? `${escapeHtml(bestBuy.station_name)} en achat` : "Pas d'achat visible"}${bestSell ? ` • ${escapeHtml(bestSell.station_name)} en revente` : ""}</span><div class="spotlight-list"><div class="spotlight-line"><span>Achat mini</span><strong>${bestBuy ? escapeHtml(credits(bestBuy.price)) : "n/d"}</strong></div><div class="spotlight-line"><span>Revente maxi</span><strong>${bestSell ? escapeHtml(credits(bestSell.price)) : "n/d"}</strong></div><div class="spotlight-line"><span>Ecart brut</span><strong>${spread !== null && spread !== undefined ? escapeHtml(credits(spread)) : "n/d"}</strong></div><div class="spotlight-line"><span>Revente rapide</span><strong>${bestLiveSell ? escapeHtml(bestLiveSell.station_name) : "n/d"}</strong></div></div></div>`
      : loop
        ? `<div class="spotlight-card"><h3>Boucle prioritaire</h3><span class="spotlight-main">${escapeHtml(loop.from_station)} ↔ ${escapeHtml(loop.to_station)}</span><span class="spotlight-sub">${escapeHtml(loop.from_system)} ↔ ${escapeHtml(loop.to_system)}</span><div class="spotlight-list"><div class="spotlight-line"><span>Aller</span><strong>${escapeHtml(loop.go_commodity)} • ${escapeHtml(credits(loop.go_profit))}</strong></div><div class="spotlight-line"><span>Retour</span><strong>${escapeHtml(loop.return_commodity)} • ${escapeHtml(credits(loop.return_profit))}</strong></div><div class="spotlight-line"><span>Total</span><strong>${escapeHtml(credits(loop.total_profit))}</strong></div><div class="spotlight-line"><span>Profit heure</span><strong>${escapeHtml(credits(loop.profit_per_hour))}</strong></div></div></div>`
        : spotlightEmpty("Boucle utile", "Une boucle apparaitra des que deux marches complementaires, accessibles et frais, seront disponibles.");
  };

  renderDecisionCards = function (dashboard) {
    const commodityIntel = state.commodityIntel?.resolved ? state.commodityIntel : null;
    const decisions = commodityIntel?.decision_cards || dashboard.decision_cards || {};
    const quick = commodityIntel?.quick_trade || {};
    const spread = quick.spread;
    const rankedRoutes = commodityIntel?.best_routes || dashboard?.routes || [];
    const primaryRoute = rankedRoutes[0] || decisions.primary_route || null;
    const bestMinuteRoute = routeByMetric(rankedRoutes, "profit_per_minute");
    const freshestRoute = routeByMetric(rankedRoutes, "freshness");
    const quickestRoute = routeByMetric(rankedRoutes, "minutes");
    const routeViews = commodityIntel?.route_views || dashboard.route_views || {};

    el("decision-grid").innerHTML = [
      decisionOfferCard("Acheter le moins cher", decisions.cheapest_buy, "Aucune offre d'achat exploitable."),
      decisionOfferCard("Revendre au plus haut", decisions.highest_sell, "Aucune bonne demande de vente pour le moment."),
      decisionOfferCard("Revente rapide", quick.best_live_sell || decisions.live_sell, "Aucune vente rapide et fiable."),
      spread !== null && spread !== undefined
        ? `<article class="decision-card"><span class="decision-eyebrow">Ecart brut</span><span class="decision-main">${escapeHtml(credits(spread))}</span><span class="decision-sub">${commodityIntel ? escapeHtml(commodityIntel.commodity_name) : "Marchandise active"}</span><div class="decision-kpis"><span class="badge">${decisions.cheapest_buy ? escapeHtml(credits(decisions.cheapest_buy.price)) : "n/d"} achat</span><span class="badge">${decisions.highest_sell ? escapeHtml(credits(decisions.highest_sell.price)) : "n/d"} vente</span></div></article>`
        : `<article class="decision-card"><span class="decision-eyebrow">Ecart brut</span><span class="decision-main">Pas encore</span><span class="decision-sub">Le moteur attend un achat et une revente coherents.</span></article>`,
    ].join("");

    el("route-view-grid").innerHTML = [
      decisionRouteCard(rankingTitle(), primaryRoute, "Pas encore de route prioritaire dans ce mode."),
      decisionRouteCard("Meilleure marge / minute", bestMinuteRoute, "Pas encore de route ultra rapide."),
      decisionRouteCard("La plus fraîche", freshestRoute, "Aucune route très fraîche pour le moment."),
      decisionRouteCard("Depuis mon systeme", routeViews.best_from_current_system || quickestRoute, "Aucune route exploitable depuis ton systeme actuel."),
    ].join("");
  };

  document.addEventListener("click", event => {
    const button = event.target.closest("[data-route-ranking-mode]");
    if (!button) return;
    event.preventDefault();
    setRouteRankingMode(button.getAttribute("data-route-ranking-mode"));
  });

  injectRouteRankingControls();
  applyRankingUi();
})();
