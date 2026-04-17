const AUTO_REFRESH_MS = 2000;
const USAGE_REFRESH_MIN_INTERVAL_MS = 15000;
const USAGE_REGION_REFRESH_MIN_INTERVAL_MS = 45000;

function readStoredJson(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch (error) {
    console.warn("stored-json", key, error);
    return fallback;
  }
}

const state = {
  dashboard: null,
  names: null,
  commodityIntel: null,
  missionIntel: null,
  commodityQuery: localStorage.getItem("elite_plug_focus_commodity") || "gold",
  tradeMode: localStorage.getItem("elite_plug_trade_mode") || "buy",
  tradeLens: localStorage.getItem("elite_plug_trade_lens") || "absolute",
  appMode: localStorage.getItem("elite55_app_mode") || "commerce",
  autoRefreshTimer: null,
  autoRefreshBusy: false,
  fullRefreshBusy: false,
  sourceRefreshBusy: false,
  lastUsageRefreshAt: 0,
  lastRegionRefreshAt: 0,
  memory: null,
  navigationSelection: readStoredJson("elite55_navigation_selection"),
  autocomplete: new Map(),
};

const NAME_TYPE_LABELS = {
  commodity: "Marchandise",
  commodity_category: "Catégorie",
  module: "Module",
  ship: "Vaisseau",
  material: "Matériau",
  economy: "Économie",
  government: "Gouvernement",
  security: "Sécurité",
  term: "Terme",
};

const ROUTE_PRESETS = {
  express: { maxAgeHours: 24, maxStationDistance: 1500, minProfitUnit: 800, includePlanetary: false, includeSettlements: false, includeCarriers: false, noSurprise: true, maxResults: 20 },
  balanced: { maxAgeHours: 72, maxStationDistance: 5000, minProfitUnit: 1000, includePlanetary: true, includeSettlements: false, includeCarriers: false, noSurprise: true, maxResults: 25 },
  ultra_fresh: { maxAgeHours: 8, maxStationDistance: 3000, minProfitUnit: 500, includePlanetary: true, includeSettlements: false, includeCarriers: false, noSurprise: true, maxResults: 20 },
  bulk: { maxAgeHours: 96, maxStationDistance: 10000, minProfitUnit: 1500, includePlanetary: true, includeSettlements: false, includeCarriers: false, noSurprise: false, maxResults: 35 },
};

function el(id) {
  return document.getElementById(id);
}

function safeText(id, message) {
  const node = el(id);
  if (node) node.textContent = message;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function number(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  return new Intl.NumberFormat("fr-FR").format(Number(value));
}

function compactNumber(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  return new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 }).format(Number(value));
}

function credits(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  return `${number(Math.round(Number(value)))} Cr`;
}

function text(value, fallback = "n/d") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function normalizeLookup(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function status(message) {
  safeText("status-line", message);
}

function liveStatus(message) {
  safeText("live-refresh-status", message);
}

async function copyText(value) {
  const textValue = String(value || "").trim();
  if (!textValue) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(textValue);
      return true;
    }
  } catch (error) {
    console.warn("clipboard-write", error);
  }
  const probe = document.createElement("textarea");
  probe.value = textValue;
  probe.setAttribute("readonly", "readonly");
  probe.style.position = "fixed";
  probe.style.left = "-9999px";
  document.body.appendChild(probe);
  probe.select();
  try {
    const ok = document.execCommand("copy");
    document.body.removeChild(probe);
    return ok;
  } catch (error) {
    console.warn("clipboard-fallback", error);
    document.body.removeChild(probe);
    return false;
  }
}

function signalUiFailure(message, detail = "") {
  const fullMessage = `${message}${detail ? ` ${detail}` : ""}`.trim();
  const banner = el("engine-status-banner");
  if (banner) banner.classList.add("engine-banner-error");
  safeText("engine-status-message", fullMessage);
  status(fullMessage);
  liveStatus(fullMessage);
}

function bindEvent(id, eventName, handler) {
  const node = el(id);
  if (!node) {
    const message = `Element manquant: ${id}`;
    console.error(message);
    signalUiFailure("Erreur interface.", message);
    return null;
  }
  node.addEventListener(eventName, handler);
  return node;
}

function formatTimestamp(value) {
  if (!value) return "Jamais";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return text(value, "Jamais");
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function formatHours(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return text(value);
  if (numeric < 1) return `${Math.max(1, Math.round(numeric * 60))} min`;
  return `${numeric.toFixed(1).replace(".", ",")} h`;
}

function distanceLy(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  return `${Number(value).toFixed(1).replace(".", ",")} Ly`;
}

function distanceLs(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  return `${number(Math.round(Number(value)))} Ls`;
}

function minutesLabel(value) {
  if (value === null || value === undefined || value === "") return "n/d";
  return `${number(Math.round(Number(value)))} min`;
}

function activeJumpRange() {
  const routeJump = Number(el("route-jump-range")?.value);
  if (Number.isFinite(routeJump) && routeJump > 0) return routeJump;
  const overrideJump = Number(el("jump-range-override")?.value);
  if (Number.isFinite(overrideJump) && overrideJump > 0) return overrideJump;
  const playerJump = Number(state.dashboard?.player?.jump_range_override ?? state.dashboard?.player?.jump_range ?? 0);
  if (Number.isFinite(playerJump) && playerJump > 0) return playerJump;
  return 15;
}

function estimateJumps(distanceLy, jumpRange, mode = "balanced") {
  const numericDistance = Number(distanceLy);
  const numericRange = Number(jumpRange);
  if (!Number.isFinite(numericDistance) || numericDistance <= 0 || !Number.isFinite(numericRange) || numericRange <= 0) {
    return null;
  }
  const efficiency = mode === "express" ? 0.95 : mode === "neutron" ? 3.6 : 0.82;
  return Math.max(1, Math.ceil(numericDistance / Math.max(numericRange * efficiency, 1)));
}

function estimateTravelMinutes(distanceLy, distanceLs, jumpRange, mode = "balanced") {
  const jumps = estimateJumps(distanceLy, jumpRange, mode);
  if (jumps === null) return null;
  const lsValue = Number(distanceLs);
  const supercruise = Number.isFinite(lsValue) && lsValue > 0 ? lsValue / 900 : 0;
  const jumpMinutes = mode === "express" ? 1.35 : mode === "neutron" ? 1.2 : 1.6;
  const routeSetup = mode === "neutron" ? 4.5 : 2.2;
  return Math.max(4.0, jumps * jumpMinutes + supercruise + routeSetup);
}

function numericValue(id, fallback = 0) {
  const value = Number(el(id).value);
  return Number.isFinite(value) ? value : fallback;
}

function isEditingUi() {
  const active = document.activeElement;
  if (!active) return false;
  if (active.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(active.tagName);
}

function safeSetValue(id, value, force = false) {
  const node = el(id);
  if (!node) return;
  if (!force && document.activeElement === node) return;
  const next = value === null || value === undefined ? "" : String(value);
  if (node.value !== next) node.value = next;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || "Erreur inconnue");
  return payload;
}

function statCard(label, value) {
  return `<div class="stat-card"><span class="stats-label">${escapeHtml(label)}</span><span class="stats-value">${escapeHtml(value)}</span></div>`;
}

function metricCard(label, value, detail) {
  return `<div class="metric-card"><span class="metric-label">${escapeHtml(label)}</span><span class="metric-value">${escapeHtml(value)}</span><span class="metric-detail">${escapeHtml(detail)}</span></div>`;
}

function marketStripCard(label, value, detail = "", tone = "") {
  return `<article class="market-strip-card ${escapeHtml(tone)}"><span class="market-strip-label">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><span>${escapeHtml(detail)}</span></article>`;
}

function actionButton(label, dataset = {}, extraClass = "") {
  const attrs = Object.entries(dataset)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => {
      const attr = String(key).replace(/[A-Z]/g, match => `-${match.toLowerCase()}`);
      return `data-${attr}="${escapeHtml(value)}"`;
    })
    .join(" ");
  const cssClass = `copy-btn ${extraClass}`.trim();
  return `<button class="${cssClass}" type="button" ${attrs}>${escapeHtml(label)}</button>`;
}

function scoreBadge(score, label) {
  const numeric = Number(score || 0);
  const tone = numeric >= 85 ? "good" : numeric >= 65 ? "warn" : "bad";
  return `<span class="score-pill score-${tone}">${escapeHtml(number(numeric))}/100 • ${escapeHtml(label || "n/d")}</span>`;
}

function spotlightEmpty(title, message) {
  return `<div class="spotlight-card"><h3>${escapeHtml(title)}</h3><span class="spotlight-main">Pas encore d'opportunité</span><span class="spotlight-sub">${escapeHtml(message)}</span></div>`;
}

function setChipActive(attribute, activeValue) {
  document.querySelectorAll(`[${attribute}]`).forEach(node => {
    node.classList.toggle("active", node.getAttribute(attribute) === String(activeValue));
  });
}

function setAppMode(mode) {
  state.appMode = mode === "combat" ? "combat" : "commerce";
  localStorage.setItem("elite55_app_mode", state.appMode);
  document.body.dataset.appMode = state.appMode;
  document.querySelectorAll("[data-side-tab]").forEach(node => {
    node.classList.toggle("active", node.getAttribute("data-side-tab") === state.appMode);
  });
  if (state.dashboard) {
    renderPlayer(state.dashboard.player || {}, state.dashboard);
    renderCombatPanel(state.dashboard);
  }
}

function commodityFavoriteIds() {
  const memory = state.memory || state.dashboard?.trader_memory || {};
  return new Set(((memory.favorites || {}).commodity || []).map(item => String(item.id || "").toLowerCase()));
}

function currentCommoditySelection() {
  if (state.commodityIntel?.resolved && state.commodityIntel.symbol) {
    return {
      symbol: state.commodityIntel.symbol,
      label: state.commodityIntel.commodity_name || state.commodityIntel.symbol,
    };
  }
  const raw = (el("commodity-focus-input")?.value || state.commodityQuery || "").trim();
  if (!raw) return null;
  return { symbol: raw, label: raw };
}

function renderFavoriteCommodityButton() {
  const button = el("btn-favorite-commodity");
  if (!button) return;
  const current = currentCommoditySelection();
  if (!current) {
    button.textContent = "Basculer favori";
    button.classList.remove("active");
    return;
  }
  const active = commodityFavoriteIds().has(String(current.symbol).toLowerCase());
  button.textContent = active ? "Retirer des favoris" : "Ajouter aux favoris";
  button.classList.toggle("active", active);
}

function renderEngineStatus(engineStatus) {
  if (!engineStatus) return;
  const banner = el("engine-status-banner");
  if (banner) banner.classList.remove("engine-banner-error");
  const message = el("engine-status-message");
  if (message) message.textContent = engineStatus.message || "Moteur trader pret.";
}

function clearSelectionData(input) {
  if (!input?.dataset) return;
  delete input.dataset.selectedKind;
  delete input.dataset.selectedId;
  delete input.dataset.selectedLabel;
  delete input.dataset.selectedSecondary;
  delete input.dataset.selectedSymbol;
  delete input.dataset.selectedSystem;
  delete input.dataset.selectedStation;
  delete input.dataset.selectedEntryType;
}

function suggestionFromInput(input) {
  if (!input?.dataset?.selectedKind) return null;
  return {
    kind: input.dataset.selectedKind,
    entity_id: input.dataset.selectedId || input.value.trim(),
    label: input.dataset.selectedLabel || input.value.trim(),
    secondary: input.dataset.selectedSecondary || "",
    meta: {
      symbol: input.dataset.selectedSymbol || null,
      system_name: input.dataset.selectedSystem || null,
      station_name: input.dataset.selectedStation || null,
      entry_type: input.dataset.selectedEntryType || null,
    },
  };
}

function applySuggestionToInput(input, item) {
  if (!input || !item) return;
  input.value = item.label || item.entity_id || "";
  input.dataset.selectedKind = item.kind || "";
  input.dataset.selectedId = item.entity_id || "";
  input.dataset.selectedLabel = item.label || "";
  input.dataset.selectedSecondary = item.secondary || "";
  input.dataset.selectedSymbol = item.meta?.symbol || "";
  input.dataset.selectedSystem = item.meta?.system_name || "";
  input.dataset.selectedStation = item.meta?.station_name || "";
  input.dataset.selectedEntryType = item.meta?.entry_type || "";
  const systemSourceId = input.dataset.suggestSystemSource;
  if (systemSourceId && item.kind === "station" && item.meta?.system_name) {
    const related = el(systemSourceId);
    if (related) {
      related.value = item.meta.system_name;
      related.dataset.selectedKind = "system";
      related.dataset.selectedId = item.meta.system_name;
      related.dataset.selectedLabel = item.meta.system_name;
      related.dataset.selectedSystem = item.meta.system_name;
    }
  }
}

async function rememberSelection(kind, entityId, label, secondary = null, extra = null) {
  if (!kind || !entityId || !label) return;
  try {
    const payload = await api("/api/trader-memory/track", {
      method: "POST",
      body: JSON.stringify({
        kind,
        entity_id: entityId,
        label,
        secondary,
        extra,
      }),
    });
    renderMemory(payload);
  } catch (error) {
    console.warn("memory-track", error);
  }
}

async function toggleCurrentCommodityFavorite() {
  const current = currentCommoditySelection();
  if (!current) return;
  const payload = await api("/api/trader-memory/toggle-favorite", {
    method: "POST",
    body: JSON.stringify({
      kind: "commodity",
      entity_id: current.symbol,
      label: current.label,
    }),
  });
  renderMemory(payload);
}

function commodityQueryFromInput(id) {
  const input = el(id);
  const suggestion = suggestionFromInput(input);
  if (suggestion?.kind === "commodity") {
    return suggestion.meta?.symbol || suggestion.entity_id || input.value.trim();
  }
  return input.value.trim();
}

function systemQueryFromInput(id) {
  const input = el(id);
  if (!input) return "";
  const suggestion = suggestionFromInput(input);
  if (suggestion?.kind === "system") {
    return suggestion.meta?.system_name || suggestion.entity_id || suggestion.label || input.value.trim();
  }
  if (suggestion?.kind === "station") {
    return suggestion.meta?.system_name || suggestion.secondary || input.value.trim();
  }
  return input.value.trim();
}

function stationQueryFromInput(id) {
  const input = el(id);
  if (!input) return "";
  const suggestion = suggestionFromInput(input);
  if (suggestion?.kind === "station") {
    return suggestion.meta?.station_name || suggestion.label || suggestion.entity_id || input.value.trim();
  }
  return input.value.trim();
}

function currentPlayerSystemName() {
  return state.dashboard?.player?.current_system || state.dashboard?.current_market?.system_name || "";
}

function currentPlayerStationName() {
  return state.dashboard?.player?.current_station || state.dashboard?.current_market?.station_name || "";
}

function playerIsAt(systemName, stationName = "") {
  const currentSystem = normalizeLookup(currentPlayerSystemName());
  const currentStation = normalizeLookup(currentPlayerStationName());
  if (!systemName) return false;
  if (normalizeLookup(systemName) !== currentSystem) return false;
  if (!stationName) return true;
  return normalizeLookup(stationName) === currentStation;
}

function persistNavigationSelection() {
  if (!state.navigationSelection) {
    localStorage.removeItem("elite55_navigation_selection");
    return;
  }
  localStorage.setItem("elite55_navigation_selection", JSON.stringify(state.navigationSelection));
}

function setNavigationSelection(selection, { persist = true } = {}) {
  state.navigationSelection = selection || null;
  if (persist) persistNavigationSelection();
  renderNavigationPanel();
}

function activeNavigationTarget() {
  const selection = state.navigationSelection;
  if (!selection) return null;
  if (selection.type === "route") {
    const useTarget = playerIsAt(selection.source_system, selection.source_station);
    return {
      mode: "route",
      leg: useTarget ? "target" : "source",
      role_label: useTarget ? "Etape vente" : "Etape achat",
      system_name: useTarget ? selection.target_system : selection.source_system,
      station_name: useTarget ? selection.target_station : selection.source_station,
      distance_ly: useTarget ? selection.target_distance_ly : selection.source_distance_ly,
      distance_ls: useTarget ? selection.target_distance_ls : selection.source_distance_ls,
      commodity_name: selection.commodity_name || "",
      trip_profit: selection.trip_profit,
      unit_profit: selection.unit_profit,
      source_system: selection.source_system,
      source_station: selection.source_station,
      target_system: selection.target_system,
      target_station: selection.target_station,
      route_score: selection.route_score,
      estimated_minutes: selection.estimated_minutes,
    };
  }
  return {
    mode: "station",
    leg: selection.role || "station",
    role_label: selection.role_label || "Destination",
    system_name: selection.system_name,
    station_name: selection.station_name,
    distance_ly: selection.distance_ly,
    distance_ls: selection.distance_ls,
    price: selection.price,
    price_label: selection.price_label,
    detail: selection.detail,
  };
}

function defaultNavigationSelection() {
  const intel = state.commodityIntel;
  if (!intel?.resolved) return null;
  const quick = intel.quick_trade || {};
  if (state.tradeMode === "buy") {
    const buy = state.tradeLens === "assisted" ? (quick.best_near_buy || quick.best_buy) : quick.best_buy;
    if (buy) {
      return {
        type: "station",
        role: "buy",
        role_label: state.tradeLens === "assisted" ? "Achat pratique" : "Achat mini",
        system_name: buy.system_name,
        station_name: buy.station_name,
        distance_ly: buy.distance_from_player_ly,
        distance_ls: buy.distance_ls,
        price: buy.price,
        price_label: "Achat",
        detail: intel.commodity_name,
      };
    }
  }
  const sell = state.tradeLens === "assisted" ? (quick.best_live_sell || quick.best_sell) : quick.best_sell;
  if (sell) {
    return {
      type: "station",
      role: "sell",
      role_label: state.tradeLens === "assisted" ? "Vente pratique" : "Revente maxi",
      system_name: sell.system_name,
      station_name: sell.station_name,
      distance_ly: sell.distance_from_player_ly,
      distance_ls: sell.distance_ls,
      price: sell.price,
      price_label: "Vente",
      detail: intel.commodity_name,
    };
  }
  const route = (intel.best_routes || [])[0];
  if (!route) return null;
  return {
    type: "route",
    role_label: "Trajet direct",
    commodity_name: route.commodity_name,
    trip_profit: route.trip_profit,
    unit_profit: route.unit_profit,
    route_score: route.route_score,
    estimated_minutes: route.estimated_minutes,
    source_system: route.source_system,
    source_station: route.source_station,
    source_distance_ly: route.distance_from_player_ly,
    source_distance_ls: route.source_distance_ls,
    target_system: route.target_system,
    target_station: route.target_station,
    target_distance_ly: null,
    target_distance_ls: route.target_distance_ls,
  };
}

function setSystemInputValue(id, systemName) {
  const input = el(id);
  if (!input) return;
  if (!systemName) {
    safeSetValue(id, "", true);
    clearSelectionData(input);
    return;
  }
  applySuggestionToInput(input, {
    kind: "system",
    entity_id: systemName,
    label: systemName,
    secondary: "",
    meta: { system_name: systemName },
  });
}

function setStationInputValue(systemId, stationId, systemName, stationName) {
  setSystemInputValue(systemId, systemName);
  const input = el(stationId);
  if (!input) return;
  if (!stationName) {
    safeSetValue(stationId, "", true);
    clearSelectionData(input);
    return;
  }
  applySuggestionToInput(input, {
    kind: "station",
    entity_id: `${systemName || ""}::${stationName}`,
    label: stationName,
    secondary: systemName || "",
    meta: {
      system_name: systemName || "",
      station_name: stationName,
    },
  });
}

function commodityRefineParams() {
  return {
    origin_system: systemQueryFromInput("commodity-origin-system") || null,
    origin_station: stationQueryFromInput("commodity-origin-station") || null,
    target_system: systemQueryFromInput("commodity-target-system") || null,
    target_station: stationQueryFromInput("commodity-target-station") || null,
  };
}

function hasCommodityRefineFilters() {
  return Object.values(commodityRefineParams()).some(Boolean);
}

function commodityContextLabel(context, fallback = "partout") {
  if (!context) return fallback;
  const systemName = text(context.system_name, "").trim();
  const stationName = text(context.station_name, "").trim();
  if (systemName && stationName) return `${systemName} / ${stationName}`;
  if (stationName) return stationName;
  if (systemName) return systemName;
  return fallback;
}

function syncCommodityPresetChips() {
  const currentSystem = normalizeLookup(currentPlayerSystemName());
  const currentStation = normalizeLookup(currentPlayerStationName());
  const originSystem = normalizeLookup(systemQueryFromInput("commodity-origin-system"));
  const originStation = normalizeLookup(stationQueryFromInput("commodity-origin-station"));
  const targetSystem = normalizeLookup(systemQueryFromInput("commodity-target-system"));
  const targetStation = normalizeLookup(stationQueryFromInput("commodity-target-station"));

  let originPreset = "anywhere";
  if (originStation && originStation === currentStation && originSystem === currentSystem) {
    originPreset = "current_station";
  } else if (!originStation && originSystem && originSystem === currentSystem) {
    originPreset = "current_system";
  }

  let targetPreset = "anywhere";
  if (targetStation && targetStation === currentStation && targetSystem === currentSystem) {
    targetPreset = "current_station";
  } else if (!targetStation && targetSystem && targetSystem === currentSystem) {
    targetPreset = "current_system";
  }

  setChipActive("data-commodity-origin-preset", originPreset);
  setChipActive("data-commodity-target-preset", targetPreset);
}

function renderCommodityRefineStatus(selectionContext = null) {
  const node = el("commodity-refine-status");
  if (!node) return;
  const origin = selectionContext?.origin || {
    system_name: systemQueryFromInput("commodity-origin-system"),
    station_name: stationQueryFromInput("commodity-origin-station"),
  };
  const target = selectionContext?.target || {
    system_name: systemQueryFromInput("commodity-target-system"),
    station_name: stationQueryFromInput("commodity-target-station"),
  };
  node.textContent = `Origine: ${commodityContextLabel(origin)} • Cible: ${commodityContextLabel(target)}`;
  syncCommodityPresetChips();
}

function applyCommodityRefineContext(selectionContext) {
  if (!selectionContext) {
    renderCommodityRefineStatus();
    return;
  }
  const origin = selectionContext.origin || {};
  const target = selectionContext.target || {};
  setStationInputValue("commodity-origin-system", "commodity-origin-station", origin.system_name || "", origin.station_name || "");
  setStationInputValue("commodity-target-system", "commodity-target-station", target.system_name || "", target.station_name || "");
  renderCommodityRefineStatus(selectionContext);
}

function applyCommodityRefinePreset(kind, presetName) {
  const currentSystem = currentPlayerSystemName();
  const currentStation = currentPlayerStationName();
  const systemId = kind === "origin" ? "commodity-origin-system" : "commodity-target-system";
  const stationId = kind === "origin" ? "commodity-origin-station" : "commodity-target-station";

  if (presetName === "current_station" && currentSystem && currentStation) {
    setStationInputValue(systemId, stationId, currentSystem, currentStation);
  } else if ((presetName === "current_system" || presetName === "current_station") && currentSystem) {
    setSystemInputValue(systemId, currentSystem);
    setStationInputValue(systemId, stationId, currentSystem, "");
  } else {
    setStationInputValue(systemId, stationId, "", "");
  }

  renderCommodityRefineStatus();
}

function resetCommodityRefine() {
  setStationInputValue("commodity-origin-system", "commodity-origin-station", "", "");
  setStationInputValue("commodity-target-system", "commodity-target-station", "", "");
  renderCommodityRefineStatus();
}

function activeCargoCapacity() {
  const routeCargo = Number(el("route-cargo-capacity")?.value);
  if (Number.isFinite(routeCargo) && routeCargo > 0) return routeCargo;
  const overrideCargo = Number(el("cargo-capacity-override")?.value);
  if (Number.isFinite(overrideCargo) && overrideCargo > 0) return overrideCargo;
  const playerCargo = Number(state.dashboard?.player?.cargo_capacity_override ?? state.dashboard?.player?.cargo_capacity ?? 0);
  if (Number.isFinite(playerCargo) && playerCargo > 0) return playerCargo;
  return 100;
}

function summarizeCommodityTrend(history) {
  const points = (history || [])
    .map(point => Number(point.max_sell || point.min_buy || 0))
    .filter(value => Number.isFinite(value) && value > 0);
  if (points.length < 2) {
    return { label: "Stable", detail: "Historique insuffisant" };
  }
  const first = points[0];
  const last = points[points.length - 1];
  const delta = last - first;
  const pct = first > 0 ? (delta / first) * 100 : 0;
  if (Math.abs(pct) < 1.5) {
    return { label: "Stable", detail: `${pct.toFixed(1).replace(".", ",")} %` };
  }
  if (delta > 0) {
    return { label: "Hausse", detail: `+${pct.toFixed(1).replace(".", ",")} %` };
  }
  return { label: "Baisse", detail: `${pct.toFixed(1).replace(".", ",")} %` };
}

function commoditySpreadUnits(bestBuy, bestSell, bestRoute) {
  if (bestRoute?.units) return Number(bestRoute.units);
  const cargo = activeCargoCapacity();
  const stock = Number(bestBuy?.stock || cargo);
  const demand = Number(bestSell?.demand || cargo);
  return Math.max(0, Math.min(cargo, stock || cargo, demand || cargo));
}

function commodityRouteRows(routes = []) {
  const rows = [...routes];
  if (state.tradeLens === "assisted") {
    rows.sort((a, b) => (b.route_score || 0) - (a.route_score || 0) || (b.profit_per_hour || 0) - (a.profit_per_hour || 0));
    return rows;
  }
  rows.sort((a, b) => (b.unit_profit || 0) - (a.unit_profit || 0) || (b.trip_profit || 0) - (a.trip_profit || 0));
  return rows;
}

async function applyCommodityOfferSelection(kind, offer) {
  if (!offer) return;
  setNavigationSelection({
    type: "station",
    role: kind === "origin" ? "buy" : "sell",
    role_label: kind === "origin" ? "Achat choisi" : "Vente choisie",
    system_name: offer.system_name || "",
    station_name: offer.station_name || "",
    distance_ly: offer.distance_from_player_ly ?? null,
    distance_ls: offer.distance_ls ?? null,
    price: offer.price ?? null,
    price_label: kind === "origin" ? "Achat" : "Vente",
    detail: state.commodityIntel?.commodity_name || "",
  });
  if (kind === "origin") {
    setStationInputValue("commodity-origin-system", "commodity-origin-station", offer.system_name || "", offer.station_name || "");
    setTradeMode("buy", { scroll: false });
  } else {
    setStationInputValue("commodity-target-system", "commodity-target-station", offer.system_name || "", offer.station_name || "");
    setTradeMode("sell", { scroll: false });
    const copied = await copyText(offer.system_name || "");
    if (copied && offer.system_name) {
      status(`${offer.system_name} copié pour collage direct dans la carte galactique d'Elite.`);
    }
  }
  renderCommodityRefineStatus();
  await rememberSelection("station", `${offer.system_name || ""}::${offer.station_name || ""}`, offer.station_name || "", offer.system_name || "", {
    system_name: offer.system_name || "",
    station_name: offer.station_name || "",
  });
  await loadCommodityIntel(false);
}

async function applyCommodityRouteSelection(route) {
  if (!route) return;
  setNavigationSelection({
    type: "route",
    role_label: "Trajet choisi",
    commodity_name: route.commodity_name || state.commodityIntel?.commodity_name || "",
    trip_profit: route.trip_profit ?? null,
    unit_profit: route.unit_profit ?? null,
    route_score: route.route_score ?? null,
    estimated_minutes: route.estimated_minutes ?? null,
    source_system: route.source_system || "",
    source_station: route.source_station || "",
    source_distance_ly: route.distance_from_player_ly ?? null,
    source_distance_ls: route.source_distance_ls ?? null,
    target_system: route.target_system || "",
    target_station: route.target_station || "",
    target_distance_ly: route.target_distance_ly ?? null,
    target_distance_ls: route.target_distance_ls ?? null,
  });
  setStationInputValue("commodity-origin-system", "commodity-origin-station", route.source_system || "", route.source_station || "");
  setStationInputValue("commodity-target-system", "commodity-target-station", route.target_system || "", route.target_station || "");
  setTradeMode("sell", { scroll: false });
  const copied = await copyText(route.target_system || "");
  if (copied && route.target_system) {
    status(`${route.target_system} copié pour collage direct dans la carte galactique d'Elite.`);
  }
  renderCommodityRefineStatus();
  await loadCommodityIntel(false);
}

function flattenMemory(groups, limit = 12) {
  const items = [];
  for (const [kind, values] of Object.entries(groups || {})) {
    for (const item of values || []) {
      items.push({ kind, ...item });
    }
  }
  items.sort((a, b) => new Date(b.updated_at || 0).getTime() - new Date(a.updated_at || 0).getTime());
  return items.slice(0, limit);
}

function renderMemory(snapshot) {
  state.memory = snapshot || state.memory;
  const memory = snapshot || state.memory || {};
  const favorites = flattenMemory(memory.favorites, 14);
  const recents = flattenMemory(memory.recents, 14);
  const missions = memory.last_missions || [];
  const profiles = memory.ship_profiles || [];

  el("memory-favorites").innerHTML = favorites.length
    ? favorites.map(item => `<button class="memory-chip favorite" type="button" data-memory-kind="${escapeHtml(item.kind)}" data-memory-id="${escapeHtml(item.id)}" data-memory-label="${escapeHtml(item.label)}" data-memory-secondary="${escapeHtml(item.secondary || "")}">${escapeHtml(item.label)}</button>`).join("")
    : `<div class="mini-note">Aucun favori trader.</div>`;

  el("memory-recents").innerHTML = recents.length
    ? recents.map(item => `<button class="memory-chip" type="button" data-memory-kind="${escapeHtml(item.kind)}" data-memory-id="${escapeHtml(item.id)}" data-memory-label="${escapeHtml(item.label)}" data-memory-secondary="${escapeHtml(item.secondary || "")}">${escapeHtml(item.label)}</button>`).join("")
    : `<div class="mini-note">Aucun recent trader.</div>`;

  el("memory-missions").innerHTML = missions.length
    ? missions.map(item => {
        const extra = item.extra || {};
        return `<button class="stack-card" type="button" data-mission-commodity="${escapeHtml(extra.commodity_query || item.label || "")}" data-mission-quantity="${escapeHtml(String(extra.quantity || 1))}" data-mission-system="${escapeHtml(extra.target_system || "")}" data-mission-station="${escapeHtml(extra.target_station || "")}"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.secondary || "Sans destination fixe")}</span><small>${escapeHtml(number(extra.quantity || 1))} unites</small></button>`;
      }).join("")
    : `<div class="mini-note">Aucune mission memorisee.</div>`;

  if (!profiles.length) {
    el("ship-profile-summary").textContent = "Profil en attente.";
  } else {
    const profile = profiles[0];
    const extra = profile.extra || {};
    el("ship-profile-summary").innerHTML = `<strong>${escapeHtml(profile.label)}</strong><br /><small>${escapeHtml(number(extra.cargo_capacity || 0))} t • ${escapeHtml(text(extra.jump_range, "0"))} Ly • pad ${escapeHtml(extra.preferred_pad_size || "M")}</small>`;
  }

  renderFavoriteCommodityButton();
  setTradeMode(state.tradeMode, { scroll: false });
}

function renderPlayer(player, dashboard) {
  const playerSummary = document.getElementById("player-summary");
  if (!playerSummary) return;
  const permitLabels = dashboard.owned_permit_labels || dashboard.owned_permits || [];
  const permits = permitLabels.join(", ") || "Aucun permis confirmé";
  if (state.appMode === "combat") {
    playerSummary.innerHTML = [
      statCard("Système", text(player.current_system, "Inconnu")),
      statCard("Situation", text(player.local_mode, "Inconnu")),
      statCard("Station / cible", text(player.station_display, "En vol")),
      statCard("Vaisseau", text(player.current_ship_name || player.current_ship_code, "Inconnu")),
      statCard("Crédits", credits(player.balance ?? player.credits)),
      statCard("Cargo", `${number(player.cargo_count ?? 0)} / ${number(player.cargo_capacity ?? 0)}`),
      statCard("Portée", `${text(player.jump_range, "0")} Ly`),
      statCard("Permis", permits),
    ].join("");
    document.getElementById("player-system-badge").textContent = player.location_line || player.current_system || "Aucune position";
    document.getElementById("local-mode-badge").textContent = player.local_mode || "État local inconnu";
    safeSetValue("cargo-capacity-override", player.cargo_capacity_override ?? player.cargo_capacity ?? 0);
    safeSetValue("jump-range-override", player.jump_range_override ?? player.jump_range ?? 0);
    safeSetValue("preferred-pad-size", player.preferred_pad_size || "M");
    return;
  }
  playerSummary.innerHTML = [
    statCard("Commandant", text(player.commander_name, "Inconnu")),
    statCard("Système", text(player.current_system, "Inconnu")),
    statCard("Situation", text(player.local_mode, "Inconnu")),
    statCard("Station / cible", text(player.station_display, "En vol")),
    statCard("Destination", text(player.destination_name, "Aucune")),
    statCard("Vaisseau", text(player.current_ship_name || player.current_ship_code, "Inconnu")),
    statCard("Cargo réel", number(player.cargo_capacity ?? 0)),
    statCard("Cargo chargé", number(player.cargo_count ?? 0)),
    statCard("Portée réelle", `${text(player.jump_range, "0")} Ly`),
    statCard("Crédits", credits(player.balance ?? player.credits)),
    statCard("Permis connus", permits),
    statCard("Dernier état", formatTimestamp(player.status_timestamp || player.current_location_at)),
  ].join("");

  document.getElementById("player-system-badge").textContent = player.location_line || player.current_system || "Aucune position";
  document.getElementById("local-mode-badge").textContent = player.local_mode || "État local inconnu";
  safeSetValue("cargo-capacity-override", player.cargo_capacity_override ?? player.cargo_capacity ?? 0);
  safeSetValue("jump-range-override", player.jump_range_override ?? player.jump_range ?? 0);
  safeSetValue("preferred-pad-size", player.preferred_pad_size || "M");
}

function renderSources(dashboard) {
  const eddn = dashboard.eddn || {};
  const sources = dashboard.sources || {};

  document.getElementById("source-status").innerHTML = [
    statCard("Poll local", formatTimestamp(sources.local_last_poll)),
    statCard("Dernier événement", formatTimestamp(sources.local_last_event)),
    statCard("Import local", formatTimestamp(sources.journal_last_import)),
    statCard("Synchro Ardent", formatTimestamp(sources.ardent_last_sync)),
    statCard("Accès / permis", formatTimestamp(sources.edsm_access_last_refresh)),
    statCard("Refresh Spansh", formatTimestamp(sources.spansh_last_refresh)),
    statCard("Refresh EDSM", formatTimestamp(sources.edsm_last_refresh)),
    statCard("EDDN", `${number(eddn.messages_seen || 0)} msg • ${number(eddn.commodity_snapshots || 0)} snaps`),
  ].join("");

  const badge = document.getElementById("eddn-badge");
  if (eddn.running && eddn.last_commodity_age_min !== null && eddn.last_commodity_age_min <= 15) {
    badge.className = "badge badge-good";
    badge.textContent = `EDDN actif • ${number(eddn.last_commodity_age_min)} min`;
  } else if (eddn.running) {
    badge.className = "badge badge-warn";
    badge.textContent = "EDDN actif";
  } else {
    badge.className = "badge badge-warn";
    badge.textContent = "EDDN inactif";
  }

  document.getElementById("data-paths").textContent = [
    `Journaux: ${dashboard.journal_dir || "n/d"}`,
    dashboard.game_dir ? `Jeu détecté: ${dashboard.game_dir}` : "Jeu détecté: non trouvé automatiquement",
  ].join(" • ");
}

function renderHeroMetrics(dashboard) {
  const commodityIntel = state.commodityIntel?.resolved ? state.commodityIntel : null;
  const decisions = commodityIntel?.decision_cards || dashboard.decision_cards || {};
  const bestRoute = commodityIntel?.best_routes?.[0] || dashboard.routes?.[0];
  const market = dashboard.current_market || {};
  const sync = dashboard.local_sync || {};
  const commodityLabel = commodityIntel?.commodity_name || null;

  document.getElementById("hero-metrics").innerHTML = [
    metricCard("Achat le moins cher", decisions.cheapest_buy ? credits(decisions.cheapest_buy.price) : "n/d", decisions.cheapest_buy ? `${decisions.cheapest_buy.system_name} / ${decisions.cheapest_buy.station_name}${commodityLabel ? ` • ${commodityLabel}` : ""}` : "Selectionne une marchandise"),
    metricCard("Vente la plus haute", decisions.highest_sell ? credits(decisions.highest_sell.price) : "n/d", decisions.highest_sell ? `${decisions.highest_sell.system_name} / ${decisions.highest_sell.station_name}${commodityLabel ? ` • ${commodityLabel}` : ""}` : "Selectionne une marchandise"),
    metricCard("Meilleure marge", bestRoute ? credits(bestRoute.trip_profit) : "n/d", bestRoute ? `${bestRoute.commodity_name} • achat ${credits(bestRoute.source_buy_price)} • vente ${credits(bestRoute.target_sell_price)}` : "Le moteur attend des routes utiles"),
    metricCard("Suivi local", sync.running ? "Actif" : "A relancer", `${AUTO_REFRESH_MS / 1000}s • dernier poll ${formatTimestamp(sync.last_poll_at)}`),
    metricCard("Marche courant", market.station_name || "Aucun", market.station_name ? `${market.system_name} • ${formatHours(market.freshness_hours)}` : "Ouvre un marche dans le jeu"),
    metricCard("Permis confirmes", number((dashboard.owned_permit_labels || dashboard.owned_permits || []).length), (dashboard.owned_permit_labels || dashboard.owned_permits || []).join(", ") || "Aucun"),
  ].join("");

  liveStatus(`Auto-rafraîchissement toutes les ${AUTO_REFRESH_MS / 1000}s • dernière mise à jour ${new Date().toLocaleTimeString("fr-FR")}`);
}

function renderHighlights(dashboard) {
  const commodityIntel = state.commodityIntel?.resolved ? state.commodityIntel : null;
  const route = commodityIntel?.best_routes?.[0] || dashboard.routes?.[0];
  const loop = dashboard.loops?.[0];
  const quick = commodityIntel?.quick_trade || {};
  const bestBuy = quick.best_buy;
  const bestSell = quick.best_sell;
  const bestLiveSell = quick.best_live_sell;
  const spread = quick.spread;

  document.getElementById("best-route-card").innerHTML = route
    ? `<div class="spotlight-card"><h3>Route directe</h3><span class="spotlight-main">${escapeHtml(route.commodity_name)}</span><span class="spotlight-sub">${escapeHtml(route.source_system)} / ${escapeHtml(route.source_station)} vers ${escapeHtml(route.target_system)} / ${escapeHtml(route.target_station)}</span><div class="spotlight-list"><div class="spotlight-line"><span>Profit trajet</span><strong>${escapeHtml(credits(route.trip_profit))}</strong></div><div class="spotlight-line"><span>Profit heure</span><strong>${escapeHtml(credits(route.profit_per_hour))}</strong></div><div class="spotlight-line"><span>Unites utiles</span><strong>${escapeHtml(number(route.units))}</strong></div><div class="spotlight-line"><span>Distance</span><strong>${escapeHtml(distanceLy(route.route_distance_ly))} • ${escapeHtml(minutesLabel(route.estimated_minutes))}</strong></div></div></div>`
    : spotlightEmpty("Route directe", "Scanne la region et laisse le moteur filtrer les routes accessibles et vraiment utiles.");

  document.getElementById("best-loop-card").innerHTML = commodityIntel
    ? `<div class="spotlight-card"><h3>Prix cibles</h3><span class="spotlight-main">${escapeHtml(commodityIntel.commodity_name || "Marchandise")}</span><span class="spotlight-sub">${bestBuy ? `${escapeHtml(bestBuy.station_name)} en achat` : "Pas d'achat visible"}${bestSell ? ` • ${escapeHtml(bestSell.station_name)} en revente` : ""}</span><div class="spotlight-list"><div class="spotlight-line"><span>Achat mini</span><strong>${bestBuy ? escapeHtml(credits(bestBuy.price)) : "n/d"}</strong></div><div class="spotlight-line"><span>Revente maxi</span><strong>${bestSell ? escapeHtml(credits(bestSell.price)) : "n/d"}</strong></div><div class="spotlight-line"><span>Ecart brut</span><strong>${spread !== null && spread !== undefined ? escapeHtml(credits(spread)) : "n/d"}</strong></div><div class="spotlight-line"><span>Revente rapide</span><strong>${bestLiveSell ? escapeHtml(bestLiveSell.station_name) : "n/d"}</strong></div></div></div>`
    : loop
      ? `<div class="spotlight-card"><h3>Boucle utile</h3><span class="spotlight-main">${escapeHtml(loop.from_station)} ↔ ${escapeHtml(loop.to_station)}</span><span class="spotlight-sub">${escapeHtml(loop.from_system)} ↔ ${escapeHtml(loop.to_system)}</span><div class="spotlight-list"><div class="spotlight-line"><span>Aller</span><strong>${escapeHtml(loop.go_commodity)} • ${escapeHtml(credits(loop.go_profit))}</strong></div><div class="spotlight-line"><span>Retour</span><strong>${escapeHtml(loop.return_commodity)} • ${escapeHtml(credits(loop.return_profit))}</strong></div><div class="spotlight-line"><span>Total</span><strong>${escapeHtml(credits(loop.total_profit))}</strong></div><div class="spotlight-line"><span>Profit heure</span><strong>${escapeHtml(credits(loop.profit_per_hour))}</strong></div></div></div>`
      : spotlightEmpty("Boucle utile", "Une boucle apparaitra des que deux marches complementaires, accessibles et frais, seront disponibles.");
}

function decisionOfferCard(title, offer, emptyMessage) {
  if (!offer) {
    return `<article class="decision-card"><span class="decision-eyebrow">${escapeHtml(title)}</span><span class="decision-main">Pas encore</span><span class="decision-sub">${escapeHtml(emptyMessage)}</span></article>`;
  }
  const volume = title.toLowerCase().includes("acheter")
    ? `${number(offer.stock || 0)} en stock`
    : `${number(offer.demand || 0)} de demande`;
  const distance = offer.distance_from_player_ly !== null && offer.distance_from_player_ly !== undefined
    ? `${distanceLy(offer.distance_from_player_ly)} depuis toi`
    : distanceLs(offer.distance_ls);
  return `<article class="decision-card"><span class="decision-eyebrow">${escapeHtml(title)}</span><span class="decision-main">${escapeHtml(offer.station_name)}</span><span class="decision-sub">${escapeHtml(offer.system_name)} • ${escapeHtml(credits(offer.price))}</span><div class="decision-kpis"><span class="badge">${escapeHtml(volume)}</span><span class="badge">${escapeHtml(formatHours(offer.freshness_hours))}</span><span class="badge">${escapeHtml(distance)}</span></div></article>`;
}

function decisionRouteCard(title, route, emptyMessage) {
  if (!route) {
    return `<article class="decision-card"><span class="decision-eyebrow">${escapeHtml(title)}</span><span class="decision-main">Pas encore</span><span class="decision-sub">${escapeHtml(emptyMessage)}</span></article>`;
  }
  return `<article class="decision-card"><span class="decision-eyebrow">${escapeHtml(title)}</span><span class="decision-main">${escapeHtml(route.commodity_name || "Route")}</span><span class="decision-sub">${escapeHtml(route.source_station)} → ${escapeHtml(route.target_station)}</span><div class="decision-kpis"><span class="badge">${escapeHtml(credits(route.trip_profit))}</span><span class="badge">${escapeHtml(credits(route.profit_per_hour))}/h</span><span class="badge">${escapeHtml(minutesLabel(route.estimated_minutes))}</span></div></article>`;
}

function renderDecisionCards(dashboard) {
  const commodityIntel = state.commodityIntel?.resolved ? state.commodityIntel : null;
  const decisions = commodityIntel?.decision_cards || dashboard.decision_cards || {};
  const routeViews = commodityIntel?.route_views || dashboard.route_views || {};
  const quick = commodityIntel?.quick_trade || {};
  const bestRoute = commodityIntel?.best_routes?.[0] || routeViews.best_margin || null;
  const spread = quick.spread;
  el("decision-grid").innerHTML = [
    decisionOfferCard("Acheter le moins cher", decisions.cheapest_buy, "Aucune offre d'achat exploitable."),
    decisionOfferCard("Revendre au plus haut", decisions.highest_sell, "Aucune bonne demande de vente pour le moment."),
    decisionOfferCard("Revente rapide", quick.best_live_sell || decisions.live_sell, "Aucune vente rapide et fiable."),
    spread !== null && spread !== undefined
      ? `<article class="decision-card"><span class="decision-eyebrow">Ecart brut</span><span class="decision-main">${escapeHtml(credits(spread))}</span><span class="decision-sub">${commodityIntel ? escapeHtml(commodityIntel.commodity_name) : "Marchandise active"}</span><div class="decision-kpis"><span class="badge">${decisions.cheapest_buy ? escapeHtml(credits(decisions.cheapest_buy.price)) : "n/d"} achat</span><span class="badge">${decisions.highest_sell ? escapeHtml(credits(decisions.highest_sell.price)) : "n/d"} vente</span></div></article>`
      : `<article class="decision-card"><span class="decision-eyebrow">Ecart brut</span><span class="decision-main">Pas encore</span><span class="decision-sub">Le moteur attend un achat et une revente coherents.</span></article>`,
  ].join("");
  el("route-view-grid").innerHTML = [
    decisionRouteCard("Meilleure marge", bestRoute || routeViews.best_margin, "Pas encore de route a forte marge."),
    decisionRouteCard("Profit par minute", commodityIntel?.best_routes?.[0] || routeViews.best_margin_per_minute, "Pas encore de route ultra rapide."),
    decisionRouteCard("Depuis mon systeme", routeViews.best_from_current_system, "Aucune route exploitable depuis ton systeme actuel."),
    decisionRouteCard("Depuis ma station", routeViews.best_from_current_station, "Aucune route exploitable depuis ta station actuelle."),
  ].join("");
}

function renderRoutes(routes, dataset) {
  document.getElementById("dataset-badge").textContent = `${number(dataset.rows)} lignes marché`;
  const tbody = document.querySelector("#routes-table tbody");
  tbody.innerHTML = "";

  if (!routes || routes.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9"><strong>Aucune route visible.</strong><br /><small>Élargis le scan, change de profil route ou attends davantage de données fraîches.</small></td></tr>`;
    return;
  }

  for (const route of routes) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(route.commodity_name)}</strong><br /><small>${escapeHtml(number(route.units))} unités utiles</small></td>
      <td><strong>${escapeHtml(route.source_station)}</strong><br /><small>${escapeHtml(route.source_system)} • ${escapeHtml(distanceLs(route.source_distance_ls))} • pad confirmé</small></td>
      <td><strong>${escapeHtml(route.target_station)}</strong><br /><small>${escapeHtml(route.target_system)} • ${escapeHtml(distanceLs(route.target_distance_ls))} • marché confirmé</small></td>
      <td><strong>Achat ${escapeHtml(credits(route.source_buy_price))}</strong><br /><small>Vente ${escapeHtml(credits(route.target_sell_price))}</small></td>
      <td><span class="profit">${escapeHtml(credits(route.trip_profit))}</span><br /><small>${escapeHtml(credits(route.unit_profit))}/u • ${escapeHtml(credits(route.profit_per_hour))}/h</small></td>
      <td><strong>${escapeHtml(distanceLy(route.route_distance_ly))}</strong><br /><small>${route.distance_from_player_ly !== null && route.distance_from_player_ly !== undefined ? `${escapeHtml(distanceLy(route.distance_from_player_ly))} depuis toi` : "Distance joueur n/d"}</small></td>
      <td><strong>${escapeHtml(minutesLabel(route.estimated_minutes))}</strong><br /><small>${escapeHtml(number(estimateJumps(route.route_distance_ly, activeJumpRange(), "balanced") || 0))} sauts estimés</small></td>
      <td><strong>${escapeHtml(formatHours(route.freshness_hours))}</strong><br /><small>${scoreBadge(route.route_score, route.confidence_label)}<br />Source ${escapeHtml(number(route.source_confidence_score))} • cible ${escapeHtml(number(route.target_confidence_score))}</small></td>
      <td><strong>${escapeHtml(route.accessibility || "Acces direct")}</strong><br />${actionButton("Utiliser trajet", { routeAction: "use-route", sourceSystem: route.source_system, sourceStation: route.source_station, targetSystem: route.target_system, targetStation: route.target_station }, "trade-card-action")}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderLoops(loops) {
  const tbody = document.querySelector("#loops-table tbody");
  tbody.innerHTML = "";

  if (!loops || loops.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7"><strong>Aucune boucle visible.</strong><br /><small>Il faut deux sens de commerce complémentaires dans la zone scannée.</small></td></tr>`;
    return;
  }

  for (const loop of loops) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(loop.from_station)}</strong><br /><small>${escapeHtml(loop.from_system)}</small></td>
      <td><strong>${escapeHtml(loop.to_station)}</strong><br /><small>${escapeHtml(loop.to_system)}</small></td>
      <td><strong>${escapeHtml(loop.go_commodity)}</strong><br /><small>${escapeHtml(credits(loop.go_profit))}</small></td>
      <td><strong>${escapeHtml(loop.return_commodity)}</strong><br /><small>${escapeHtml(credits(loop.return_profit))}</small></td>
      <td><span class="profit">${escapeHtml(credits(loop.total_profit))}</span></td>
      <td><span class="profit">${escapeHtml(credits(loop.profit_per_hour))}</span><br /><small>Par heure estimée</small></td>
      <td><strong>${escapeHtml(formatHours(loop.freshness_hours))}</strong><br /><small>${scoreBadge(loop.route_score, loop.confidence_label)}</small></td>
    `;
    tbody.appendChild(tr);
  }
}

function renderCurrentMarket(market) {
  const badge = document.getElementById("current-market-badge");
  const exportsNode = document.getElementById("current-exports");
  const importsNode = document.getElementById("current-imports");

  if (!market.station_name) {
    badge.textContent = "Aucun marché courant";
    exportsNode.innerHTML = "<li>Ouvre un marché dans le jeu ou attends la prochaine mise à jour locale.</li>";
    importsNode.innerHTML = "<li>Ouvre un marché dans le jeu ou attends la prochaine mise à jour locale.</li>";
    return;
  }

  badge.textContent = `${market.system_name} / ${market.station_name} • ${formatHours(market.freshness_hours)}`;
  exportsNode.innerHTML = (market.exports || []).map(item => `<li><strong>${escapeHtml(item.commodity_name)}</strong><br /><small>${escapeHtml(credits(item.buy_price))} • stock ${escapeHtml(number(item.stock))}</small></li>`).join("") || "<li>Aucun export détecté.</li>";
  importsNode.innerHTML = (market.imports || []).map(item => `<li><strong>${escapeHtml(item.commodity_name)}</strong><br /><small>${escapeHtml(credits(item.sell_price))} • demande ${escapeHtml(number(item.demand))}</small></li>`).join("") || "<li>Aucun import détecté.</li>";
}

function renderKnowledge(entries) {
  document.getElementById("knowledge-list").innerHTML = (entries || []).slice(0, 8).map(entry => `
    <div class="knowledge-item">
      <div class="source">${escapeHtml(entry.source_name)} • ${escapeHtml((entry.languages || []).join(", ") || "fr")}</div>
      <h3>${escapeHtml(entry.title)}</h3>
      <p>${escapeHtml(entry.summary)}</p>
      ${entry.url ? `<a href="${escapeHtml(entry.url)}" target="_blank" rel="noreferrer">Ouvrir la source</a>` : ""}
    </div>
  `).join("");
}

function renderNameLibrarySummary(summary) {
  if (!summary) return;
  document.getElementById("name-library-badge").textContent = `${number(summary.total)} noms`;
  document.getElementById("name-library-summary").innerHTML = [
    statCard("Total", number(summary.total)),
    statCard("Exacts Frontier", number(summary.exact_total)),
    statCard("Dérivés", number(summary.derived_total)),
    statCard("Dernière reconstruction", formatTimestamp(summary.updated_at)),
  ].join("");
  document.getElementById("name-library-types").innerHTML = (summary.types || []).slice(0, 12).map(item => `<span class="type-pill"><strong>${escapeHtml(NAME_TYPE_LABELS[item.entry_type] || item.entry_type)}</strong> ${escapeHtml(number(item.total))}</span>`).join("");
}

function renderNameLibraryResults(results) {
  const tbody = document.querySelector("#name-library-table tbody");
  tbody.innerHTML = "";

  if (!results || results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4"><strong>Aucun résultat.</strong><br /><small>Essaie un autre mot-clé ou change le type filtré.</small></td></tr>`;
    return;
  }

  for (const row of results) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(NAME_TYPE_LABELS[row.entry_type] || row.entry_type)}</td>
      <td>${escapeHtml(text(row.lookup_key))}</td>
      <td><strong>${escapeHtml(text(row.name_fr))}</strong><br /><small>${row.is_exact ? "Exact Frontier local" : `Dérivé • confiance ${escapeHtml(text(row.confidence, "n/d"))}`}</small></td>
      <td>${escapeHtml(text(row.source))}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderWatchlist(watchlist) {
  const node = document.getElementById("watchlist-grid");
  if (!watchlist || watchlist.length === 0) {
    node.innerHTML = `<div class="focus-summary">Aucune marchandise surveillée n'est visible dans les données actuelles.</div>`;
    return;
  }

  node.innerHTML = watchlist.map(item => {
    const bestBuy = item.best_buy;
    const bestSell = item.best_sell;
    const bestRoute = item.best_route;
    return `
      <article class="watch-card">
        <span class="watch-eyebrow">${escapeHtml(item.symbol.toUpperCase())}</span>
        <span class="watch-title">${escapeHtml(item.commodity_name)}</span>
        <span class="watch-detail">${bestRoute ? `${credits(bestRoute.trip_profit)} le trajet` : "Pas de route complète visible"}</span>
        <div class="watch-lines">
          <div class="watch-line"><span>Achat</span><strong>${bestBuy ? credits(bestBuy.price) : "n/d"}</strong></div>
          <div class="watch-line"><span>Vente</span><strong>${bestSell ? credits(bestSell.price) : "n/d"}</strong></div>
          <div class="watch-line"><span>Meilleure route</span><strong>${bestRoute ? `${credits(bestRoute.profit_per_hour)}/h` : "n/d"}</strong></div>
        </div>
        <button class="preset-chip watch-action" type="button" data-commodity="${escapeHtml(item.symbol)}">Ouvrir ${escapeHtml(item.commodity_name)}</button>
      </article>
    `;
  }).join("");
}

function renderCommodityRouteTable(routes) {
  const tbody = document.querySelector("#commodity-route-table tbody");
  tbody.innerHTML = "";
  const visibleRoutes = commodityRouteRows(routes || []);
  if (!visibleRoutes.length) {
    tbody.innerHTML = `<tr><td colspan="5"><strong>Aucune route directe visible.</strong></td></tr>`;
    return;
  }
  for (const route of visibleRoutes) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(route.source_station)}</strong><br /><small>${escapeHtml(route.source_system)} → ${escapeHtml(route.target_station)}</small><br />${actionButton("Choisir trajet", { routeAction: "use-route", sourceSystem: route.source_system, sourceStation: route.source_station, targetSystem: route.target_system, targetStation: route.target_station })}</td><td><strong>${escapeHtml(credits(route.source_buy_price))}</strong><br /><small>vente ${escapeHtml(credits(route.target_sell_price))}</small></td><td><strong>${escapeHtml(credits(route.trip_profit))}</strong><br /><small>${escapeHtml(credits(route.unit_profit))}/u • ${escapeHtml(credits(route.profit_per_hour))}/h</small></td><td>${escapeHtml(minutesLabel(route.estimated_minutes))}<br /><small>${escapeHtml(distanceLy(route.route_distance_ly))}</small></td><td>${scoreBadge(route.route_score, route.confidence_label)}</td>`;
    tbody.appendChild(tr);
  }
}

function upsertNavigationCandidate(map, candidate) {
  if (!candidate?.system_name) return;
  const key = `${normalizeLookup(candidate.system_name)}::${normalizeLookup(candidate.station_name || "")}`;
  const current = map.get(key);
  if (!current) {
    map.set(key, { ...candidate, role_labels: [candidate.role_label].filter(Boolean) });
    return;
  }
  const roleLabels = new Set([...(current.role_labels || []), candidate.role_label].filter(Boolean));
  const currentDistance = Number(current.distance_ly);
  const nextDistance = Number(candidate.distance_ly);
  const preferCandidate =
    (!Number.isFinite(currentDistance) && Number.isFinite(nextDistance))
    || (Number.isFinite(currentDistance) && Number.isFinite(nextDistance) && nextDistance < currentDistance)
    || (!current.price && candidate.price)
    || ((candidate.sort_score || 0) > (current.sort_score || 0));
  map.set(key, {
    ...(preferCandidate ? current : candidate),
    ...(preferCandidate ? candidate : current),
    role_labels: [...roleLabels],
    role_label: [...roleLabels].join(" / "),
  });
}

function buildNavigationCandidates() {
  const candidates = new Map();
  const intel = state.commodityIntel;
  const quick = intel?.quick_trade || {};
  const addOffer = (roleLabel, offer, sortScore = 0) => {
    if (!offer?.system_name) return;
    upsertNavigationCandidate(candidates, {
      type: "station",
      role: roleLabel,
      role_label: roleLabel,
      system_name: offer.system_name,
      station_name: offer.station_name,
      distance_ly: offer.distance_from_player_ly,
      distance_ls: offer.distance_ls,
      price: offer.price,
      price_label: roleLabel.toLowerCase().includes("vente") ? "Vente" : "Achat",
      detail: intel?.commodity_name || "",
      sort_score: sortScore,
    });
  };
  const addRouteLeg = (roleLabel, route, leg, sortScore = 0) => {
    if (!route) return;
    const isSource = leg === "source";
    upsertNavigationCandidate(candidates, {
      type: "station",
      role: isSource ? "buy" : "sell",
      role_label: roleLabel,
      system_name: isSource ? route.source_system : route.target_system,
      station_name: isSource ? route.source_station : route.target_station,
      distance_ly: isSource ? route.distance_from_player_ly : null,
      distance_ls: isSource ? route.source_distance_ls : route.target_distance_ls,
      price: isSource ? route.source_buy_price : route.target_sell_price,
      price_label: isSource ? "Achat" : "Vente",
      detail: route.commodity_name || "",
      sort_score: sortScore,
    });
  };

  addOffer("Achat mini", quick.best_buy, 96);
  addOffer("Achat pratique", quick.best_near_buy, 90);
  addOffer("Revente maxi", quick.best_sell, 95);
  addOffer("Vente pratique", quick.best_live_sell, 89);

  (commodityRouteRows(intel?.best_routes || []).slice(0, 8)).forEach((route, index) => {
    addRouteLeg(`Route ${index + 1} achat`, route, "source", 88 - index);
    addRouteLeg(`Route ${index + 1} vente`, route, "target", 84 - index);
  });

  const mission = state.missionIntel;
  (mission?.best_sources || []).slice(0, 4).forEach((item, index) => {
    addOffer(`Mission achat ${index + 1}`, item, 76 - index);
  });
  (mission?.best_routes || []).slice(0, 4).forEach((route, index) => {
    addRouteLeg(`Mission route ${index + 1}`, route, "source", 72 - index);
    addRouteLeg(`Mission cible ${index + 1}`, route, "target", 70 - index);
  });

  const jumpRange = activeJumpRange();
  return [...candidates.values()]
    .map(item => {
      const jumps = estimateJumps(item.distance_ly, jumpRange, "balanced");
      const minutes = estimateTravelMinutes(item.distance_ly, item.distance_ls, jumpRange, "balanced");
      return {
        ...item,
        jumps,
        minutes,
      };
    })
    .sort((a, b) => {
      const jumpsA = Number.isFinite(a.jumps) ? a.jumps : 999999;
      const jumpsB = Number.isFinite(b.jumps) ? b.jumps : 999999;
      const minutesA = Number.isFinite(a.minutes) ? a.minutes : 999999;
      const minutesB = Number.isFinite(b.minutes) ? b.minutes : 999999;
      return jumpsA - jumpsB || minutesA - minutesB || (b.sort_score || 0) - (a.sort_score || 0) || (b.price || 0) - (a.price || 0);
    });
}

function navigationProfileCard(label, distanceLyValue, distanceLs, jumpRange, mode, detail = "") {
  const jumps = estimateJumps(distanceLyValue, jumpRange, mode);
  const minutes = estimateTravelMinutes(distanceLyValue, distanceLs, jumpRange, mode);
  const detailLine = detail || (distanceLyValue !== null && distanceLyValue !== undefined ? distanceLy(distanceLyValue) : "Estimation en attente");
  return `<article class="trade-card"><span class="metric-label">${escapeHtml(label)}</span><strong>${jumps !== null ? `${escapeHtml(number(jumps))} sauts` : "n/d"}</strong><span>${minutes !== null ? escapeHtml(minutesLabel(minutes)) : "Distance inconnue"}</span><span>${escapeHtml(detailLine)}</span></article>`;
}

function renderNavigationPanel() {
  const summaryNode = el("navigation-summary");
  const gridNode = el("navigation-profile-grid");
  const badgeNode = el("navigation-route-badge");
  const tbody = document.querySelector("#navigation-table tbody");
  if (!summaryNode || !gridNode || !badgeNode || !tbody) return;

  const selected = activeNavigationTarget() || defaultNavigationSelection();
  const navRoute = state.dashboard?.nav_route || {};
  const currentSystem = currentPlayerSystemName();
  const jumpRange = activeJumpRange();
  const distanceLyValue = selected?.distance_ly;
  const distanceLsValue = selected?.distance_ls;
  const routeMatches = Boolean(navRoute.available && selected?.system_name && normalizeLookup(navRoute.destination_system) === normalizeLookup(selected.system_name));

  if (!selected) {
    badgeNode.textContent = navRoute.available ? `Route Elite active: ${navRoute.destination_system || "n/d"}` : "Aucune destination active";
    summaryNode.innerHTML = "<strong>Bibliotheque de trajets</strong><br />Choisis un achat, une vente ou un trajet. Le logiciel prepare ensuite le systeme a coller dans la carte galactique d'Elite.";
    gridNode.innerHTML = "";
    tbody.innerHTML = `<tr><td colspan="6"><strong>Aucun trajet actif.</strong><br /><small>Selectionne une station d'achat, une station de vente ou une route complete.</small></td></tr>`;
    return;
  }

  badgeNode.textContent = routeMatches
    ? `Route Elite detectee vers ${selected.system_name}`
    : navRoute.available
      ? `Route Elite: ${navRoute.destination_system || "n/d"}`
      : "Route Elite non tracee";

  const chips = [
    selected.role_label || "Destination",
    selected.commodity_name || selected.detail || null,
    selected.price_label && selected.price ? `${selected.price_label} ${credits(selected.price)}` : null,
    selected.trip_profit ? `Trajet ${credits(selected.trip_profit)}` : null,
  ].filter(Boolean);
  summaryNode.innerHTML = `<strong>${escapeHtml(selected.station_name || selected.system_name)}</strong><br />${escapeHtml(selected.system_name)}${currentSystem ? ` depuis ${escapeHtml(currentSystem)}` : ""}<br /><small>${chips.map(item => escapeHtml(item)).join(" • ") || "Destination active"}</small>${routeMatches ? `<br /><small>La route actuelle du jeu pointe deja vers ce systeme.</small>` : ""}`;

  const profileCards = [
    navigationProfileCard("Express", distanceLyValue, distanceLsValue, jumpRange, "express", "Moins de sauts, trajet direct"),
    navigationProfileCard("Equilibre", distanceLyValue, distanceLsValue, jumpRange, "balanced", "Lecture pratique pour le vaisseau actif"),
  ];
  if (Number(distanceLyValue || 0) >= 500) {
    profileCards.push(navigationProfileCard("Long trajet", distanceLyValue, distanceLsValue, jumpRange, "neutron", "Estimation pour route longue type neutron"));
  }
  if (navRoute.available) {
    profileCards.push(`<article class="trade-card trade-card-accent"><span class="metric-label">Route Elite actuelle</span><strong>${escapeHtml(navRoute.destination_system || "n/d")}</strong><span>${escapeHtml(number(navRoute.hops || 0))} sauts • ${escapeHtml(distanceLy(navRoute.direct_distance_ly))}</span><span>${escapeHtml(formatTimestamp(navRoute.updated_at))}</span></article>`);
  }
  gridNode.innerHTML = profileCards.join("");

  const candidates = buildNavigationCandidates();
  if (!candidates.length) {
    tbody.innerHTML = `<tr><td colspan="6"><strong>Aucune destination trader visible.</strong><br /><small>Attends plus de donnees ou analyse une marchandise.</small></td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  for (const item of candidates.slice(0, 14)) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(item.role_label || "Destination")}</strong><br /><small>${escapeHtml((item.role_labels || []).join(" • ") || item.detail || "")}</small></td><td><strong>${escapeHtml(item.station_name || item.system_name)}</strong><br /><small>${escapeHtml(item.system_name)}</small></td><td>${escapeHtml(distanceLy(item.distance_ly))}<br /><small>${escapeHtml(distanceLs(item.distance_ls))}</small></td><td><strong>${item.jumps !== null ? escapeHtml(number(item.jumps)) : "n/d"}</strong><br /><small>${escapeHtml(minutesLabel(item.minutes))}</small></td><td>${item.price ? `<strong>${escapeHtml(credits(item.price))}</strong><br /><small>${escapeHtml(item.price_label || "")}</small>` : "<strong>n/d</strong>"}</td><td>${actionButton("Activer", { navigationAction: "activate", systemName: item.system_name, stationName: item.station_name, role: item.role, roleLabel: item.role_label, distanceLy: item.distance_ly, distanceLs: item.distance_ls, price: item.price, priceLabel: item.price_label, detail: item.detail }, "trade-card-action")}${actionButton("Copier", { navigationAction: "copy", systemName: item.system_name }, "trade-card-action")}</td>`;
    tbody.appendChild(tr);
  }
}

function combatServiceSummary(item) {
  if (!item) return "n/d";
  return [
    item.has_restock ? "Munitions" : null,
    item.has_repair ? "Reparation" : null,
    item.has_refuel ? "Refuel" : null,
  ].filter(Boolean).join(" • ");
}

function renderCombatPanel(dashboard) {
  const panel = dashboard?.combat_support || {};
  const summary = el("combat-summary");
  const cards = el("combat-cards");
  const badge = el("combat-badge");
  const tbody = document.querySelector("#combat-table tbody");
  if (!summary || !cards || !badge || !tbody) return;

  const bestRestock = panel.best_restock;
  const bestRepair = panel.best_repair;
  const bestRefuel = panel.best_refuel;
  const currentSystem = panel.current_system || currentPlayerSystemName() || "Position inconnue";
  badge.textContent = `${currentSystem} • pad ${panel.preferred_pad_size || "M"}`;

  if (!panel.stations?.length) {
    summary.innerHTML = `<strong>Support combat indisponible.</strong><br />Le logiciel n'a pas encore assez de stations avec services de combat autour de ta position.`;
    cards.innerHTML = `<div class="focus-summary">Importe tes journaux ou scanne la region pour trouver des stations avec restock, repair et refuel.</div>`;
    tbody.innerHTML = `<tr><td colspan="4"><strong>Aucune station combat visible.</strong></td></tr>`;
    return;
  }

  summary.innerHTML = `<strong>Recharge combat autour de toi</strong><br />Priorité aux stations avec <strong>munitions</strong>, puis <strong>réparation</strong> et <strong>carburant</strong>, en gardant le pad compatible et la station la plus simple à atteindre.`;
  cards.innerHTML = [
    bestRestock
      ? `<article class="trade-card trade-card-accent"><span class="metric-label">Munitions</span><strong>${escapeHtml(bestRestock.station_name)}</strong><span>${escapeHtml(bestRestock.system_name)} • ${escapeHtml(distanceLy(bestRestock.distance_ly))}</span><span>${escapeHtml(combatServiceSummary(bestRestock))}</span>${actionButton("Tracer", { navigationAction: "activate", systemName: bestRestock.system_name, stationName: bestRestock.station_name, role: "combat", roleLabel: "Munitions", distanceLy: bestRestock.distance_ly, distanceLs: bestRestock.distance_ls, detail: combatServiceSummary(bestRestock) }, "trade-card-action")}</article>`
      : `<article class="trade-card trade-card-accent"><span class="metric-label">Munitions</span><strong>Aucune station claire</strong><span>Pas de restock exploitable pour le moment.</span></article>`,
    bestRepair
      ? `<article class="trade-card"><span class="metric-label">Réparation</span><strong>${escapeHtml(bestRepair.station_name)}</strong><span>${escapeHtml(bestRepair.system_name)} • ${escapeHtml(distanceLy(bestRepair.distance_ly))}</span><span>${escapeHtml(combatServiceSummary(bestRepair))}</span>${actionButton("Tracer", { navigationAction: "activate", systemName: bestRepair.system_name, stationName: bestRepair.station_name, role: "combat", roleLabel: "Réparation", distanceLy: bestRepair.distance_ly, distanceLs: bestRepair.distance_ls, detail: combatServiceSummary(bestRepair) }, "trade-card-action")}</article>`
      : `<article class="trade-card"><span class="metric-label">Reparation</span><strong>n/d</strong><span>Pas de repair visible.</span></article>`,
    bestRefuel
      ? `<article class="trade-card"><span class="metric-label">Carburant</span><strong>${escapeHtml(bestRefuel.station_name)}</strong><span>${escapeHtml(bestRefuel.system_name)} • ${escapeHtml(distanceLy(bestRefuel.distance_ly))}</span><span>${escapeHtml(combatServiceSummary(bestRefuel))}</span>${actionButton("Tracer", { navigationAction: "activate", systemName: bestRefuel.system_name, stationName: bestRefuel.station_name, role: "combat", roleLabel: "Carburant", distanceLy: bestRefuel.distance_ly, distanceLs: bestRefuel.distance_ls, detail: combatServiceSummary(bestRefuel) }, "trade-card-action")}</article>`
      : `<article class="trade-card"><span class="metric-label">Refuel</span><strong>n/d</strong><span>Pas de refuel visible.</span></article>`,
  ].join("");

  tbody.innerHTML = "";
  for (const item of panel.stations || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(item.station_name)}</strong><br /><small>${escapeHtml(item.system_name)} • ${escapeHtml(item.accessibility || "Acces direct")}</small><br /><small>${escapeHtml(formatHours(item.freshness_hours))} • ${escapeHtml(formatTimestamp(item.updated_at))}</small></td><td><strong>${escapeHtml(combatServiceSummary(item))}</strong><br /><small>${escapeHtml((item.badges || []).join(" • "))}</small></td><td>${escapeHtml(distanceLy(item.distance_ly))}<br /><small>${escapeHtml(distanceLs(item.distance_ls))}</small></td><td>${actionButton("Tracer", { navigationAction: "activate", systemName: item.system_name, stationName: item.station_name, role: "combat", roleLabel: "Support combat", distanceLy: item.distance_ly, distanceLs: item.distance_ls, detail: combatServiceSummary(item) }, "trade-card-action")}${actionButton("Copier", { navigationAction: "copy", systemName: item.system_name }, "trade-card-action")}</td>`;
    tbody.appendChild(tr);
  }
}

function setTradeMode(mode, { scroll = false } = {}) {
  state.tradeMode = mode === "sell" ? "sell" : "buy";
  localStorage.setItem("elite_plug_trade_mode", state.tradeMode);
  const buyButton = document.getElementById("btn-mode-buy");
  const sellButton = document.getElementById("btn-mode-sell");
  const buyWrap = document.getElementById("focus-buy-wrap");
  const sellWrap = document.getElementById("focus-sell-wrap");
  if (buyButton) buyButton.classList.toggle("active", state.tradeMode === "buy");
  if (sellButton) sellButton.classList.toggle("active", state.tradeMode === "sell");
  if (buyWrap) buyWrap.hidden = state.tradeMode !== "buy";
  if (sellWrap) sellWrap.hidden = state.tradeMode !== "sell";
  if (scroll) {
    const target = state.tradeMode === "buy" ? buyWrap : sellWrap;
    target?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  renderNavigationPanel();
}

function setTradeLens(mode) {
  state.tradeLens = mode === "assisted" ? "assisted" : "absolute";
  localStorage.setItem("elite_plug_trade_lens", state.tradeLens);
  el("btn-lens-absolute")?.classList.toggle("active", state.tradeLens === "absolute");
  el("btn-lens-assisted")?.classList.toggle("active", state.tradeLens === "assisted");
  if (state.commodityIntel) {
    renderCommodityIntel(state.commodityIntel);
  }
}

function renderCommodityIntel(intel) {
  state.commodityIntel = intel;
  const summary = document.getElementById("commodity-focus-summary");
  const quickCards = document.getElementById("commodity-quick-cards");
  const marketStrip = document.getElementById("commodity-market-strip");
  const historyNode = document.getElementById("commodity-history");
  const historyBadge = document.getElementById("commodity-history-badge");
  const buyTbody = document.querySelector("#focus-buy-table tbody");
  const sellTbody = document.querySelector("#focus-sell-table tbody");
  const sellOffers = document.getElementById("commodity-sell-offers");
  quickCards.innerHTML = "";
  if (marketStrip) marketStrip.innerHTML = "";
  historyNode.innerHTML = "";
  historyBadge.textContent = "Pas encore d'historique";
  buyTbody.innerHTML = "";
  sellTbody.innerHTML = "";
  if (sellOffers) sellOffers.innerHTML = "";
  applyCommodityRefineContext(intel?.selection_context || null);

  if (!intel || !intel.resolved) {
    summary.textContent = "Marchandise inconnue pour le moment. Essaie avec le nom FR ou la clé anglaise du jeu.";
    quickCards.innerHTML = `<div class="focus-summary">Aucune opportunité directe disponible.</div>`;
    if (marketStrip) marketStrip.innerHTML = marketStripCard("Centre commerce", "En attente", "Choisis une marchandise pour afficher achat, vente et marge.");
    historyNode.innerHTML = `<div class="focus-summary">Aucun historique pour le moment.</div>`;
    buyTbody.innerHTML = `<tr><td colspan="5"><strong>Aucun achat trouvé.</strong></td></tr>`;
    sellTbody.innerHTML = `<tr><td colspan="5"><strong>Aucune vente trouvée.</strong></td></tr>`;
    if (sellOffers) sellOffers.innerHTML = `<div class="focus-summary">Aucune cible de revente disponible.</div>`;
    renderCommodityRouteTable([]);
    renderFavoriteCommodityButton();
    return;
  }

  const quick = intel.quick_trade || {};
  const bestBuy = quick.best_buy;
  const bestNearBuy = quick.best_near_buy;
  const bestSell = quick.best_sell;
  const bestLiveSell = quick.best_live_sell;
  const visibleRoutes = commodityRouteRows(intel.best_routes || []);
  const bestRoute = visibleRoutes[0] || null;
  const spread = quick.spread;
  const displayBuy = state.tradeLens === "assisted" ? (bestNearBuy || bestBuy) : bestBuy;
  const displaySell = state.tradeLens === "assisted" ? (bestLiveSell || bestSell) : bestSell;
  const activeUnits = commoditySpreadUnits(bestBuy, bestSell, bestRoute);
  const totalSpread = spread !== null && spread !== undefined ? Number(spread) * activeUnits : null;
  const trend = summarizeCommodityTrend(intel.history || []);
  const selectionContext = intel.selection_context || {};
  const contextLine = `Origine ${commodityContextLabel(selectionContext.origin)} • Cible ${commodityContextLabel(selectionContext.target)}`;
  const fallbackNotes = [];
  if (intel.fallback_buy_used) fallbackNotes.push("achat élargi");
  if (intel.fallback_sell_used) fallbackNotes.push("vente élargie");
  summary.innerHTML = `<strong>${escapeHtml(intel.commodity_name)}</strong><br />${bestBuy && bestSell ? `Achat mini: ${escapeHtml(bestBuy.system_name)} / ${escapeHtml(bestBuy.station_name)} • ${escapeHtml(credits(bestBuy.price))} | Revente maxi: ${escapeHtml(bestSell.system_name)} / ${escapeHtml(bestSell.station_name)} • ${escapeHtml(credits(bestSell.price))}` : bestRoute ? `Meilleure route actuelle: ${escapeHtml(bestRoute.source_system)} / ${escapeHtml(bestRoute.source_station)} → ${escapeHtml(bestRoute.target_system)} / ${escapeHtml(bestRoute.target_station)} • ${escapeHtml(credits(bestRoute.trip_profit))} le trajet` : intel.sell_same_market_only ? "Aucune revente distincte assez fraîche n'est visible pour cette marchandise dans les filtres actuels." : "Aucune route complète visible pour l'instant, mais les meilleurs achats et ventes sont listés ci-dessous."}${spread !== null && spread !== undefined ? `<br /><small>Ecart brut actuel: ${escapeHtml(credits(spread))} par unite.</small>` : ""}${fallbackNotes.length ? `<br /><small>Vue elargie activee: ${escapeHtml(fallbackNotes.join(' + '))}.</small>` : ""}`;

  if (marketStrip) {
    marketStrip.innerHTML = [
      marketStripCard("Marchandise", intel.commodity_name || intel.symbol || "n/d", contextLine),
      marketStripCard("Achat mini", bestBuy ? credits(bestBuy.price) : "n/d", bestBuy ? `${bestBuy.system_name} / ${bestBuy.station_name}` : "Aucune offre achat", "buy"),
      marketStripCard("Revente maxi", bestSell ? credits(bestSell.price) : "n/d", bestSell ? `${bestSell.system_name} / ${bestSell.station_name}` : (intel.sell_same_market_only ? "Même station que l'achat" : "Aucune offre vente"), "sell"),
      marketStripCard("Marge soute", totalSpread !== null ? credits(totalSpread) : "n/d", `${number(activeUnits)} t utilisées`, "spread"),
      marketStripCard("Tendance", trend.label, trend.detail),
    ].join("");
  }

  quickCards.innerHTML = [
    displayBuy
      ? `<article class="trade-card"><span class="metric-label">${state.tradeLens === "assisted" ? "Achat pratique" : "Achat le moins cher"}</span><strong>${escapeHtml(displayBuy.station_name)}</strong><span>${escapeHtml(displayBuy.system_name)} • ${escapeHtml(credits(displayBuy.price))}</span><span>${escapeHtml(number(displayBuy.stock))} unites • ${scoreBadge(displayBuy.confidence_score, displayBuy.confidence_label)}</span>${actionButton("Utiliser en achat", { offerAction: "set-origin", systemName: displayBuy.system_name, stationName: displayBuy.station_name }, "trade-card-action")}</article>`
      : `<article class="trade-card"><span class="metric-label">Le moins cher</span><strong>Aucun achat fiable</strong><span>Pas d'offre exploitable.</span></article>`,
    displaySell
      ? `<article class="trade-card"><span class="metric-label">${state.tradeLens === "assisted" ? "Vente pratique" : "Revente la plus haute"}</span><strong>${escapeHtml(displaySell.station_name)}</strong><span>${escapeHtml(displaySell.system_name)} • ${escapeHtml(credits(displaySell.price))}</span><span>Demande ${escapeHtml(number(displaySell.demand))} • ${scoreBadge(displaySell.confidence_score, displaySell.confidence_label)}</span>${actionButton("Utiliser en vente", { offerAction: "set-target", systemName: displaySell.system_name, stationName: displaySell.station_name }, "trade-card-action")}</article>`
      : `<article class="trade-card"><span class="metric-label">Vendre maintenant</span><strong>${intel.sell_same_market_only ? "Aucune revente distincte" : "Aucune vente fiable"}</strong><span>${intel.sell_same_market_only ? "Le seul prix frais visible est la même station que l'achat." : "Pas de demande exploitable."}</span></article>`,
    totalSpread !== null
      ? `<article class="trade-card"><span class="metric-label">Marge pour ta soute</span><strong>${escapeHtml(credits(totalSpread))}</strong><span>${escapeHtml(number(activeUnits))} t • ${spread !== null && spread !== undefined ? `${escapeHtml(credits(spread))}/u` : "n/d"}</span><span>${state.tradeLens === "assisted" ? "Lecture pratique de la cargaison active." : "Lecture brute basée sur le meilleur spread."}</span></article>`
      : `<article class="trade-card"><span class="metric-label">Marge pour ta soute</span><strong>n/d</strong><span>Le moteur attend une paire achat/vente cohérente.</span></article>`,
    bestRoute
      ? `<article class="trade-card trade-card-accent"><span class="metric-label">Trajet direct</span><strong>${escapeHtml(credits(bestRoute.trip_profit))}</strong><span>${escapeHtml(bestRoute.source_station)} → ${escapeHtml(bestRoute.target_station)}</span><span>${scoreBadge(bestRoute.route_score, bestRoute.confidence_label)} • ${escapeHtml(credits(bestRoute.profit_per_hour))}/h</span>${actionButton("Utiliser ce trajet", { routeAction: "use-route", sourceSystem: bestRoute.source_system, sourceStation: bestRoute.source_station, targetSystem: bestRoute.target_system, targetStation: bestRoute.target_station }, "trade-card-action")}</article>`
      : `<article class="trade-card trade-card-accent"><span class="metric-label">Trajet direct</span><strong>Aucune route complète</strong><span>Le moteur attend plus de données fraîches.</span></article>`,
  ].join("");

  const history = intel.history || [];
  historyBadge.textContent = history.length ? `${number(history.length)} points` : "Pas encore d'historique";
  if (history.length) {
    const maxSell = Math.max(...history.map(item => Number(item.max_sell || 0)), 1);
    historyNode.innerHTML = history.slice(-12).map(point => {
      const sellHeight = Math.max(10, Math.round((Number(point.max_sell || 0) / maxSell) * 100));
      const buyHeight = Math.max(8, Math.round((Number(point.min_buy || 0) / maxSell) * 100));
      return `<div class="history-point"><div class="history-bars-stack"><span class="history-bar buy" style="height:${buyHeight}%"></span><span class="history-bar sell" style="height:${sellHeight}%"></span></div><span class="history-value">${escapeHtml(credits(point.max_sell || point.min_buy || 0))}</span><span class="history-time">${escapeHtml(formatTimestamp(point.updated_at))}</span></div>`;
    }).join("");
  } else {
    historyNode.innerHTML = `<div class="focus-summary">Aucun historique visible pour le moment.</div>`;
  }

  for (const item of intel.best_buys || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(item.station_name)}</strong><br /><small>${escapeHtml(item.system_name)}</small><br />${actionButton("Utiliser", { offerAction: "set-origin", systemName: item.system_name, stationName: item.station_name })}</td><td>${escapeHtml(credits(item.price))}</td><td>${escapeHtml(number(item.stock))}</td><td>${escapeHtml(distanceLs(item.distance_ls))}${item.distance_from_player_ly !== null && item.distance_from_player_ly !== undefined ? `<br /><small>${escapeHtml(distanceLy(item.distance_from_player_ly))} depuis toi</small>` : ""}</td><td>${escapeHtml(formatHours(item.freshness_hours))}<br /><small>${scoreBadge(item.confidence_score, item.confidence_label)}</small></td>`;
    buyTbody.appendChild(tr);
  }
  if (!buyTbody.children.length) buyTbody.innerHTML = `<tr><td colspan="5"><strong>Aucun achat trouvé.</strong></td></tr>`;

  for (const item of intel.best_sells || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(item.station_name)}</strong><br /><small>${escapeHtml(item.system_name)}</small><br />${actionButton("Utiliser", { offerAction: "set-target", systemName: item.system_name, stationName: item.station_name })}</td><td>${escapeHtml(credits(item.price))}</td><td>${escapeHtml(number(item.demand))}</td><td>${escapeHtml(distanceLs(item.distance_ls))}${item.distance_from_player_ly !== null && item.distance_from_player_ly !== undefined ? `<br /><small>${escapeHtml(distanceLy(item.distance_from_player_ly))} depuis toi</small>` : ""}</td><td>${escapeHtml(formatHours(item.freshness_hours))}<br /><small>${scoreBadge(item.confidence_score, item.confidence_label)}</small></td>`;
    sellTbody.appendChild(tr);
  }
  if (!sellTbody.children.length) sellTbody.innerHTML = `<tr><td colspan="5"><strong>${intel.sell_same_market_only ? "Aucune revente distincte assez fraîche." : "Aucune vente trouvée."}</strong></td></tr>`;
  if (sellOffers) {
    sellOffers.innerHTML = (intel.best_sells || []).slice(0, 4).map(item => `
      <article class="trade-card">
        <span class="metric-label">Cible revente</span>
        <strong>${escapeHtml(item.station_name)}</strong>
        <span>${escapeHtml(item.system_name)} • ${escapeHtml(credits(item.price))}</span>
        <span>Demande ${escapeHtml(number(item.demand))}${item.distance_from_player_ly !== null && item.distance_from_player_ly !== undefined ? ` • ${escapeHtml(distanceLy(item.distance_from_player_ly))}` : ""}</span>
        ${actionButton("Utiliser en vente", { offerAction: "set-target", systemName: item.system_name, stationName: item.station_name }, "trade-card-action")}
      </article>
    `).join("") || `<div class="focus-summary">${intel.sell_same_market_only ? "Aucune cible de revente distincte n'est assez fraîche dans les filtres actuels." : "Aucune cible de revente visible."}</div>`;
  }
  renderCommodityRouteTable(visibleRoutes);
  renderFavoriteCommodityButton();
  if (state.dashboard) {
    renderHeroMetrics(state.dashboard);
    renderHighlights(state.dashboard);
    renderDecisionCards(state.dashboard);
  }
}

function renderMissionIntel(payload) {
  state.missionIntel = payload;
  const summary = document.getElementById("mission-summary");
  const cards = document.getElementById("mission-cards");
  const alternatives = document.getElementById("mission-alternatives");
  const sourceTbody = document.querySelector("#mission-source-table tbody");
  const routeTbody = document.querySelector("#mission-route-table tbody");
  cards.innerHTML = "";
  alternatives.innerHTML = "";
  sourceTbody.innerHTML = "";
  routeTbody.innerHTML = "";

  if (!payload || !payload.resolved) {
    summary.textContent = "Marchandise mission inconnue pour le moment.";
    cards.innerHTML = `<div class="focus-summary">Aucun plan mission disponible.</div>`;
    alternatives.innerHTML = `<div class="focus-summary">Aucune alternative.</div>`;
    sourceTbody.innerHTML = `<tr><td colspan="5"><strong>Aucune source d'achat.</strong></td></tr>`;
    routeTbody.innerHTML = `<tr><td colspan="5"><strong>Aucune route mission.</strong></td></tr>`;
    return;
  }

  const bestSource = payload.best_sources?.[0];
  const bestRoute = payload.best_routes?.[0];
  const targetLabel = payload.target ? `${payload.target.system_name} / ${payload.target.station_name}` : "Aucune destination fixe";
  summary.innerHTML = `<strong>${escapeHtml(payload.commodity_name)}</strong> • ${escapeHtml(number(payload.quantity))} unités<br />${payload.target ? `Destination mission: ${escapeHtml(targetLabel)}` : "Sans destination imposée: le moteur cherche aussi la meilleure revente possible."}`;

  cards.innerHTML = [
    bestSource
      ? `<article class="trade-card"><span class="metric-label">Meilleure source</span><strong>${escapeHtml(bestSource.station_name)}</strong><span>${escapeHtml(bestSource.system_name)} • ${escapeHtml(credits(bestSource.price))}</span><span>${escapeHtml(number(bestSource.units_covered))}/${escapeHtml(number(bestSource.requested_units))} unités • ${scoreBadge(bestSource.confidence_score, bestSource.confidence_label)}</span></article>`
      : `<article class="trade-card"><span class="metric-label">Meilleure source</span><strong>Aucune source fiable</strong><span>Le moteur n'a pas trouvé d'offre couvrable.</span></article>`,
    bestRoute
      ? `<article class="trade-card trade-card-accent"><span class="metric-label">Meilleure route mission</span><strong>${escapeHtml(bestRoute.source_station)}</strong><span>${escapeHtml(bestRoute.target_system)}${bestRoute.target_station ? ` / ${escapeHtml(bestRoute.target_station)}` : ""}</span><span>${scoreBadge(bestRoute.route_score, bestRoute.confidence_label)} • ${escapeHtml(minutesLabel(bestRoute.estimated_minutes))}</span></article>`
      : `<article class="trade-card trade-card-accent"><span class="metric-label">Meilleure route mission</span><strong>Aucune route prête</strong><span>Renseigne une destination ou laisse plus de données marché arriver.</span></article>`,
    `<article class="trade-card"><span class="metric-label">Historique mission</span><strong>${escapeHtml(number((payload.history || []).length))} points</strong><span>${payload.history?.length ? "Le prix a déjà commencé à être historisé." : "L'historique se remplit au fil des refreshs."}</span></article>`,
  ].join("");

  alternatives.innerHTML = [
    ...(payload.best_sources || []).slice(1, 3).map(item => `<article class="trade-card"><span class="metric-label">Alternative achat</span><strong>${escapeHtml(item.station_name)}</strong><span>${escapeHtml(item.system_name)} • ${escapeHtml(credits(item.price))}</span><span>${escapeHtml(number(item.units_covered))}/${escapeHtml(number(item.requested_units))} unites</span></article>`),
    ...(payload.best_routes || []).slice(1, 3).map(item => `<article class="trade-card"><span class="metric-label">Alternative route</span><strong>${escapeHtml(item.source_station)}</strong><span>${escapeHtml(item.target_station || item.target_system)}</span><span>${scoreBadge(item.route_score, item.confidence_label)}</span></article>`),
  ].join("") || `<div class="focus-summary">Aucune alternative utile pour l'instant.</div>`;

  for (const item of payload.best_sources || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(item.station_name)}</strong><br /><small>${escapeHtml(item.system_name)}</small></td><td>${escapeHtml(credits(item.price))}<br /><small>Total ${escapeHtml(credits(item.total_cost))}</small></td><td><strong>${escapeHtml(number(item.units_covered))}/${escapeHtml(number(item.requested_units))}</strong><br /><small>Manque ${escapeHtml(number(item.units_missing))}</small></td><td>${escapeHtml(distanceLs(item.distance_ls))}${item.distance_from_player_ly !== null && item.distance_from_player_ly !== undefined ? `<br /><small>${escapeHtml(distanceLy(item.distance_from_player_ly))} depuis toi</small>` : ""}</td><td>${scoreBadge(item.confidence_score, item.confidence_label)}</td>`;
    sourceTbody.appendChild(tr);
  }
  if (!sourceTbody.children.length) sourceTbody.innerHTML = `<tr><td colspan="5"><strong>Aucune source d'achat.</strong></td></tr>`;

  for (const item of payload.best_routes || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${escapeHtml(item.source_station)}</strong><br /><small>${escapeHtml(item.source_system)} → ${escapeHtml(item.target_station || item.target_system)}</small></td><td><strong>${escapeHtml(credits(item.total_cost || 0))}</strong><br /><small>${item.margin_per_unit !== null && item.margin_per_unit !== undefined ? `Marge ${escapeHtml(credits(item.margin_per_unit))}/u` : "Route de livraison / achat"}</small></td><td><strong>${escapeHtml(number(item.units))}</strong><br /><small>${escapeHtml(credits(item.source_buy_price || 0))}/u</small></td><td>${escapeHtml(minutesLabel(item.estimated_minutes))}<br /><small>${escapeHtml(distanceLy(item.route_distance_ly))}</small></td><td>${scoreBadge(item.route_score, item.confidence_label)}</td>`;
    routeTbody.appendChild(tr);
  }
  if (!routeTbody.children.length) routeTbody.innerHTML = `<tr><td colspan="5"><strong>Aucune route mission.</strong></td></tr>`;
}

function applyDefaults(dashboard) {
  const player = dashboard.player || {};
  document.getElementById("max-distance").value = dashboard.defaults.max_distance;
  document.getElementById("max-days-ago").value = dashboard.defaults.max_days_ago;
  document.getElementById("max-systems").value = dashboard.defaults.max_systems;
  safeSetValue("center-system", player.current_system || "", true);
  safeSetValue("route-cargo-capacity", player.cargo_capacity_override ?? player.cargo_capacity ?? 0, true);
  safeSetValue("route-jump-range", player.jump_range_override ?? player.jump_range ?? 0, true);
  safeSetValue("route-max-age-hours", dashboard.defaults.max_age_hours, true);
  safeSetValue("route-max-station-distance", dashboard.defaults.max_station_distance_ls, true);
  safeSetValue("route-min-profit-unit", dashboard.defaults.min_profit_unit, true);
  safeSetValue("route-min-buy-stock", dashboard.defaults.min_buy_stock ?? 0, true);
  safeSetValue("route-min-sell-demand", dashboard.defaults.min_sell_demand ?? 0, true);
  safeSetValue("route-min-pad-size", player.preferred_pad_size || dashboard.defaults.preferred_pad_size, true);
  document.getElementById("route-include-planetary").checked = true;
  document.getElementById("route-include-settlements").checked = false;
  document.getElementById("route-include-carriers").checked = false;
  document.getElementById("route-no-surprise").checked = Boolean(dashboard.defaults.no_surprise);
  safeSetValue("route-max-results", dashboard.defaults.max_results, true);
  safeSetValue("commodity-focus-input", state.commodityQuery, true);
  safeSetValue("mission-commodity-query", state.commodityQuery, true);
  safeSetValue("mission-quantity", player.cargo_capacity_override ?? player.cargo_capacity ?? 100, true);
  if (!document.getElementById("mission-target-system").value) safeSetValue("mission-target-system", "", true);
  if (!document.getElementById("mission-target-station").value) safeSetValue("mission-target-station", "", true);
  setChipActive("data-route-preset", "balanced");
  setChipActive("data-commodity", state.commodityQuery.toLowerCase());
  renderCommodityRefineStatus();
}

function renderDashboard(dashboard) {
  state.dashboard = dashboard;
  state.memory = dashboard.trader_memory || state.memory;
  renderEngineStatus(dashboard.engine_status);
  renderPlayer(dashboard.player, dashboard);
  renderCombatPanel(dashboard);
  renderNavigationPanel();
  renderSources(dashboard);
  renderHeroMetrics(dashboard);
  renderHighlights(dashboard);
  renderDecisionCards(dashboard);
  renderMemory(dashboard.trader_memory || {});
  renderWatchlist(dashboard.watchlist);
  renderRoutes(dashboard.routes, dashboard.dataset);
  renderLoops(dashboard.loops);
  renderCurrentMarket(dashboard.current_market);
  renderKnowledge(dashboard.knowledge);
  renderNameLibrarySummary(dashboard.name_library);
  renderFavoriteCommodityButton();
  renderCommodityRefineStatus();
}

function mergeDashboardPulse(pulseDashboard) {
  if (!pulseDashboard) return state.dashboard;
  const previous = state.dashboard || {};
  return {
    ...previous,
    ...pulseDashboard,
    routes: previous.routes || [],
    loops: previous.loops || [],
    route_views: previous.route_views || {},
    decision_cards: previous.decision_cards || {},
    watchlist: previous.watchlist || [],
    knowledge: previous.knowledge || [],
    defaults: previous.defaults || {},
    dataset: {
      ...(previous.dataset || {}),
      ...(pulseDashboard.dataset || {}),
    },
  };
}

function renderLocalPulse(pulseDashboard) {
  if (!pulseDashboard) return;
  const merged = mergeDashboardPulse(pulseDashboard);
  state.dashboard = merged;
  if (pulseDashboard.trader_memory) {
    state.memory = pulseDashboard.trader_memory;
    renderMemory(pulseDashboard.trader_memory);
  }
  renderEngineStatus(merged.engine_status);
  renderPlayer(merged.player || {}, merged);
  renderCombatPanel(merged);
  renderNavigationPanel();
  renderSources(merged);
  renderHeroMetrics(merged);
  renderCurrentMarket(merged.current_market || {});
}

function currentNameQuery() {
  return {
    q: document.getElementById("name-search-input").value.trim(),
    entry_type: document.getElementById("name-search-type").value,
  };
}

async function loadNameLibrary() {
  const params = new URLSearchParams({ limit: "80" });
  const query = currentNameQuery();
  if (query.q) params.set("q", query.q);
  if (query.entry_type) params.set("entry_type", query.entry_type);
  const payload = await api(`/api/names?${params.toString()}`);
  state.names = payload;
  renderNameLibrarySummary(payload.summary);
  renderNameLibraryResults(payload.results);
}

async function refreshNameLibrary() {
  status("Reconstruction de la bibliothèque FR...");
  const payload = await api("/api/names/refresh", { method: "POST", body: "{}" });
  state.names = payload;
  renderNameLibrarySummary(payload.summary);
  renderNameLibraryResults(payload.results);
  status(`Bibliothèque reconstruite : ${number(payload.summary.total)} entrées.`);
}

async function loadCommodityIntel(silent = false) {
  const query = (state.commodityQuery || "").trim();
  if (!query) {
    renderCommodityIntel(null);
    return;
  }
  if (!silent) status(`Analyse de ${query}...`);
  const params = new URLSearchParams({ q: query });
  Object.entries(commodityRefineParams()).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const payload = await api(`/api/commodity-intel?${params.toString()}`);
  renderCommodityIntel(payload);
  if (!silent) status(`Analyse ${payload.commodity_name || query} prête.`);
}

function missionBody() {
  return {
    commodity_query: commodityQueryFromInput("mission-commodity-query"),
    quantity: Math.max(1, numericValue("mission-quantity", 100)),
    target_system: document.getElementById("mission-target-system").value.trim() || null,
    target_station: document.getElementById("mission-target-station").value.trim() || null,
    max_age_hours: numericValue("route-max-age-hours", 72),
  };
}

function liveSnapshotBody(useFormValues = true) {
  if (!useFormValues) {
    return {
      commodity_query: state.commodityQuery,
      mission: null,
    };
  }
  const mission = missionBody();
  return {
    route: routeBody(),
    commodity_query: (state.commodityQuery || "").trim(),
    mission: mission.commodity_query ? mission : null,
  };
}

async function loadMissionIntel(silent = false) {
  const body = missionBody();
  if (!body.commodity_query) {
    renderMissionIntel(null);
    return;
  }
  if (!silent) status(`Analyse mission ${body.commodity_query}...`);
  const payload = await api("/api/mission-intel", { method: "POST", body: JSON.stringify(body) });
  renderMissionIntel(payload);
  if (!silent) status(`Plan mission prêt pour ${payload.commodity_name || body.commodity_query}.`);
}

function renderSnapshotPayload(payload, { applyFormDefaults = false } = {}) {
  renderDashboard(payload.dashboard);
  if (applyFormDefaults) applyDefaults(payload.dashboard);
  if (!hasCommodityRefineFilters() || !state.commodityQuery?.trim()) {
    renderCommodityIntel(payload.commodity_intel);
  }
  renderMissionIntel(payload.mission_intel);
}

async function loadLiveSnapshot({ silent = false, useFormValues = true, applyFormDefaults = false } = {}) {
  if (!silent) status("Chargement du snapshot trader...");
  const payload = await api("/api/live-snapshot", { method: "POST", body: JSON.stringify(liveSnapshotBody(useFormValues)) });
  renderSnapshotPayload(payload, { applyFormDefaults });
  if (hasCommodityRefineFilters() && state.commodityQuery?.trim()) {
    await loadCommodityIntel(true);
  }
  if (!silent) status(`Prêt. Journaux suivis dans ${payload.dashboard.journal_dir}`);
}

async function loadLocalPulse({ silent = false } = {}) {
  const payload = await api("/api/local-pulse");
  renderLocalPulse(payload.dashboard);
  if (!silent) {
    liveStatus(`Etat local mis a jour a ${new Date().toLocaleTimeString("fr-FR")}`);
  }
}

async function refreshDashboardLive() {
  if (document.visibilityState === "hidden") return;
  if (isEditingUi()) return;
  if (state.autoRefreshBusy) return;
  state.autoRefreshBusy = true;
  try {
    await loadLocalPulse({ silent: true });
  } catch (error) {
    console.error(error);
    liveStatus(`Auto-rafraîchissement en erreur • ${error.message}`);
  } finally {
    state.autoRefreshBusy = false;
  }
}

async function refreshDashboardFull() {
  if (document.visibilityState === "hidden") return;
  if (state.fullRefreshBusy) return;
  state.fullRefreshBusy = true;
  try {
    await loadLiveSnapshot({ silent: true, useFormValues: true });
  } catch (error) {
    console.error(error);
    liveStatus(`Rafraichissement complet en erreur - ${error.message}`);
  } finally {
    state.fullRefreshBusy = false;
  }
}

function startAutoRefresh() {
  if (!state.autoRefreshTimer) {
    state.autoRefreshTimer = window.setInterval(refreshDashboardLive, AUTO_REFRESH_MS);
  }
}

async function maybeRefreshFreshSourcesOnUse({ force = false } = {}) {
  if (state.sourceRefreshBusy) return;
  const now = Date.now();
  if (!force && now - state.lastUsageRefreshAt < Math.max(USAGE_REFRESH_MIN_INTERVAL_MS, 30000)) return;
  state.lastUsageRefreshAt = now;
  state.sourceRefreshBusy = true;
  try {
    const tasks = [];
    const hasCurrentMarket = Boolean(state.dashboard?.player?.current_market_id || state.dashboard?.current_market?.station_name);
    if (hasCurrentMarket) tasks.push(refreshCurrentMarket({ silent: true }));
    if (tasks.length) {
      liveStatus("Verification des sources fraiches...");
      await Promise.all(tasks);
      await refreshDashboardFull();
      liveStatus(`Sources reverifiees a ${new Date().toLocaleTimeString("fr-FR")}`);
    }
  } catch (error) {
    console.error(error);
    liveStatus(`Verification des sources en erreur • ${error.message}`);
  } finally {
    state.sourceRefreshBusy = false;
  }
}

function installUsageRefreshHooks() {
  window.addEventListener("focus", () => {
    maybeRefreshFreshSourcesOnUse({ force: true }).catch(error => console.warn("usage-refresh", error));
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      maybeRefreshFreshSourcesOnUse({ force: true }).catch(error => console.warn("usage-refresh", error));
    }
  });
}

function playerConfigBody() {
  return {
    cargo_capacity_override: numericValue("cargo-capacity-override", 0),
    jump_range_override: numericValue("jump-range-override", 0),
    preferred_pad_size: document.getElementById("preferred-pad-size").value,
  };
}

function routeBody() {
  return {
    cargo_capacity: numericValue("route-cargo-capacity", 100),
    jump_range: numericValue("route-jump-range", 15),
    max_age_hours: numericValue("route-max-age-hours", 72),
    max_station_distance_ls: numericValue("route-max-station-distance", 5000),
    min_profit_unit: numericValue("route-min-profit-unit", 1000),
    min_buy_stock: numericValue("route-min-buy-stock", 0),
    min_sell_demand: numericValue("route-min-sell-demand", 0),
    min_pad_size: document.getElementById("route-min-pad-size").value,
    include_planetary: document.getElementById("route-include-planetary").checked,
    include_settlements: document.getElementById("route-include-settlements").checked,
    include_fleet_carriers: document.getElementById("route-include-carriers").checked,
    no_surprise: document.getElementById("route-no-surprise").checked,
    max_results: numericValue("route-max-results", 25),
  };
}

async function loadDashboard() {
  await loadLiveSnapshot({ silent: false, useFormValues: false, applyFormDefaults: true });
  state.lastUsageRefreshAt = Date.now();
  setTradeMode(state.tradeMode, { scroll: false });
  startAutoRefresh();
}

async function importJournals() {
  status("Import des journaux locaux...");
  const payload = await api("/api/import/journals", { method: "POST", body: "{}" });
  renderDashboard(payload.dashboard);
  await loadNameLibrary();
  await Promise.all([loadCommodityIntel(true), loadMissionIntel(true)]);
  status(`Import terminé : ${number(payload.stats.events)} événements analysés.`);
}

async function syncArdent(overrides = {}, options = {}) {
  const silent = Boolean(options?.silent);
  if (!silent) status("Synchro Ardent en cours...");
  const body = {
    center_system: document.getElementById("center-system").value || null,
    max_distance: overrides.max_distance ?? Number(document.getElementById("max-distance").value),
    max_days_ago: Number(document.getElementById("max-days-ago").value),
    max_systems: overrides.max_systems ?? Number(document.getElementById("max-systems").value),
  };
  const payload = await api("/api/sync/ardent", { method: "POST", body: JSON.stringify(body) });
  renderDashboard(payload.dashboard);
  await Promise.all([loadCommodityIntel(true), loadMissionIntel(true)]);
  const blocked = Number(payload.stats?.access?.systems_blocked || 0);
  const failed = Number(payload.stats.systems_failed || 0);
  const fragments = [
    `${number(payload.stats.market_rows_upserted)} lignes marche`,
    blocked > 0 ? `${number(blocked)} systeme(s) sous permis non confirme` : null,
    failed > 0 ? `${number(failed)} systeme(s) partiellement ignore(s)` : null,
  ].filter(Boolean);
  if (!silent) status(`Synchro Ardent terminee : ${fragments.join(" | ")}.`);
}

async function refreshCurrentMarket(options = {}) {
  const silent = Boolean(options?.silent);
  if (!silent) status("Rafraichissement cible du marche courant...");
  const payload = await api("/api/refresh/current-market", { method: "POST", body: "{}" });
  renderDashboard(payload.dashboard);
  await Promise.all([loadCommodityIntel(true), loadMissionIntel(true)]);
  if (!silent) {
    status(`Marche courant rafraichi. Spansh : ${number(payload.stats.spansh_rows)}, EDSM : ${number(payload.stats.edsm_rows)}.`);
  }
}

async function startEDDN() {
  status("Démarrage de l'écoute EDDN...");
  await api("/api/eddn/start", { method: "POST", body: "{}" });
  const dashboard = await api("/api/dashboard");
  renderDashboard(dashboard);
  status("EDDN actif.");
}

async function stopEDDN() {
  status("Arrêt de l'écoute EDDN...");
  await api("/api/eddn/stop", { method: "POST", body: "{}" });
  const dashboard = await api("/api/dashboard");
  renderDashboard(dashboard);
  status("EDDN arrêté.");
}

async function savePlayerConfig(event) {
  if (event) event.preventDefault();
  status("Enregistrement des préférences...");
  const payload = await api("/api/player-config", { method: "POST", body: JSON.stringify(playerConfigBody()) });
  renderDashboard(payload.dashboard);
  await Promise.all([loadCommodityIntel(true), loadMissionIntel(true)]);
  status("Préférences enregistrées.");
}

async function recalculateRoutes(event) {
  if (event) event.preventDefault();
  status("Recalcul des routes...");
  const payload = await api("/api/routes", { method: "POST", body: JSON.stringify(routeBody()) });
  renderDashboard(payload.dashboard);
  await Promise.all([loadCommodityIntel(true), loadMissionIntel(true)]);
  status(`Routes recalculées : ${number(payload.dashboard.routes.length)} opportunités visibles.`);
}

async function searchNameLibrary(event) {
  event.preventDefault();
  status("Recherche dans la bibliothèque FR...");
  await loadNameLibrary();
  status("Bibliothèque FR mise à jour.");
}

async function focusCommodity(event) {
  event.preventDefault();
  state.commodityQuery = commodityQueryFromInput("commodity-focus-input");
  localStorage.setItem("elite_plug_focus_commodity", state.commodityQuery);
  safeSetValue("mission-commodity-query", document.getElementById("commodity-focus-input").value, true);
  setChipActive("data-commodity", state.commodityQuery.toLowerCase());
  await maybeRefreshFreshSourcesOnUse({ force: true });
  await Promise.all([loadCommodityIntel(false), loadMissionIntel(true), refreshDashboardLive()]);
}

async function analyzeMission(event) {
  if (event) event.preventDefault();
  await maybeRefreshFreshSourcesOnUse({ force: true });
  await Promise.all([loadMissionIntel(false), refreshDashboardLive()]);
}

function applyRoutePreset(name) {
  const preset = ROUTE_PRESETS[name];
  if (!preset) return;
  document.getElementById("route-max-age-hours").value = preset.maxAgeHours;
  document.getElementById("route-max-station-distance").value = preset.maxStationDistance;
  document.getElementById("route-min-profit-unit").value = preset.minProfitUnit;
  document.getElementById("route-include-planetary").checked = preset.includePlanetary;
  document.getElementById("route-include-settlements").checked = preset.includeSettlements;
  document.getElementById("route-include-carriers").checked = preset.includeCarriers;
  document.getElementById("route-no-surprise").checked = preset.noSurprise;
  safeSetValue("route-max-results", preset.maxResults);
  setChipActive("data-route-preset", name);
}

function applyCargoPreset(value) {
  safeSetValue("cargo-capacity-override", value);
  safeSetValue("route-cargo-capacity", value);
  safeSetValue("mission-quantity", value);
  setChipActive("data-cargo-preset", value);
}

function applyJumpPreset(value) {
  safeSetValue("jump-range-override", value);
  safeSetValue("route-jump-range", value);
  setChipActive("data-jump-preset", value);
}

function applyPadPreset(value) {
  safeSetValue("preferred-pad-size", value);
  safeSetValue("route-min-pad-size", value);
  setChipActive("data-pad-preset", value);
}

async function handlePresetClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.sideTab) { setAppMode(button.dataset.sideTab); return; }
  if (button.id === "btn-favorite-commodity") { await toggleCurrentCommodityFavorite(); return; }
  if (button.id === "btn-lens-absolute") { setTradeLens("absolute"); return; }
  if (button.id === "btn-lens-assisted") { setTradeLens("assisted"); return; }
  if (button.id === "btn-commodity-use-current") {
    applyCommodityRefinePreset("origin", "current_station");
    await loadCommodityIntel(false);
    return;
  }
  if (button.id === "btn-commodity-clear-context") {
    resetCommodityRefine();
    await loadCommodityIntel(false);
    return;
  }
  if (button.id === "btn-commodity-refine-apply") { await loadCommodityIntel(false); return; }
  if (button.id === "btn-commodity-refine-reset") { resetCommodityRefine(); await loadCommodityIntel(false); return; }
  if (button.dataset.cargoPreset) { applyCargoPreset(button.dataset.cargoPreset); await savePlayerConfig(); return; }
  if (button.dataset.jumpPreset) { applyJumpPreset(button.dataset.jumpPreset); await savePlayerConfig(); return; }
  if (button.dataset.padPreset) { applyPadPreset(button.dataset.padPreset); await savePlayerConfig(); return; }
  if (button.dataset.routePreset) { applyRoutePreset(button.dataset.routePreset); await recalculateRoutes(); return; }
  if (button.dataset.commodityOriginPreset) {
    applyCommodityRefinePreset("origin", button.dataset.commodityOriginPreset);
    await loadCommodityIntel(false);
    return;
  }
  if (button.dataset.commodityTargetPreset) {
    applyCommodityRefinePreset("target", button.dataset.commodityTargetPreset);
    await loadCommodityIntel(false);
    return;
  }
  if (button.dataset.scanDistance) {
    const distance = Number(button.dataset.scanDistance);
    document.getElementById("max-distance").value = distance;
    document.getElementById("max-systems").value = distance >= 80 ? 40 : distance >= 40 ? 30 : 20;
    await syncArdent({ max_distance: distance, max_systems: Number(document.getElementById("max-systems").value) });
    return;
  }
  if (button.dataset.commodity) {
    state.commodityQuery = button.dataset.commodity;
    localStorage.setItem("elite_plug_focus_commodity", state.commodityQuery);
    document.getElementById("commodity-focus-input").value = state.commodityQuery;
    document.getElementById("mission-commodity-query").value = state.commodityQuery;
    setChipActive("data-commodity", state.commodityQuery.toLowerCase());
    await Promise.all([loadCommodityIntel(false), loadMissionIntel(true)]);
    return;
  }
  if (button.dataset.offerAction === "set-origin") {
    await applyCommodityOfferSelection("origin", {
      system_name: button.dataset.systemName,
      station_name: button.dataset.stationName,
    });
    return;
  }
  if (button.dataset.offerAction === "set-target") {
    await applyCommodityOfferSelection("target", {
      system_name: button.dataset.systemName,
      station_name: button.dataset.stationName,
    });
    return;
  }
  if (button.dataset.routeAction === "use-route") {
    await applyCommodityRouteSelection({
      source_system: button.dataset.sourceSystem,
      source_station: button.dataset.sourceStation,
      target_system: button.dataset.targetSystem,
      target_station: button.dataset.targetStation,
    });
    return;
  }
  if (button.dataset.navigationAction === "activate") {
    setNavigationSelection({
      type: "station",
      role: button.dataset.role || "station",
      role_label: button.dataset.roleLabel || "Destination",
      system_name: button.dataset.systemName || "",
      station_name: button.dataset.stationName || "",
      distance_ly: button.dataset.distanceLy ? Number(button.dataset.distanceLy) : null,
      distance_ls: button.dataset.distanceLs ? Number(button.dataset.distanceLs) : null,
      price: button.dataset.price ? Number(button.dataset.price) : null,
      price_label: button.dataset.priceLabel || "",
      detail: button.dataset.detail || "",
    });
    const copied = await copyText(button.dataset.systemName || "");
    if (copied && button.dataset.systemName) {
      status(`${button.dataset.systemName} copie pour collage direct dans la carte galactique d'Elite.`);
    }
    return;
  }
  if (button.dataset.navigationAction === "copy") {
    const copied = await copyText(button.dataset.systemName || "");
    if (copied && button.dataset.systemName) {
      status(`${button.dataset.systemName} copie pour collage direct dans la carte galactique d'Elite.`);
    }
  }
}

async function handleMemoryAction(button) {
  const kind = button.dataset.memoryKind;
  const label = button.dataset.memoryLabel || button.textContent.trim();
  const entityId = button.dataset.memoryId || label;
  const secondary = button.dataset.memorySecondary || "";

  if (kind === "commodity") {
    safeSetValue("commodity-focus-input", label, true);
    safeSetValue("mission-commodity-query", label, true);
    state.commodityQuery = entityId;
    localStorage.setItem("elite_plug_focus_commodity", state.commodityQuery);
    await Promise.all([loadCommodityIntel(false), loadMissionIntel(true), refreshDashboardLive()]);
    return;
  }

  if (kind === "system") {
    safeSetValue("center-system", label, true);
    await syncArdent({ center_system: label });
    return;
  }

  if (kind === "station") {
    safeSetValue("mission-target-system", secondary, true);
    safeSetValue("mission-target-station", label, true);
    safeSetValue("center-system", secondary, true);
    return;
  }

  if (kind === "module") {
    safeSetValue("name-search-input", label, true);
    safeSetValue("name-search-type", "module", true);
    await loadNameLibrary();
    return;
  }

  if (kind === "query") {
    safeSetValue("universal-search-input", label, true);
    el("universal-search-input").focus();
  }
}

async function handleMissionMemory(button) {
  safeSetValue("mission-commodity-query", button.dataset.missionCommodity || "", true);
  safeSetValue("mission-quantity", button.dataset.missionQuantity || "1", true);
  safeSetValue("mission-target-system", button.dataset.missionSystem || "", true);
  safeSetValue("mission-target-station", button.dataset.missionStation || "", true);
  if (button.dataset.missionCommodity) {
    safeSetValue("commodity-focus-input", button.dataset.missionCommodity, true);
    state.commodityQuery = button.dataset.missionCommodity;
    localStorage.setItem("elite_plug_focus_commodity", state.commodityQuery);
  }
  await analyzeMission();
}

function hideAutocomplete(controller) {
  controller.panel.hidden = true;
  controller.activeIndex = -1;
}

function renderAutocomplete(controller) {
  const items = controller.items || [];
  if (!items.length) {
    hideAutocomplete(controller);
    controller.panel.innerHTML = "";
    return;
  }
  controller.panel.innerHTML = items.map((item, index) => {
    const meta = [item.type_label, item.secondary].filter(Boolean).join(" • ");
    const tags = (item.badges || []).slice(0, 4);
    return `<button class="autocomplete-item ${index === controller.activeIndex ? "active" : ""}" type="button" data-index="${index}"><span><span class="autocomplete-title">${escapeHtml(item.label)}</span><span class="autocomplete-subtitle">${escapeHtml(meta)}</span>${tags.length ? `<span class="autocomplete-tags">${tags.map(tag => `<span class="autocomplete-tag">${escapeHtml(tag)}</span>`).join("")}</span>` : ""}</span><span class="autocomplete-score">${escapeHtml(number(item.relevance || 0))}</span></button>`;
  }).join("");
  controller.panel.hidden = false;
}

async function fetchSuggestions(controller) {
  const query = controller.input.value.trim();
  if (!query) {
    controller.items = [];
    hideAutocomplete(controller);
    return;
  }
  const requestId = ++controller.requestId;
  const params = new URLSearchParams({
    q: query,
    scope: controller.input.dataset.suggestScope || "universal",
    limit: "8",
  });
  const systemSourceId = controller.input.dataset.suggestSystemSource;
  if (systemSourceId && el(systemSourceId)?.value?.trim()) {
    params.set("system_name", el(systemSourceId).value.trim());
  }
  const payload = await api(`/api/suggest?${params.toString()}`);
  if (requestId !== controller.requestId) return;
  controller.items = payload.results || [];
  controller.activeIndex = controller.items.length ? 0 : -1;
  renderAutocomplete(controller);
}

function scheduleSuggestions(controller) {
  window.clearTimeout(controller.timer);
  controller.timer = window.setTimeout(() => {
    fetchSuggestions(controller).catch(error => console.warn("suggest", error));
  }, 120);
}

async function acceptAutocomplete(controller, item, submitUniversal = false) {
  if (!item) return;
  applySuggestionToInput(controller.input, item);
  hideAutocomplete(controller);
  if (controller.input.id?.startsWith("commodity-origin-") || controller.input.id?.startsWith("commodity-target-")) {
    renderCommodityRefineStatus();
  }
  await rememberSelection(item.kind === "library" ? "module" : item.kind, item.entity_id, item.label, item.secondary || null, item.meta || null);
  if (submitUniversal) {
    await applyUniversalSelection(item);
  }
}

function installAutocomplete(input) {
  if (!input.id) return;
  if (!input.parentElement.classList.contains("autocomplete-shell")) {
    const shell = document.createElement("div");
    shell.className = "autocomplete-shell";
    input.parentNode.insertBefore(shell, input);
    shell.appendChild(input);
  }
  const panel = document.createElement("div");
  panel.className = "autocomplete-panel";
  panel.hidden = true;
  input.parentElement.appendChild(panel);
  const controller = { input, panel, items: [], activeIndex: -1, requestId: 0, timer: null };
  state.autocomplete.set(input.id, controller);

  input.addEventListener("input", () => {
    clearSelectionData(input);
    scheduleSuggestions(controller);
  });
  input.addEventListener("focus", () => {
    if (input.value.trim()) scheduleSuggestions(controller);
  });
  input.addEventListener("keydown", async event => {
    if (event.key === "ArrowDown" && controller.items.length) {
      event.preventDefault();
      controller.activeIndex = (controller.activeIndex + 1 + controller.items.length) % controller.items.length;
      renderAutocomplete(controller);
    } else if (event.key === "ArrowUp" && controller.items.length) {
      event.preventDefault();
      controller.activeIndex = (controller.activeIndex - 1 + controller.items.length) % controller.items.length;
      renderAutocomplete(controller);
    } else if (event.key === "Escape") {
      hideAutocomplete(controller);
    } else if ((event.key === "Enter" || event.key === "Tab") && controller.items.length && !panel.hidden) {
      event.preventDefault();
      const item = controller.items[Math.max(controller.activeIndex, 0)];
      await acceptAutocomplete(controller, item, input.id === "universal-search-input");
    }
  });
  panel.addEventListener("mousedown", event => event.preventDefault());
  panel.addEventListener("click", async event => {
    const button = event.target.closest(".autocomplete-item");
    if (!button) return;
    const item = controller.items[Number(button.dataset.index)];
    await acceptAutocomplete(controller, item, input.id === "universal-search-input");
  });
}

function setupAutocomplete() {
  document.querySelectorAll("input[data-suggest-scope]").forEach(input => {
    if (!state.autocomplete.has(input.id)) installAutocomplete(input);
  });
  document.addEventListener("click", event => {
    state.autocomplete.forEach(controller => {
      if (controller.input.contains(event.target) || controller.panel.contains(event.target)) return;
      hideAutocomplete(controller);
    });
  });
}

async function applyUniversalSelection(item) {
  if (!item) return;
  if (item.kind === "commodity") {
    safeSetValue("commodity-focus-input", item.label, true);
    safeSetValue("mission-commodity-query", item.label, true);
    applySuggestionToInput(el("commodity-focus-input"), item);
    applySuggestionToInput(el("mission-commodity-query"), item);
    state.commodityQuery = item.meta?.symbol || item.entity_id || item.label;
    localStorage.setItem("elite_plug_focus_commodity", state.commodityQuery);
    await Promise.all([loadCommodityIntel(false), loadMissionIntel(true), refreshDashboardLive()]);
    return;
  }
  if (item.kind === "system") {
    safeSetValue("center-system", item.label, true);
    applySuggestionToInput(el("center-system"), item);
    await syncArdent({ center_system: item.label });
    return;
  }
  if (item.kind === "station") {
    safeSetValue("center-system", item.meta?.system_name || item.secondary || "", true);
    safeSetValue("mission-target-system", item.meta?.system_name || item.secondary || "", true);
    safeSetValue("mission-target-station", item.label, true);
    applySuggestionToInput(el("mission-target-station"), item);
    return;
  }
  safeSetValue("name-search-input", item.label, true);
  if (item.meta?.entry_type) safeSetValue("name-search-type", item.meta.entry_type, true);
  await loadNameLibrary();
}

async function handleUniversalSearch(event) {
  if (event) event.preventDefault();
  const input = el("universal-search-input");
  const controller = state.autocomplete.get("universal-search-input");
  const selected = suggestionFromInput(input) || (controller?.items?.length ? controller.items[Math.max(controller.activeIndex, 0)] : null);
  const query = input.value.trim();
  if (!query) return;
  if (selected) {
    await applyUniversalSelection(selected);
    return;
  }
  await rememberSelection("query", query, query);
  safeSetValue("name-search-input", query, true);
  await loadNameLibrary();
}

function installKeyboardShortcuts() {
  document.addEventListener("keydown", event => {
    const target = event.target;
    const typing = Boolean(target.closest("input, textarea, select, [contenteditable='true']"));
    if (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      el("universal-search-input").focus();
      el("universal-search-input").select();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      el("universal-search-input").focus();
      el("universal-search-input").select();
    }
  });
}

function installCommodityRefineHooks() {
  [
    "commodity-origin-system",
    "commodity-origin-station",
    "commodity-target-system",
    "commodity-target-station",
  ].forEach(id => {
    const input = el(id);
    if (!input) return;
    input.addEventListener("input", () => {
      renderCommodityRefineStatus();
    });
    input.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      if (state.autocomplete.get(id)?.panel?.hidden === false) return;
      event.preventDefault();
      loadCommodityIntel(false).catch(error => {
        console.error(error);
        status(`Erreur : ${error.message}`);
      });
    });
  });
}

document.getElementById("btn-import").addEventListener("click", importJournals);
document.getElementById("btn-refresh-names").addEventListener("click", refreshNameLibrary);
document.getElementById("btn-sync").addEventListener("click", () => syncArdent());
document.getElementById("btn-refresh-market").addEventListener("click", refreshCurrentMarket);
document.getElementById("btn-eddn-start").addEventListener("click", startEDDN);
document.getElementById("btn-eddn-stop").addEventListener("click", stopEDDN);
document.getElementById("btn-universal-go").addEventListener("click", handleUniversalSearch);
document.getElementById("universal-search-form").addEventListener("submit", handleUniversalSearch);
document.getElementById("name-search-form").addEventListener("submit", searchNameLibrary);
document.getElementById("player-config-form").addEventListener("submit", savePlayerConfig);
document.getElementById("route-form").addEventListener("submit", recalculateRoutes);
document.getElementById("commodity-focus-form").addEventListener("submit", focusCommodity);
document.getElementById("mission-form").addEventListener("submit", analyzeMission);
document.getElementById("btn-mode-buy").addEventListener("click", () => setTradeMode("buy", { scroll: true }));
document.getElementById("btn-mode-sell").addEventListener("click", () => setTradeMode("sell", { scroll: true }));
document.addEventListener("click", event => {
  const memoryButton = event.target.closest("[data-memory-kind]");
  if (memoryButton) {
    handleMemoryAction(memoryButton).catch(error => {
      console.error(error);
      status(`Erreur : ${error.message}`);
    });
    return;
  }
  const missionButton = event.target.closest("[data-mission-commodity]");
  if (missionButton) {
    handleMissionMemory(missionButton).catch(error => {
      console.error(error);
      status(`Erreur : ${error.message}`);
    });
    return;
  }
  handlePresetClick(event).catch(error => {
    console.error(error);
    status(`Erreur : ${error.message}`);
  });
});

setupAutocomplete();
installKeyboardShortcuts();
installCommodityRefineHooks();
installUsageRefreshHooks();
setAppMode(state.appMode);
setTradeLens(state.tradeLens);

loadDashboard().catch(error => {
  console.error(error);
  status(`Erreur : ${error.message}`);
  liveStatus(`Connexion impossible • ${error.message}`);
});
