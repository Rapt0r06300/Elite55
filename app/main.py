from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import sqlite3
import sys
import threading
import time
import unicodedata
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import httpx
import zmq
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

try:
    import winreg
except ImportError:
    winreg = None


if getattr(sys, "frozen", False):
    APP_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    DATA_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parents[1]
    DATA_DIR = APP_DIR

BASE_DIR = APP_DIR
DB_PATH = DATA_DIR / "elite_trade.db"
ARDENT_API_BASE = "https://api.ardent-insight.com/v2"
SPANSH_API_BASE = "https://spansh.co.uk/api"
EDSM_BASE = "https://www.edsm.net"
EDDN_ENDPOINT = "tcp://eddn.edcd.io:9500"
REQUEST_TIMEOUT = 30.0
ACCESS_REQUEST_TIMEOUT = 8.0
LOCAL_SYNC_POLL_SECONDS = 2.0
LOCAL_MARKET_MAX_AGE_MINUTES = 20
REMOTE_MARKET_REFRESH_SECONDS = 180
WATCHLIST_SYMBOLS = ["gold", "silver", "gallium", "tritium"]
BOOTSTRAP_JOURNAL_TAIL_BYTES = 2 * 1024 * 1024
BOOTSTRAP_JOURNAL_MAX_LINES = 5000
BACKGROUND_START_DELAY_SECONDS = 8.0
SNAPSHOT_CACHE_TTL_SECONDS = 1.5
SNAPSHOT_CACHE_BUSY_STALE_SECONDS = 45.0
TRADER_MEMORY_LIMIT = 18
NO_DISTANCE_LIMIT_LS = 2_147_483_647
FEDERATION_RANK_PERMITS = {
    "sol": 4,
    "beta hydri": 5,
    "vega": 5,
    "plx 695": 6,
    "ross 128": 7,
    "exbeur": 8,
    "hors": 10,
}
EMPIRE_RANK_PERMITS = {
    "achenar": 4,
    "summerland": 7,
    "facece": 10,
}
logger = logging.getLogger(__name__)
snapshot_cache_lock = threading.Lock()
snapshot_cache: dict[str, tuple[float, dict[str, Any]]] = {}
background_flags = {"remote_seed_running": False}


def latest_mtime(path: Path) -> float:
    try:
        return max((item.stat().st_mtime for item in path.iterdir()), default=0.0)
    except OSError:
        return 0.0


def _saved_games_roots() -> list[Path]:
    roots: list[Path] = []
    user_profile = Path.home()
    roots.extend(
        [
            user_profile / "Saved Games",
            user_profile / "OneDrive" / "Saved Games",
        ]
    )
    if winreg is not None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                raw_value, _ = winreg.QueryValueEx(key, "{4C5C32FF-BB9D-43b0-B5B4-2D72E54EAAA4}")
                expanded = Path(str(raw_value).replace("%USERPROFILE%", str(user_profile)))
                roots.append(expanded)
        except OSError:
            pass
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def discover_journal_dir() -> Path:
    candidates = [root / "Frontier Developments" / "Elite Dangerous" for root in _saved_games_roots()]
    existing = [
        path
        for path in candidates
        if path.exists() and ((path / "Status.json").exists() or any(path.glob("Journal.*.log")))
    ]
    if existing:
        return max(existing, key=latest_mtime)
    return candidates[0] if candidates else Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def _steam_library_candidates() -> list[Path]:
    candidates: list[Path] = []
    steam_root = Path(r"C:\Program Files (x86)\Steam")
    library_vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not library_vdf.exists():
        return []
    try:
        content = library_vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for match in re.finditer(r'"path"\s+"([^"]+)"', content):
        candidates.append(Path(match.group(1).replace("\\\\", "\\")))
    return candidates


def discover_game_dir() -> Path | None:
    candidates = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Elite Dangerous"),
        Path(r"C:\Program Files (x86)\Frontier\EDLaunch\Products\elite-dangerous-64"),
        Path(r"C:\Program Files\Frontier\EDLaunch\Products\elite-dangerous-64"),
        Path.home() / "AppData" / "Local" / "Frontier_Developments" / "Products" / "elite-dangerous-64",
    ]
    for library_root in _steam_library_candidates():
        candidates.append(library_root / "steamapps" / "common" / "Elite Dangerous")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


JOURNAL_DIR = discover_journal_dir()
GAME_DIR = discover_game_dir()


STATUS_FLAG_BITS = {
    "docked": 1 << 0,
    "landed": 1 << 1,
    "landing_gear_down": 1 << 2,
    "shields_up": 1 << 3,
    "supercruise": 1 << 4,
    "flight_assist_off": 1 << 5,
    "hardpoints_deployed": 1 << 6,
    "in_wing": 1 << 7,
    "lights_on": 1 << 8,
    "cargo_scoop_deployed": 1 << 9,
    "silent_running": 1 << 10,
    "scooping_fuel": 1 << 11,
    "srv_handbrake": 1 << 12,
    "srv_turret": 1 << 13,
    "srv_close_to_ship": 1 << 14,
    "srv_drive_assist": 1 << 15,
    "fsd_mass_locked": 1 << 16,
    "fsd_charging": 1 << 17,
    "fsd_cooldown": 1 << 18,
    "low_fuel": 1 << 19,
    "overheating": 1 << 20,
    "has_lat_long": 1 << 21,
    "in_danger": 1 << 22,
    "being_interdicted": 1 << 23,
    "in_main_ship": 1 << 24,
    "in_fighter": 1 << 25,
    "in_srv": 1 << 26,
    "analysis_mode": 1 << 27,
    "night_vision": 1 << 28,
    "altitude_from_average_radius": 1 << 29,
    "fsd_jumping": 1 << 30,
    "srv_high_beam": 1 << 31,
}

STATUS_FLAG2_BITS = {
    "on_foot": 1 << 0,
    "in_taxi": 1 << 1,
    "in_multicrew": 1 << 2,
    "on_foot_in_station": 1 << 3,
    "on_foot_on_planet": 1 << 4,
    "aim_down_sight": 1 << 5,
    "low_oxygen": 1 << 6,
    "low_health": 1 << 7,
    "cold": 1 << 8,
    "hot": 1 << 9,
    "very_cold": 1 << 10,
    "very_hot": 1 << 11,
    "glide_mode": 1 << 12,
    "on_foot_in_hangar": 1 << 13,
    "on_foot_social_space": 1 << 14,
    "on_foot_exterior": 1 << 15,
    "breathable_atmosphere": 1 << 16,
    "telepresence_multicrew": 1 << 17,
    "physical_multicrew": 1 << 18,
    "fsd_hyperdrive_charging": 1 << 19,
}


KNOWLEDGE_ENTRIES = [
    {
        "category": "source",
        "title": "EDDN en temps réel",
        "summary": "C'est la source communautaire la plus proche du temps réel à l'échelle de la galaxie. Le logiciel l'écoute en continu pour garder la base fraîche.",
        "url": "https://eddn.edcd.io/schemas",
        "source_name": "EDDN",
        "languages": ["en"],
        "priority": 100,
    },
    {
        "category": "source",
        "title": "Ardent API",
        "summary": "API publique anonyme, orientée données EDDN, avec recherche de systèmes, stations, imports, exports, proximité et statistiques de marché.",
        "url": "https://github.com/iaincollins/ardent-api",
        "source_name": "Ardent",
        "languages": ["en"],
        "priority": 98,
    },
    {
        "category": "source",
        "title": "Spansh API",
        "summary": "Très utile pour rafraîchir précisément une station ou un système: marché, services, pads, import/export, coordonnées et timestamps.",
        "url": "https://spansh.co.uk/api/station/3230448384",
        "source_name": "Spansh",
        "languages": ["en"],
        "priority": 94,
    },
    {
        "category": "source",
        "title": "EDSM API",
        "summary": "Excellente source complémentaire pour systèmes, stations et marchés ciblés. Sert de vérification et de fallback.",
        "url": "https://www.edsm.net/en/api-system-v1",
        "source_name": "EDSM",
        "languages": ["en", "fr", "de", "es", "ja", "ru", "pt", "pl", "uk", "zh"],
        "priority": 92,
    },
    {
        "category": "source",
        "title": "Journaux locaux du jeu",
        "summary": "Indispensables pour connaître l'état exact du commandant, la station actuelle, le cargo, le vaisseau et les fichiers de marché locaux.",
        "url": "https://elite-journal.readthedocs.io/en/latest/File%20Format.html",
        "source_name": "Elite Dangerous Journal",
        "languages": ["en"],
        "priority": 96,
    },
    {
        "category": "source",
        "title": "INARA comme référence",
        "summary": "Très utile pour comparer des routes et surveiller l'écosystème, mais pas la meilleure base d'ingestion massive pour un moteur de marché temps réel.",
        "url": "https://inara.cz/elite/market-traderoutes",
        "source_name": "INARA",
        "languages": ["en"],
        "priority": 75,
    },
    {
        "category": "source",
        "title": "Frontier Community API",
        "summary": "Source officielle liée au compte du joueur via authentification. C'est la meilleure piste pour confirmer en direct la position, le vaisseau, les services et le marché courant du commandant.",
        "url": "https://www.elitedangerous.net/edmc.php",
        "source_name": "Frontier / CAPI",
        "languages": ["en"],
        "priority": 97,
    },
    {
        "category": "source",
        "title": "FleetManager market pages",
        "summary": "Interface publique reliée aux données EDDN avec pages de rapport de marché par station. Pas encore branchée comme source principale, mais exploitable en secours par scrapping ciblé.",
        "url": "https://edfm.space/market/station/3230448640",
        "source_name": "FleetManager",
        "languages": ["en"],
        "priority": 83,
    },
    {
        "category": "source",
        "title": "INARA commodity pages",
        "summary": "Les pages marchandise et station peuvent servir de source de vérification supplémentaire via scrapping ciblé, avec classement achat / vente et horodatage visible.",
        "url": "https://inara.cz/elite/commodities/",
        "source_name": "INARA Scraping",
        "languages": ["en"],
        "priority": 78,
    },
    {
        "category": "knowledge",
        "title": "Vraie fraîcheur des prix",
        "summary": "Le \"seconde par seconde\" global n'existe pas partout de façon garantie. La meilleure stratégie est d'empiler EDDN, journaux locaux, Ardent et vérifications ciblées.",
        "url": "",
        "source_name": "Synthèse",
        "languages": ["fr"],
        "priority": 99,
    },
    {
        "category": "knowledge",
        "title": "Le commerce se joue aussi sur le temps perdu",
        "summary": "Le profit brut seul ne suffit pas. Le logiciel pénalise naturellement les trajets trop longs en Ls, les données trop vieilles et les stations incompatibles.",
        "url": "",
        "source_name": "Synthèse",
        "languages": ["fr"],
        "priority": 90,
    },
]


NAME_SOURCE_PRIORITY = {
    "frontier_market": 100,
    "frontier_shipyard": 98,
    "frontier_journal": 96,
    "frontier_family": 88,
    "catalogue_derive": 72,
}


SHIP_CODE_FALLBACKS = {
    "adder": "Adder",
    "anaconda": "Anaconda",
    "asp": "Asp Explorer",
    "asp_scout": "Asp Scout",
    "belugaliner": "Beluga Liner",
    "cobramkiii": "Cobra Mk III",
    "cobramkiv": "Cobra Mk IV",
    "cobramkv": "Cobra Mk V",
    "corsair": "Corsair",
    "diamondback": "Diamondback Scout",
    "diamondbackxl": "Diamondback Explorer",
    "dolphin": "Dolphin",
    "eagle": "Eagle",
    "empire_courier": "Imperial Courier",
    "empire_eagle": "Imperial Eagle",
    "empire_fighter": "Imperial Fighter",
    "empire_trader": "Imperial Clipper",
    "federation_corvette": "Federal Corvette",
    "federation_dropship": "Federal Dropship",
    "federation_dropship_mkii": "Federal Assault Ship",
    "federation_fighter": "F63 Condor",
    "federation_gunship": "Federal Gunship",
    "ferdelance": "Fer-de-Lance",
    "hauler": "Hauler",
    "independant_trader": "Keelback",
    "independent_fighter": "Taipan",
    "krait_light": "Krait Phantom",
    "krait_mkii": "Krait Mk II",
    "mamba": "Mamba",
    "mandalay": "Mandalay",
    "orca": "Orca",
    "panthermkii": "Panther Clipper Mk II",
    "python": "Python",
    "python_nx": "Python Mk II",
    "sidewinder": "Sidewinder",
    "testbuggy": "Scarabée VRS",
    "type6": "Type-6 Transporter",
    "type7": "Type-7 Transporter",
    "type8": "Type-8 Transporter",
    "type9": "Type-9 Heavy",
    "type9_military": "Type-10 Defender",
    "typex": "Alliance Chieftain",
    "typex_2": "Alliance Crusader",
    "typex_3": "Alliance Challenger",
    "viper": "Viper Mk III",
    "viper_mkiv": "Viper Mk IV",
    "vulture": "Vulture",
}


ARMOUR_VARIANT_FR = {
    "grade1": "Blindage léger",
    "grade2": "Blindage renforcé",
    "grade3": "Blindage composite militaire",
    "mirrored": "Blindage miroir",
    "reactive": "Blindage réactif",
}


MODULE_FAMILY_FR_OVERRIDES = {
    "hpt_advancedtorppylon": "Pylône de torpilles",
    "hpt_basicmissilerack": "Lance-missiles à tête chercheuse",
    "hpt_beamlaser": "Laser à faisceau",
    "hpt_cargoscanner": "Analyseur de cargaison",
    "hpt_chafflauncher_tiny": "Paillettes",
    "hpt_cloudscanner": "Analyseur de sillage FSD",
    "hpt_crimescanner": "Analyseur de prime",
    "hpt_dumbfiremissilerack": "Lance-missiles",
    "hpt_heatsinklauncher": "Dissipateur thermique",
    "hpt_minelauncher": "Lance-mines",
    "hpt_minelauncher_fixed_small_impulse": "Lance-mines à impulsion",
    "hpt_mining_abrblstr": "Blaster abrasif",
    "hpt_mining_seismchrgwarhd": "Lanceur de charges sismiques",
    "hpt_mining_subsurfdispmisle": "Missile de déplacement sous-surface",
    "hpt_mininglaser": "Laser minier",
    "hpt_miningtoolv2": "Lance minière",
    "hpt_mkiiplasmashockautocannon": "Canon à choc Mk II",
    "hpt_mrascanner": "Analyseur à ondes pulsées",
    "hpt_multicannon": "Multi-canon",
    "hpt_plasmaaccelerator": "Accélérateur à plasma",
    "hpt_plasmapointdefence": "Tourelle de défense ponctuelle",
    "hpt_pulselaser": "Laser à impuls.",
    "hpt_pulselaserburst": "Laser à rafale",
    "hpt_railgun": "Canon électromagnétique",
    "hpt_shieldbooster": "Survolteur de bouclier",
    "hpt_slugshot": "Canon à frag.",
    "int_buggybay": "Hangar pour véhicule planétaire",
    "int_cargorack": "Compartiment soute",
    "int_dockingcomputer_advanced": "Ordinateur d'appontage",
    "int_dronecontrol_collection": "Collecteur",
    "int_dronecontrol_fueltransfer": "Drone de transfert de carburant",
    "int_dronecontrol_prospector": "Prospecteur",
    "int_dronecontrol_recon": "Drone de reconnaissance",
    "int_dronecontrol_repair": "Drone de réparation",
    "int_dronecontrol_resourcesiphon": "Pirateur d'écoutille",
    "int_engine": "Propulseurs",
    "int_fsdinterdictor": "Interdicteur de FSD",
    "int_fuelscoop": "Récupérateur de carburant",
    "int_fueltank": "Réservoir",
    "int_hullreinforcement": "Renforcement de coque",
    "int_hyperdrive": "FSD",
    "int_hyperdrive_overcharge": "FSD (SSN)",
    "int_largecargorack": "Compartiment soute étendu",
    "int_lifesupport": "Systèmes de survie",
    "int_modulereinforcement": "Renforcement de modules",
    "int_multidronecontrol_mining": "Contrôleur multi-drone minier",
    "int_multidronecontrol_operations": "Contrôleur multi-drone d'opérations",
    "int_multidronecontrol_rescue": "Contrôleur multi-drone de sauvetage",
    "int_multidronecontrol_xeno": "Contrôleur multi-drone xéno",
    "int_planetapproachsuite": "Suite d'approche planétaire",
    "int_planetapproachsuite_advanced": "Suite d'approche planétaire avancée",
    "int_powerdistributor": "Répartiteur de puissance",
    "int_powerplant": "Générateur",
    "int_refinery": "Raffinerie",
    "int_repairer": "Unité MAE",
    "int_sensors": "Capteurs",
    "int_shieldcellbank": "Cellules de bouclier",
    "int_shieldgenerator": "Générateur de bouclier",
    "int_supercruiseassist": "Assistance de supercroisière",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace(" ", "T")
    if normalized.endswith("+00"):
        normalized += ":00"
    if normalized.endswith("Z"):
        normalized = normalized.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def age_hours(value: str | None) -> float | None:
    parsed = parse_dt(value)
    if not parsed:
        return None
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 3600, 2)


def age_minutes(value: str | None) -> float | None:
    parsed = parse_dt(value)
    if not parsed:
        return None
    return round((datetime.now(timezone.utc) - parsed).total_seconds() / 60, 1)


def decode_status_flags(flags: Any, flags2: Any) -> dict[str, bool]:
    flags_value = int(flags or 0)
    flags2_value = int(flags2 or 0)
    decoded = {name: bool(flags_value & mask) for name, mask in STATUS_FLAG_BITS.items()}
    decoded.update({name: bool(flags2_value & mask) for name, mask in STATUS_FLAG2_BITS.items()})
    return decoded


def market_file_is_fresh(path: Path, timestamp: str | None) -> bool:
    if not path.exists():
        return False
    reference_dt = parse_dt(timestamp)
    if reference_dt:
        return age_minutes(timestamp) is not None and float(age_minutes(timestamp) or 0) <= LOCAL_MARKET_MAX_AGE_MINUTES
    file_age_minutes = (time.time() - path.stat().st_mtime) / 60
    return file_age_minutes <= LOCAL_MARKET_MAX_AGE_MINUTES


def player_runtime_snapshot(player: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(player)
    flags = dict(enriched.get("status_flags") or {})
    current_station = enriched.get("current_station")
    current_body_name = enriched.get("current_body_name")
    destination_name = enriched.get("destination_name") or ((enriched.get("destination") or {}).get("Name"))
    if isinstance(destination_name, str) and destination_name.startswith("$"):
        destination_name = None

    if flags.get("on_foot"):
        local_mode = "À pied"
    elif flags.get("docked"):
        local_mode = "Amarré"
    elif flags.get("landed"):
        local_mode = "Posé"
    elif flags.get("supercruise"):
        local_mode = "Supercroisière"
    elif flags.get("glide_mode"):
        local_mode = "Glisse orbitale"
    elif flags.get("fsd_jumping") or flags.get("fsd_hyperdrive_charging"):
        local_mode = "Saut hyperespace"
    elif flags.get("fsd_charging"):
        local_mode = "FSD en charge"
    elif current_station:
        local_mode = "Approche station"
    else:
        local_mode = "En vol"

    if flags.get("docked") and current_station:
        station_display = current_station
    elif current_station:
        station_display = f"Approche {current_station}"
    elif current_body_name:
        station_display = current_body_name
    elif destination_name:
        station_display = f"Cap vers {destination_name}"
    else:
        station_display = "En vol"

    if flags.get("docked") and current_station and enriched.get("current_system"):
        location_line = f"{enriched['current_system']} / {current_station}"
    elif enriched.get("current_system") and destination_name:
        location_line = f"{enriched['current_system']} • destination {destination_name}"
    else:
        location_line = enriched.get("current_system") or station_display

    enriched["local_mode"] = local_mode
    enriched["station_display"] = station_display
    enriched["destination_name"] = destination_name
    enriched["location_line"] = location_line
    return enriched


def normalize_text_key(value: Any) -> str:
    text = str(value or "").strip().replace("\u00A0", " ").lower()
    if text.startswith("$") and text.endswith(";"):
        text = text[1:-1]
    return text


def strip_diacritics(value: Any) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_search_text(value: Any) -> str:
    text = strip_diacritics(str(value or "").replace("\u00A0", " "))
    text = text.strip().lower()
    if text.startswith("$") and text.endswith(";"):
        text = text[1:-1]
    return re.sub(r"\s+", " ", text)


def compact_search_key(value: Any) -> str:
    text = normalize_search_text(value)
    text = text.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", text)


def search_words(value: Any) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", normalize_search_text(value)) if token]


def compact_key(value: Any) -> str:
    text = normalize_text_key(value)
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def normalize_lookup_key(value: Any) -> str:
    text = normalize_text_key(value)
    text = text.replace(" ", "_")
    text = text.replace("-", "_")
    text = re.sub(r"[^a-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def normalize_category_key(value: Any) -> str:
    text = normalize_text_key(value)
    text = re.sub(r"^.*category_", "", text)
    return compact_key(text)


def normalize_commodity_symbol(raw: Any, *fallbacks: Any) -> str:
    for candidate in (raw, *fallbacks):
        text = normalize_text_key(candidate)
        if not text:
            continue
        text = re.sub(r"_name$", "", text)
        if text.startswith("market_category_"):
            continue
        symbol = compact_key(text)
        if symbol:
            return symbol
    return ""


def normalize_module_key(value: Any) -> str:
    text = normalize_text_key(value)
    return re.sub(r"_name$", "", text)


def module_family_key(value: Any) -> str:
    key = normalize_module_key(value)
    key = re.sub(r"_(fixed|gimbal|turret)_(tiny|smallfree|small|medium|large|huge)$", "", key)
    key = re.sub(r"_size\d+_class\d+$", "", key)
    key = re.sub(r"_grade\d+$", "", key)
    key = re.sub(r"_(mirrored|reactive)$", "", key)
    return key


def normalize_ship_code(value: Any) -> str:
    return normalize_lookup_key(value)


def source_priority(name: str | None) -> int:
    return NAME_SOURCE_PRIORITY.get(name or "", 0)


def format_ship_name(code: str) -> str:
    normalized = normalize_ship_code(code)
    if normalized in SHIP_CODE_FALLBACKS:
        return SHIP_CODE_FALLBACKS[normalized]
    text = normalized.replace("_", " ").title().replace("Mk Iii", "Mk III").replace("Mk Ii", "Mk II").replace("Mk Iv", "Mk IV").replace("Mk V", "Mk V")
    return text or str(code)


def derive_armour_name(module_code: str) -> str | None:
    key = normalize_module_key(module_code)
    for suffix, label in ARMOUR_VARIANT_FR.items():
        if key.endswith(f"_{suffix}"):
            return label
    return None


def derive_module_name_fr(module_code: str, family_map: dict[str, str]) -> str | None:
    key = normalize_module_key(module_code)
    direct = family_map.get(key) or MODULE_FAMILY_FR_OVERRIDES.get(key)
    if direct:
        return direct
    armour_name = derive_armour_name(key)
    if armour_name:
        return armour_name
    family = module_family_key(key)
    return family_map.get(family) or MODULE_FAMILY_FR_OVERRIDES.get(family)


def better_price_candidate(candidate: dict[str, Any], current: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    candidate_dt = parse_dt(candidate.get("updated_at"))
    current_dt = parse_dt(current.get("updated_at"))
    if candidate_dt and current_dt and candidate_dt != current_dt:
        return candidate_dt > current_dt
    if candidate_dt and not current_dt:
        return True
    if not candidate_dt and current_dt:
        return False
    candidate_fields = sum(1 for field in ("buy_price", "sell_price", "demand", "stock") if int(candidate.get(field) or 0) > 0)
    current_fields = sum(1 for field in ("buy_price", "sell_price", "demand", "stock") if int(current.get(field) or 0) > 0)
    if candidate_fields != current_fields:
        return candidate_fields > current_fields
    return source_priority(candidate.get("source")) >= source_priority(current.get("source"))


def infer_pad_size(station_type: str | None, max_landing_pad: int | None = None) -> str:
    if max_landing_pad == 3:
        return "L"
    if max_landing_pad == 2:
        return "M"
    if max_landing_pad == 1:
        return "S"
    text = (station_type or "").lower()
    if "carrier" in text or "starport" in text or "port" in text or "megaship" in text or "drake-class" in text:
        return "L"
    if "outpost" in text or "settlement" in text:
        return "M"
    return "?"


def is_planetary(station_type: str | None) -> bool:
    text = (station_type or "").lower()
    return "planetary" in text or "surface" in text or "onfoot" in text or "settlement" in text


def is_odyssey_station(station_type: str | None) -> bool:
    text = (station_type or "").lower()
    return "onfoot" in text or "settlement" in text


def is_fleet_carrier(station_type: str | None) -> bool:
    return "carrier" in (station_type or "").lower()


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS player_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS systems (
    name TEXT PRIMARY KEY,
    address INTEGER,
    x REAL,
    y REAL,
    z REAL,
    allegiance TEXT,
    government TEXT,
    faction TEXT,
    faction_state TEXT,
    population INTEGER,
    security TEXT,
    economy_primary TEXT,
    economy_secondary TEXT,
    reserve TEXT,
    controlling_power TEXT,
    powerplay_state TEXT,
    requires_permit INTEGER NOT NULL DEFAULT 0,
    permit_name TEXT,
    access_updated_at TEXT,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stations (
    market_id INTEGER PRIMARY KEY,
    system_name TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT,
    distance_to_arrival REAL,
    allegiance TEXT,
    government TEXT,
    economy_primary TEXT,
    economy_secondary TEXT,
    landing_pad TEXT,
    is_planetary INTEGER NOT NULL DEFAULT 0,
    is_odyssey INTEGER NOT NULL DEFAULT 0,
    is_fleet_carrier INTEGER NOT NULL DEFAULT 0,
    has_market INTEGER NOT NULL DEFAULT 1,
    has_shipyard INTEGER NOT NULL DEFAULT 0,
    has_outfitting INTEGER NOT NULL DEFAULT 0,
    services_json TEXT,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commodities (
    symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_fr TEXT,
    category TEXT,
    is_rare INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commodity_prices (
    market_id INTEGER NOT NULL,
    commodity_symbol TEXT NOT NULL,
    buy_price INTEGER NOT NULL DEFAULT 0,
    sell_price INTEGER NOT NULL DEFAULT 0,
    demand INTEGER NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    demand_bracket TEXT,
    stock_bracket TEXT,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (market_id, commodity_symbol)
);

CREATE TABLE IF NOT EXISTS commodity_price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id INTEGER NOT NULL,
    commodity_symbol TEXT NOT NULL,
    buy_price INTEGER NOT NULL DEFAULT 0,
    sell_price INTEGER NOT NULL DEFAULT 0,
    demand INTEGER NOT NULL DEFAULT 0,
    stock INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (market_id, commodity_symbol, buy_price, sell_price, demand, stock, source, updated_at)
);

CREATE TABLE IF NOT EXISTS knowledge_entries (
    title TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    url TEXT,
    source_name TEXT NOT NULL,
    languages_json TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS name_library (
    entry_type TEXT NOT NULL,
    lookup_key TEXT NOT NULL,
    name TEXT,
    name_fr TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL,
    is_exact INTEGER NOT NULL DEFAULT 0,
    confidence INTEGER NOT NULL DEFAULT 0,
    extra_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entry_type, lookup_key)
);

CREATE INDEX IF NOT EXISTS idx_name_library_name_fr ON name_library(name_fr);
CREATE INDEX IF NOT EXISTS idx_price_history_symbol_updated_at ON commodity_price_history(commodity_symbol, updated_at);
""" 


class Repository:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_lock = threading.Lock()
        self._trade_rows_cache: list[dict[str, Any]] | None = None
        self._trade_rows_cached_at = 0.0
        self._lookup_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self.init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=8.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 8000")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA_SQL)
            self._ensure_column(conn, "systems", "requires_permit", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "systems", "permit_name", "TEXT")
            self._ensure_column(conn, "systems", "access_updated_at", "TEXT")

    def invalidate_trade_rows_cache(self) -> None:
        with self._cache_lock:
            self._trade_rows_cache = None
            self._trade_rows_cached_at = 0.0
            self._lookup_cache.clear()

    def _cached_lookup_rows(
        self,
        key: str,
        builder: Callable[[], list[dict[str, Any]]],
        *,
        max_age_seconds: float = 6.0,
    ) -> list[dict[str, Any]]:
        with self._cache_lock:
            cached = self._lookup_cache.get(key)
            if cached and (time.monotonic() - cached[0]) <= max_age_seconds:
                return cached[1]
        rows = builder()
        with self._cache_lock:
            self._lookup_cache[key] = (time.monotonic(), rows)
        return rows

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
        if column_name in existing:
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    def seed_knowledge(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM knowledge_entries")
            conn.executemany(
                """
                INSERT INTO knowledge_entries (title, category, summary, url, source_name, languages_json, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        entry["title"],
                        entry["category"],
                        entry["summary"],
                        entry.get("url", ""),
                        entry["source_name"],
                        json.dumps(entry.get("languages", []), ensure_ascii=False),
                        entry.get("priority", 0),
                    )
                    for entry in KNOWLEDGE_ENTRIES
                ],
            )

    def normalize_commodity_catalog(self) -> dict[str, int]:
        with self.connect() as conn:
            commodity_rows = [dict(row) for row in conn.execute("SELECT * FROM commodities").fetchall()]
            price_rows = [dict(row) for row in conn.execute("SELECT * FROM commodity_prices").fetchall()]

        merged_commodities: dict[str, dict[str, Any]] = {}
        for row in commodity_rows:
            symbol = normalize_commodity_symbol(row.get("symbol"), row.get("name_fr"), row.get("name"))
            if not symbol:
                continue
            merged = merged_commodities.get(symbol)
            candidate = {
                "symbol": symbol,
                "name": row.get("name_fr") or row.get("name") or symbol,
                "name_fr": row.get("name_fr"),
                "category": normalize_category_key(row.get("category")) or row.get("category"),
                "is_rare": int(row.get("is_rare") or 0),
                "updated_at": row.get("updated_at") or utc_now_iso(),
            }
            if merged is None:
                merged_commodities[symbol] = candidate
                continue
            if candidate["name_fr"] and not merged.get("name_fr"):
                merged["name_fr"] = candidate["name_fr"]
            if candidate["name"] and (str(merged.get("name") or "").startswith("$") or not merged.get("name")):
                merged["name"] = candidate["name"]
            if candidate["category"] and not merged.get("category"):
                merged["category"] = candidate["category"]
            if candidate["is_rare"]:
                merged["is_rare"] = 1
            candidate_dt = parse_dt(candidate["updated_at"])
            merged_dt = parse_dt(merged["updated_at"])
            if candidate_dt and (not merged_dt or candidate_dt > merged_dt):
                merged["updated_at"] = candidate["updated_at"]

        merged_prices: dict[tuple[int, str], dict[str, Any]] = {}
        for row in price_rows:
            symbol = normalize_commodity_symbol(row.get("commodity_symbol"))
            if not symbol:
                continue
            candidate = {
                "market_id": int(row["market_id"]),
                "commodity_symbol": symbol,
                "buy_price": int(row.get("buy_price") or 0),
                "sell_price": int(row.get("sell_price") or 0),
                "demand": int(row.get("demand") or 0),
                "stock": int(row.get("stock") or 0),
                "demand_bracket": row.get("demand_bracket") or "",
                "stock_bracket": row.get("stock_bracket") or "",
                "source": row.get("source") or "",
                "updated_at": row.get("updated_at") or utc_now_iso(),
            }
            key = (candidate["market_id"], candidate["commodity_symbol"])
            if better_price_candidate(candidate, merged_prices.get(key)):
                merged_prices[key] = candidate

        with self.connect() as conn:
            conn.execute("DELETE FROM commodity_prices")
            conn.execute("DELETE FROM commodities")
            conn.executemany(
                """
                INSERT INTO commodities (symbol, name, name_fr, category, is_rare, updated_at)
                VALUES (:symbol, :name, :name_fr, :category, :is_rare, :updated_at)
                """,
                sorted(merged_commodities.values(), key=lambda row: row["symbol"]),
            )
            conn.executemany(
                """
                INSERT INTO commodity_prices (
                    market_id, commodity_symbol, buy_price, sell_price, demand, stock,
                    demand_bracket, stock_bracket, source, updated_at
                )
                VALUES (
                    :market_id, :commodity_symbol, :buy_price, :sell_price, :demand, :stock,
                    :demand_bracket, :stock_bracket, :source, :updated_at
                )
                """,
                sorted(merged_prices.values(), key=lambda row: (row["market_id"], row["commodity_symbol"])),
            )
        self.invalidate_trade_rows_cache()

        return {
            "commodities_before": len(commodity_rows),
            "commodities_after": len(merged_commodities),
            "prices_before": len(price_rows),
            "prices_after": len(merged_prices),
        }

    def replace_name_library(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_entry in entries:
            entry_type = normalize_lookup_key(raw_entry.get("entry_type"))
            lookup_key = normalize_lookup_key(raw_entry.get("lookup_key"))
            if not entry_type or not lookup_key:
                continue
            candidate = {
                "entry_type": entry_type,
                "lookup_key": lookup_key,
                "name": raw_entry.get("name"),
                "name_fr": raw_entry.get("name_fr") or raw_entry.get("name"),
                "aliases_json": json.dumps(sorted(set(raw_entry.get("aliases", []))), ensure_ascii=False),
                "source": raw_entry.get("source") or "catalogue_derive",
                "is_exact": 1 if raw_entry.get("is_exact") else 0,
                "confidence": int(raw_entry.get("confidence") or 0),
                "extra_json": json.dumps(raw_entry.get("extra", {}), ensure_ascii=False),
                "updated_at": raw_entry.get("updated_at") or utc_now_iso(),
            }
            key = (entry_type, lookup_key)
            current = deduped.get(key)
            if current is None:
                deduped[key] = candidate
                continue
            if (
                candidate["is_exact"] > current["is_exact"]
                or candidate["confidence"] > current["confidence"]
                or source_priority(candidate["source"]) > source_priority(current["source"])
            ):
                deduped[key] = candidate
                current = deduped[key]
            aliases = sorted(set(json.loads(current["aliases_json"]) + json.loads(candidate["aliases_json"])))
            current["aliases_json"] = json.dumps(aliases, ensure_ascii=False)
            if not current.get("name_fr") and candidate.get("name_fr"):
                current["name_fr"] = candidate["name_fr"]
            if not current.get("name") and candidate.get("name"):
                current["name"] = candidate["name"]

        with self.connect() as conn:
            conn.execute("DELETE FROM name_library")
            conn.executemany(
                """
                INSERT INTO name_library (
                    entry_type, lookup_key, name, name_fr, aliases_json, source,
                    is_exact, confidence, extra_json, updated_at
                )
                VALUES (
                    :entry_type, :lookup_key, :name, :name_fr, :aliases_json, :source,
                    :is_exact, :confidence, :extra_json, :updated_at
                )
                """,
                sorted(deduped.values(), key=lambda row: (row["entry_type"], row["lookup_key"])),
            )

        return self.name_library_summary()

    def name_library_summary(self) -> dict[str, Any]:
        with self.connect() as conn:
            total_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN is_exact = 1 THEN 1 ELSE 0 END) AS exact_total
                FROM name_library
                """
            ).fetchone()
            type_rows = conn.execute(
                """
                SELECT
                    entry_type,
                    COUNT(*) AS total,
                    SUM(CASE WHEN is_exact = 1 THEN 1 ELSE 0 END) AS exact_total
                FROM name_library
                GROUP BY entry_type
                ORDER BY total DESC, entry_type ASC
                """
            ).fetchall()
        return {
            "total": int(total_row["total"] or 0),
            "exact_total": int(total_row["exact_total"] or 0),
            "derived_total": int((total_row["total"] or 0) - (total_row["exact_total"] or 0)),
            "updated_at": self.get_state("name_library_last_refresh"),
            "types": [
                {
                    "entry_type": row["entry_type"],
                    "total": int(row["total"] or 0),
                    "exact_total": int(row["exact_total"] or 0),
                }
                for row in type_rows
            ],
        }

    def search_name_library(self, query: str = "", entry_type: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
        clean_query = (query or "").strip()
        normalized_type = normalize_lookup_key(entry_type) if entry_type else None
        if normalized_type:
            rows = [row for row in self.name_entries_catalog(normalized_type)]
        else:
            rows = [row for row in self.name_entries_catalog()]
        if clean_query:
            ranked: list[dict[str, Any]] = []
            for row in rows:
                score, match_label, _ = best_variant_score(
                    clean_query,
                    row.get("lookup_key"),
                    row.get("name_fr"),
                    row.get("name"),
                    *(row.get("aliases") or []),
                )
                if score <= 0:
                    continue
                ranked.append(
                    {
                        **row,
                        "match_score": score,
                        "match_label": match_label,
                    }
                )
            ranked.sort(
                key=lambda row: (
                    int(row.get("match_score") or 0),
                    1 if row.get("is_exact") else 0,
                    int(row.get("confidence") or 0),
                    str(row.get("name_fr") or ""),
                    str(row.get("lookup_key") or ""),
                ),
                reverse=True,
            )
            rows = ranked
        else:
            rows.sort(
                key=lambda row: (
                    1 if row.get("is_exact") else 0,
                    int(row.get("confidence") or 0),
                    str(row.get("name_fr") or ""),
                    str(row.get("lookup_key") or ""),
                ),
                reverse=True,
            )
        return rows[: max(1, min(int(limit or 60), 200))]

    def systems_catalog(self) -> list[dict[str, Any]]:
        def builder() -> list[dict[str, Any]]:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT name, address, x, y, z, requires_permit, permit_name, updated_at
                    FROM systems
                    ORDER BY name COLLATE NOCASE ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]

        return self._cached_lookup_rows("systems_catalog", builder)

    def stations_catalog(self) -> list[dict[str, Any]]:
        def builder() -> list[dict[str, Any]]:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        st.market_id,
                        st.system_name,
                        st.name AS station_name,
                        st.type AS station_type,
                        st.distance_to_arrival,
                        st.landing_pad,
                        st.has_market,
                        st.is_planetary,
                        st.is_odyssey,
                        st.is_fleet_carrier,
                        st.updated_at,
                        sy.x,
                        sy.y,
                        sy.z,
                        sy.requires_permit,
                        sy.permit_name
                    FROM stations st
                    LEFT JOIN systems sy ON sy.name = st.system_name
                    ORDER BY st.updated_at DESC, st.name COLLATE NOCASE ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]

        return self._cached_lookup_rows("stations_catalog", builder)

    def commodities_catalog(self) -> list[dict[str, Any]]:
        def builder() -> list[dict[str, Any]]:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT symbol, name, name_fr, category, is_rare, updated_at
                    FROM commodities
                    ORDER BY COALESCE(name_fr, name) COLLATE NOCASE ASC
                    """
                ).fetchall()
            return [dict(row) for row in rows]

        return self._cached_lookup_rows("commodities_catalog", builder)

    def name_entries_catalog(self, entry_type: str | None = None) -> list[dict[str, Any]]:
        cache_key = f"name_entries:{normalize_lookup_key(entry_type) if entry_type else '*'}"

        def builder() -> list[dict[str, Any]]:
            params: list[Any] = []
            sql = """
                SELECT entry_type, lookup_key, name, name_fr, aliases_json, source, is_exact, confidence, updated_at
                FROM name_library
            """
            if entry_type:
                sql += " WHERE entry_type = ?"
                params.append(normalize_lookup_key(entry_type))
            sql += " ORDER BY is_exact DESC, confidence DESC, name_fr COLLATE NOCASE ASC, lookup_key ASC"
            with self.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "entry_type": row["entry_type"],
                    "lookup_key": row["lookup_key"],
                    "name": row["name"],
                    "name_fr": row["name_fr"] or row["name"] or row["lookup_key"],
                    "aliases": json.loads(row["aliases_json"]),
                    "source": row["source"],
                    "is_exact": bool(row["is_exact"]),
                    "confidence": int(row["confidence"] or 0),
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

        return self._cached_lookup_rows(cache_key, builder)

    def set_state(self, key: str, value: Any) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO player_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), utc_now_iso()),
            )

    def set_states(self, values: dict[str, Any]) -> None:
        now = utc_now_iso()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO player_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                [(key, json.dumps(value, ensure_ascii=False), now) for key, value in values.items()],
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value_json FROM player_state WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        return json.loads(row["value_json"])

    def get_all_state(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value_json FROM player_state ORDER BY key").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def commodity_price_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS total FROM commodity_prices").fetchone()
        return int(row["total"] if row else 0)

    def commodity_history(self, symbol: str, limit: int = 24) -> list[dict[str, Any]]:
        normalized = normalize_commodity_symbol(symbol)
        if not normalized:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    updated_at,
                    MIN(CASE WHEN buy_price > 0 AND stock > 0 THEN buy_price END) AS min_buy,
                    MAX(CASE WHEN sell_price > 0 AND demand > 0 THEN sell_price END) AS max_sell,
                    AVG(CASE WHEN buy_price > 0 AND stock > 0 THEN buy_price END) AS avg_buy,
                    AVG(CASE WHEN sell_price > 0 AND demand > 0 THEN sell_price END) AS avg_sell,
                    COUNT(DISTINCT market_id) AS stations_seen
                FROM commodity_price_history
                WHERE commodity_symbol = ?
                GROUP BY updated_at
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (normalized, max(1, min(int(limit or 24), 120))),
            ).fetchall()
        points = []
        for row in reversed(rows):
            points.append(
                {
                    "updated_at": row["updated_at"],
                    "min_buy": int(row["min_buy"]) if row["min_buy"] is not None else None,
                    "max_sell": int(row["max_sell"]) if row["max_sell"] is not None else None,
                    "avg_buy": round(float(row["avg_buy"]), 2) if row["avg_buy"] is not None else None,
                    "avg_sell": round(float(row["avg_sell"]), 2) if row["avg_sell"] is not None else None,
                    "stations_seen": int(row["stations_seen"] or 0),
                }
            )
        return points

    def find_station(self, *, system_name: str | None = None, station_name: str | None = None) -> dict[str, Any] | None:
        where = []
        params: list[Any] = []
        if system_name:
            where.append("LOWER(st.system_name) = ?")
            params.append(str(system_name).strip().lower())
        if station_name:
            where.append("LOWER(st.name) = ?")
            params.append(str(station_name).strip().lower())
        if not where:
            return None
        sql = """
            SELECT
                st.market_id,
                st.system_name,
                st.name AS station_name,
                st.type AS station_type,
                st.distance_to_arrival,
                st.landing_pad,
                st.has_market,
                st.is_planetary,
                st.is_odyssey,
                st.is_fleet_carrier,
                st.updated_at,
                sy.x,
                sy.y,
                sy.z,
                sy.requires_permit,
                sy.permit_name
            FROM stations st
            LEFT JOIN systems sy ON sy.name = st.system_name
            WHERE
        """
        sql += " AND ".join(where)
        sql += " ORDER BY st.updated_at DESC LIMIT 1"
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def system_position(self, name: str | None) -> dict[str, Any] | None:
        if not name:
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT name, x, y, z FROM systems WHERE name = ?",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    def resolve_system(self, query: str | None) -> dict[str, Any] | None:
        text = (query or "").strip()
        if not text:
            return None
        best: dict[str, Any] | None = None
        best_score = 0
        for row in self.systems_catalog():
            score, _, _ = best_variant_score(text, row.get("name"))
            if score <= best_score:
                continue
            best_score = score
            best = row
        return best if best_score >= 72 else None

    def resolve_station(self, query: str | None, *, system_name: str | None = None) -> dict[str, Any] | None:
        text = (query or "").strip()
        if not text:
            return None
        scoped_system = self.resolve_system(system_name) if system_name else None
        scoped_name = scoped_system.get("name") if scoped_system else system_name
        best: dict[str, Any] | None = None
        best_score = 0
        for row in self.stations_catalog():
            system_value = row.get("system_name")
            if scoped_name and normalize_search_text(system_value) != normalize_search_text(scoped_name):
                continue
            score, _, _ = best_variant_score(text, row.get("station_name"), f"{row.get('system_name')} {row.get('station_name')}")
            if score <= best_score:
                continue
            best_score = score
            best = row
        return best if best_score >= 72 else None

    def resolve_commodity(self, query: str | None) -> dict[str, Any] | None:
        text = (query or "").strip()
        if not text:
            return None
        symbol = normalize_commodity_symbol(text)
        commodity_rows = self.commodities_catalog()
        for row in commodity_rows:
            if row.get("symbol") == symbol:
                return {"symbol": row["symbol"], "commodity_name": row.get("name_fr") or row.get("name") or row["symbol"]}
        alias_map = {entry["lookup_key"]: entry.get("aliases", []) for entry in self.name_entries_catalog("commodity")}
        best: dict[str, Any] | None = None
        best_score = 0
        for row in commodity_rows:
            aliases = alias_map.get(row["symbol"], [])
            score, _, _ = best_variant_score(text, row.get("symbol"), row.get("name_fr"), row.get("name"), *aliases)
            if score <= best_score:
                continue
            best_score = score
            best = row
        if not best or best_score < 72:
            return None
        return {"symbol": best["symbol"], "commodity_name": best.get("name_fr") or best.get("name") or best["symbol"]}

    def upsert_system(self, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO systems (
                    name, address, x, y, z, allegiance, government, faction, faction_state, population,
                    security, economy_primary, economy_secondary, reserve, controlling_power,
                    powerplay_state, requires_permit, permit_name, access_updated_at, source, updated_at
                )
                VALUES (
                    :name, :address, :x, :y, :z, :allegiance, :government, :faction, :faction_state, :population,
                    :security, :economy_primary, :economy_secondary, :reserve, :controlling_power,
                    :powerplay_state, :requires_permit, :permit_name, :access_updated_at, :source, :updated_at
                )
                ON CONFLICT(name) DO UPDATE SET
                    address = COALESCE(excluded.address, systems.address),
                    x = COALESCE(excluded.x, systems.x),
                    y = COALESCE(excluded.y, systems.y),
                    z = COALESCE(excluded.z, systems.z),
                    allegiance = COALESCE(excluded.allegiance, systems.allegiance),
                    government = COALESCE(excluded.government, systems.government),
                    faction = COALESCE(excluded.faction, systems.faction),
                    faction_state = COALESCE(excluded.faction_state, systems.faction_state),
                    population = COALESCE(excluded.population, systems.population),
                    security = COALESCE(excluded.security, systems.security),
                    economy_primary = COALESCE(excluded.economy_primary, systems.economy_primary),
                    economy_secondary = COALESCE(excluded.economy_secondary, systems.economy_secondary),
                    reserve = COALESCE(excluded.reserve, systems.reserve),
                    controlling_power = COALESCE(excluded.controlling_power, systems.controlling_power),
                    powerplay_state = COALESCE(excluded.powerplay_state, systems.powerplay_state),
                    requires_permit = CASE
                        WHEN excluded.access_updated_at IS NOT NULL THEN excluded.requires_permit
                        ELSE systems.requires_permit
                    END,
                    permit_name = CASE
                        WHEN excluded.access_updated_at IS NOT NULL THEN excluded.permit_name
                        ELSE COALESCE(systems.permit_name, excluded.permit_name)
                    END,
                    access_updated_at = COALESCE(excluded.access_updated_at, systems.access_updated_at),
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
        self.invalidate_trade_rows_cache()

    def upsert_station(self, payload: dict[str, Any]) -> None:
        if not payload.get("market_id"):
            return
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO stations (
                    market_id, system_name, name, type, distance_to_arrival, allegiance, government,
                    economy_primary, economy_secondary, landing_pad, is_planetary, is_odyssey,
                    is_fleet_carrier, has_market, has_shipyard, has_outfitting, services_json,
                    source, updated_at
                )
                VALUES (
                    :market_id, :system_name, :name, :type, :distance_to_arrival, :allegiance, :government,
                    :economy_primary, :economy_secondary, :landing_pad, :is_planetary, :is_odyssey,
                    :is_fleet_carrier, :has_market, :has_shipyard, :has_outfitting, :services_json,
                    :source, :updated_at
                )
                ON CONFLICT(market_id) DO UPDATE SET
                    system_name = excluded.system_name,
                    name = excluded.name,
                    type = COALESCE(excluded.type, stations.type),
                    distance_to_arrival = COALESCE(excluded.distance_to_arrival, stations.distance_to_arrival),
                    allegiance = COALESCE(excluded.allegiance, stations.allegiance),
                    government = COALESCE(excluded.government, stations.government),
                    economy_primary = COALESCE(excluded.economy_primary, stations.economy_primary),
                    economy_secondary = COALESCE(excluded.economy_secondary, stations.economy_secondary),
                    landing_pad = COALESCE(excluded.landing_pad, stations.landing_pad),
                    is_planetary = CASE WHEN excluded.is_planetary = 1 THEN 1 ELSE stations.is_planetary END,
                    is_odyssey = CASE WHEN excluded.is_odyssey = 1 THEN 1 ELSE stations.is_odyssey END,
                    is_fleet_carrier = CASE WHEN excluded.is_fleet_carrier = 1 THEN 1 ELSE stations.is_fleet_carrier END,
                    has_market = excluded.has_market,
                    has_shipyard = excluded.has_shipyard,
                    has_outfitting = excluded.has_outfitting,
                    services_json = CASE WHEN excluded.services_json = '[]' THEN stations.services_json ELSE excluded.services_json END,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                payload,
            )
        self.invalidate_trade_rows_cache()

    def upsert_market_snapshot(self, snapshot: dict[str, Any], *, source: str, updated_at: str | None = None) -> int:
        station_payload = {
            "market_id": int(snapshot["market_id"]),
            "system_name": snapshot["system_name"],
            "name": snapshot["name"],
            "type": snapshot.get("type"),
            "distance_to_arrival": snapshot.get("distance_to_arrival"),
            "allegiance": snapshot.get("allegiance"),
            "government": snapshot.get("government"),
            "economy_primary": snapshot.get("economy_primary"),
            "economy_secondary": snapshot.get("economy_secondary"),
            "landing_pad": snapshot.get("landing_pad"),
            "is_planetary": 1 if snapshot.get("is_planetary") else 0,
            "is_odyssey": 1 if snapshot.get("is_odyssey") else 0,
            "is_fleet_carrier": 1 if snapshot.get("is_fleet_carrier") else 0,
            "has_market": 1,
            "has_shipyard": 1 if snapshot.get("has_shipyard") else 0,
            "has_outfitting": 1 if snapshot.get("has_outfitting") else 0,
            "services_json": json.dumps(snapshot.get("services", []), ensure_ascii=False),
            "source": source,
            "updated_at": updated_at or utc_now_iso(),
        }
        self.upsert_station(station_payload)

        rows = []
        for commodity in snapshot.get("commodities", []):
            symbol = normalize_commodity_symbol(
                commodity.get("symbol"),
                commodity.get("name_fr"),
                commodity.get("name"),
            )
            if not symbol:
                continue
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO commodities (symbol, name, name_fr, category, is_rare, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET
                        name = COALESCE(excluded.name, commodities.name),
                        name_fr = COALESCE(excluded.name_fr, commodities.name_fr),
                        category = COALESCE(excluded.category, commodities.category),
                        is_rare = CASE WHEN excluded.is_rare = 1 THEN 1 ELSE commodities.is_rare END,
                        updated_at = excluded.updated_at
                    """,
                    (
                        symbol,
                        commodity.get("name") or symbol,
                        commodity.get("name_fr"),
                        normalize_category_key(commodity.get("category")) or commodity.get("category"),
                        1 if commodity.get("is_rare") else 0,
                        utc_now_iso(),
                    ),
                )
            rows.append(
                (
                    int(snapshot["market_id"]),
                    symbol,
                    int(commodity.get("buy_price") or 0),
                    int(commodity.get("sell_price") or 0),
                    int(commodity.get("demand") or 0),
                    int(commodity.get("stock") or 0),
                    str(commodity.get("demand_bracket") or ""),
                    str(commodity.get("stock_bracket") or ""),
                    source,
                    station_payload["updated_at"],
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO commodity_prices (
                    market_id, commodity_symbol, buy_price, sell_price, demand, stock,
                    demand_bracket, stock_bracket, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_id, commodity_symbol) DO UPDATE SET
                    buy_price = excluded.buy_price,
                    sell_price = excluded.sell_price,
                    demand = excluded.demand,
                    stock = excluded.stock,
                    demand_bracket = excluded.demand_bracket,
                    stock_bracket = excluded.stock_bracket,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            conn.executemany(
                """
                INSERT OR IGNORE INTO commodity_price_history (
                    market_id, commodity_symbol, buy_price, sell_price, demand, stock, source, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (row[0], row[1], row[2], row[3], row[4], row[5], row[8], row[9])
                    for row in rows
                ],
            )
        self.invalidate_trade_rows_cache()
        return len(rows)

    def trade_rows(self) -> list[dict[str, Any]]:
        with self._cache_lock:
            if self._trade_rows_cache is not None and (time.monotonic() - self._trade_rows_cached_at) <= 1.2:
                return self._trade_rows_cache
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    cp.market_id,
                    cp.commodity_symbol,
                    cp.buy_price,
                    cp.sell_price,
                    cp.demand,
                    cp.stock,
                    cp.source AS price_source,
                    cp.updated_at AS price_updated_at,
                    st.system_name,
                    st.name AS station_name,
                    st.type AS station_type,
                    st.distance_to_arrival,
                    st.landing_pad,
                    st.has_market,
                    st.is_planetary,
                    st.is_odyssey,
                    st.is_fleet_carrier,
                    sy.x, sy.y, sy.z,
                    sy.requires_permit,
                    sy.permit_name,
                    sy.access_updated_at,
                    c.name AS commodity_name,
                    c.name_fr AS commodity_name_fr,
                    c.category
                FROM commodity_prices cp
                JOIN stations st ON st.market_id = cp.market_id
                LEFT JOIN systems sy ON sy.name = st.system_name
                JOIN commodities c ON c.symbol = cp.commodity_symbol
                """
            ).fetchall()
        materialized = [dict(row) for row in rows]
        with self._cache_lock:
            self._trade_rows_cache = materialized
            self._trade_rows_cached_at = time.monotonic()
        return materialized

    def filtered_trade_rows(
        self,
        filters: TradeFilters,
        *,
        commodity_symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        where = [
            "st.has_market = 1",
            "(cp.updated_at >= ?)",
        ]
        params: list[Any] = [
            (datetime.now(timezone.utc) - timedelta(hours=max(float(filters.max_age_hours or 0), 0.0))).isoformat(),
        ]

        allowed_pads = {
            "S": ["S", "M", "L"],
            "M": ["M", "L"],
            "L": ["L"],
        }.get(filters.min_pad_size, ["M", "L"])
        pad_placeholders = ", ".join("?" for _ in allowed_pads)
        where.append(f"COALESCE(st.landing_pad, '?') IN ({pad_placeholders})")
        params.extend(allowed_pads)

        if filters.max_station_distance_ls >= 0:
            where.append("(st.distance_to_arrival IS NULL OR st.distance_to_arrival <= ?)")
            params.append(int(filters.max_station_distance_ls))
        if not filters.include_planetary:
            where.append("COALESCE(st.is_planetary, 0) = 0")
        if not filters.include_settlements:
            where.append("NOT (COALESCE(st.is_odyssey, 0) = 1 AND LOWER(COALESCE(st.type, '')) LIKE '%settlement%')")
        if not filters.include_fleet_carriers:
            where.append("COALESCE(st.is_fleet_carrier, 0) = 0")
        if commodity_symbols:
            normalized = [normalize_commodity_symbol(symbol) for symbol in commodity_symbols]
            normalized = [symbol for symbol in normalized if symbol]
            if normalized:
                placeholders = ", ".join("?" for _ in normalized)
                where.append(f"cp.commodity_symbol IN ({placeholders})")
                params.extend(normalized)

        sql = """
            SELECT
                cp.market_id,
                cp.commodity_symbol,
                cp.buy_price,
                cp.sell_price,
                cp.demand,
                cp.stock,
                cp.source AS price_source,
                cp.updated_at AS price_updated_at,
                st.system_name,
                st.name AS station_name,
                st.type AS station_type,
                st.distance_to_arrival,
                st.landing_pad,
                st.has_market,
                st.is_planetary,
                st.is_odyssey,
                st.is_fleet_carrier,
                sy.x, sy.y, sy.z,
                sy.requires_permit,
                sy.permit_name,
                sy.access_updated_at,
                c.name AS commodity_name,
                c.name_fr AS commodity_name_fr,
                c.category
            FROM commodity_prices cp
            JOIN stations st ON st.market_id = cp.market_id
            LEFT JOIN systems sy ON sy.name = st.system_name
            JOIN commodities c ON c.symbol = cp.commodity_symbol
            WHERE
        """
        sql += " AND ".join(where)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def current_market(self) -> dict[str, Any]:
        market_id = self.get_state("current_market_id")
        if not market_id:
            return {"station_name": None, "exports": [], "imports": []}
        with self.connect() as conn:
            station = conn.execute(
                "SELECT name, system_name, updated_at FROM stations WHERE market_id = ?",
                (market_id,),
            ).fetchone()
            exports = conn.execute(
                """
                SELECT COALESCE(c.name_fr, c.name) AS commodity_name, cp.buy_price, cp.stock
                FROM commodity_prices cp
                JOIN commodities c ON c.symbol = cp.commodity_symbol
                WHERE cp.market_id = ? AND cp.buy_price > 0 AND cp.stock > 0
                ORDER BY cp.buy_price ASC, cp.stock DESC
                LIMIT 10
                """,
                (market_id,),
            ).fetchall()
            imports = conn.execute(
                """
                SELECT COALESCE(c.name_fr, c.name) AS commodity_name, cp.sell_price, cp.demand
                FROM commodity_prices cp
                JOIN commodities c ON c.symbol = cp.commodity_symbol
                WHERE cp.market_id = ? AND cp.sell_price > 0 AND cp.demand > 0
                ORDER BY cp.sell_price DESC, cp.demand DESC
                LIMIT 10
                """,
                (market_id,),
            ).fetchall()
        return {
            "station_name": station["name"] if station else None,
            "system_name": station["system_name"] if station else None,
            "updated_at": station["updated_at"] if station else None,
            "freshness_hours": age_hours(station["updated_at"]) if station else None,
            "exports": [dict(row) for row in exports],
            "imports": [dict(row) for row in imports],
        }

    def knowledge(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_entries ORDER BY priority DESC, title ASC"
            ).fetchall()
        return [
            {
                "title": row["title"],
                "category": row["category"],
                "summary": row["summary"],
                "url": row["url"],
                "source_name": row["source_name"],
                "languages": json.loads(row["languages_json"]),
                "priority": row["priority"],
            }
            for row in rows
        ]


repo = Repository(DB_PATH)
repo.seed_knowledge()


def trader_memory_defaults() -> dict[str, Any]:
    return {
        "recent": {
            "commodity": [],
            "system": [],
            "station": [],
            "module": [],
            "query": [],
        },
        "favorites": {
            "commodity": [],
            "system": [],
            "station": [],
            "module": [],
        },
        "missions": [],
        "ship_profiles": [],
    }


def _normalize_memory_items(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("id") or "").strip()
        if not entity_id:
            continue
        normalized.append(
            {
                "id": entity_id,
                "label": str(raw.get("label") or entity_id),
                "secondary": raw.get("secondary"),
                "updated_at": raw.get("updated_at") or utc_now_iso(),
                "count": max(1, int(raw.get("count") or 1)),
                "extra": raw.get("extra") if isinstance(raw.get("extra"), dict) else {},
            }
        )
    return normalized[:TRADER_MEMORY_LIMIT]


def get_trader_memory() -> dict[str, Any]:
    stored = repo.get_state("trader_memory", {})
    memory = trader_memory_defaults()
    if not isinstance(stored, dict):
        return memory
    for section in ("recent", "favorites"):
        current = stored.get(section, {})
        if not isinstance(current, dict):
            continue
        for kind in memory[section]:
            memory[section][kind] = _normalize_memory_items(current.get(kind, []))
    memory["missions"] = _normalize_memory_items(stored.get("missions", []))
    memory["ship_profiles"] = _normalize_memory_items(stored.get("ship_profiles", []))
    return memory


def save_trader_memory(memory: dict[str, Any]) -> dict[str, Any]:
    repo.set_state("trader_memory", memory)
    return memory


def _memory_upsert(items: list[dict[str, Any]], entity_id: str, label: str, *, secondary: str | None = None, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    normalized_id = str(entity_id).strip()
    if not normalized_id:
        return items
    now = utc_now_iso()
    updated: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for item in items:
        if str(item.get("id") or "").strip().lower() == normalized_id.lower():
            previous = item
            continue
        updated.append(item)
    updated.insert(
        0,
        {
            "id": normalized_id,
            "label": label or normalized_id,
            "secondary": secondary,
            "updated_at": now,
            "count": max(1, int((previous or {}).get("count") or 0) + 1),
            "extra": extra or (previous or {}).get("extra") or {},
        },
    )
    return updated[:TRADER_MEMORY_LIMIT]


def remember_trader_selection(
    kind: Literal["commodity", "system", "station", "module", "query"],
    entity_id: str,
    label: str,
    *,
    secondary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = get_trader_memory()
    if kind in memory["recent"]:
        memory["recent"][kind] = _memory_upsert(memory["recent"][kind], entity_id, label, secondary=secondary, extra=extra)
    return save_trader_memory(memory)


def toggle_trader_favorite(
    kind: Literal["commodity", "system", "station", "module"],
    entity_id: str,
    label: str,
    *,
    secondary: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = get_trader_memory()
    items = list(memory["favorites"].get(kind, []))
    normalized_id = str(entity_id).strip().lower()
    exists = any(str(item.get("id") or "").strip().lower() == normalized_id for item in items)
    if exists:
        items = [item for item in items if str(item.get("id") or "").strip().lower() != normalized_id]
    else:
        items = _memory_upsert(items, entity_id, label, secondary=secondary, extra=extra)
    memory["favorites"][kind] = items[:TRADER_MEMORY_LIMIT]
    save_trader_memory(memory)
    return trader_memory_snapshot()


def remember_trader_query(query: str) -> dict[str, Any]:
    clean = str(query or "").strip()
    if not clean:
        return get_trader_memory()
    return remember_trader_selection("query", clean, clean)


def remember_mission_plan(
    commodity_query: str,
    quantity: int,
    *,
    commodity_name: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
) -> dict[str, Any]:
    memory = get_trader_memory()
    label = commodity_name or commodity_query or "Mission"
    target_label = " / ".join(part for part in [target_system, target_station] if part)
    entry_id = "|".join(
        [
            normalize_lookup_key(commodity_query),
            str(max(1, int(quantity or 1))),
            normalize_lookup_key(target_system),
            normalize_lookup_key(target_station),
        ]
    )
    extra = {
        "commodity_query": commodity_query,
        "commodity_name": commodity_name,
        "quantity": max(1, int(quantity or 1)),
        "target_system": target_system,
        "target_station": target_station,
    }
    memory["missions"] = _memory_upsert(
        memory["missions"],
        entry_id,
        label,
        secondary=target_label or None,
        extra=extra,
    )
    save_trader_memory(memory)
    return trader_memory_snapshot()


def remember_ship_profile(player: dict[str, Any]) -> dict[str, Any]:
    ship_code = normalize_lookup_key(player.get("current_ship_code") or player.get("current_ship_name"))
    if not ship_code:
        return trader_memory_snapshot()
    cargo_capacity = int(player.get("cargo_capacity_override") or player.get("cargo_capacity") or 0)
    jump_range = float(player.get("jump_range_override") or player.get("jump_range") or 0.0)
    preferred_pad_size = str(player.get("preferred_pad_size") or repo.get_state("preferred_pad_size", "M"))
    label = player.get("current_ship_name") or player.get("current_ship_code") or ship_code
    extra = {
        "ship_code": ship_code,
        "cargo_capacity": cargo_capacity,
        "jump_range": jump_range,
        "preferred_pad_size": preferred_pad_size,
        "system_name": player.get("current_system"),
    }
    memory = get_trader_memory()
    memory["ship_profiles"] = _memory_upsert(memory["ship_profiles"], ship_code, label, secondary=player.get("current_system"), extra=extra)[:6]
    save_trader_memory(memory)
    return trader_memory_snapshot()


def trader_memory_snapshot() -> dict[str, Any]:
    memory = get_trader_memory()
    return {
        "favorites": memory["favorites"],
        "recents": memory["recent"],
        "last_missions": memory["missions"][:6],
        "last_commodities": memory["recent"]["commodity"][:6],
        "last_systems": memory["recent"]["system"][:6],
        "last_stations": memory["recent"]["station"][:6],
        "ship_profiles": memory["ship_profiles"][:4],
    }


def memory_flags(memory: dict[str, Any], kind: str, entity_id: str) -> tuple[bool, bool, int]:
    normalized_id = str(entity_id or "").strip().lower()
    favorite_items = memory.get("favorites", {}).get(kind, [])
    recent_items = memory.get("recent", {}).get(kind, [])
    favorite = any(str(item.get("id") or "").strip().lower() == normalized_id for item in favorite_items)
    recent = False
    usage_count = 0
    for item in recent_items:
        if str(item.get("id") or "").strip().lower() != normalized_id:
            continue
        recent = True
        usage_count = int(item.get("count") or 0)
        break
    return favorite, recent, usage_count


def localised(event: dict[str, Any], key: str) -> Any:
    return event.get(f"{key}_Localised") or event.get(key)


class NameLibraryService:
    def __init__(self, journal_dir: Path, repository: Repository):
        self.journal_dir = journal_dir
        self.repo = repository
        self.seen_modules: set[str] = set()
        self.seen_ships: set[str] = set()

    def refresh(self) -> dict[str, Any]:
        commodity_stats = self.repo.normalize_commodity_catalog()
        self.seen_modules = set()
        self.seen_ships = set()
        entries: list[dict[str, Any]] = []
        entries.extend(self._collect_market_entries())
        entries.extend(self._collect_shipyard_entries())
        entries.extend(self._collect_journal_entries())
        entries.extend(self._collect_runtime_entries(entries))
        self.repo.replace_name_library(entries)
        now = utc_now_iso()
        self.repo.set_state("name_library_last_refresh", now)
        summary = self.repo.name_library_summary()
        return {
            "commodity_catalog": commodity_stats,
            "entries_total": summary["total"],
            "entries_exact": summary["exact_total"],
            "entries_derived": summary["derived_total"],
            "module_codes_seen": len(self.seen_modules),
            "ship_codes_seen": len(self.seen_ships),
            "updated_at": now,
        }

    def _entry(
        self,
        entry_type: str,
        lookup_key: str,
        name_fr: str,
        *,
        name: str | None = None,
        source: str,
        is_exact: bool,
        confidence: int,
        aliases: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "entry_type": entry_type,
            "lookup_key": lookup_key,
            "name": name,
            "name_fr": name_fr,
            "source": source,
            "is_exact": is_exact,
            "confidence": confidence,
            "aliases": aliases or [],
            "extra": extra or {},
            "updated_at": utc_now_iso(),
        }

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None

    def _remember_module(self, value: Any) -> None:
        key = normalize_module_key(value)
        if key.startswith("int_") or key.startswith("hpt_"):
            self.seen_modules.add(key)

    def _remember_ship(self, value: Any) -> None:
        key = normalize_ship_code(value)
        if key:
            self.seen_ships.add(key)

    def _classify_pair(self, raw: str, base_key: str, node: dict[str, Any]) -> tuple[str, str, list[str]] | None:
        raw_text = str(raw or "").strip()
        if not raw_text:
            return None
        if base_key in {"Message", "From", "PilotName", "CurrentRankName", "OldRankName", "NewRankName", "Effect"}:
            return None
        lowered = raw_text.lower()
        aliases = [raw_text]
        if lowered.startswith("$market_category_"):
            return ("commodity_category", normalize_category_key(raw_text), aliases)
        if lowered.startswith("$int_") or lowered.startswith("$hpt_"):
            key = normalize_module_key(raw_text)
            self._remember_module(key)
            return ("module", key, aliases)
        if lowered.startswith("int_") or lowered.startswith("hpt_"):
            key = normalize_module_key(raw_text)
            self._remember_module(key)
            return ("module", key, aliases)
        if base_key in {"Ship", "ShipType", "SRVType"}:
            key = normalize_ship_code(raw_text)
            self._remember_ship(key)
            return ("ship", key, aliases)
        if "economy" in base_key.lower():
            return ("economy", normalize_lookup_key(raw_text), aliases)
        if "government" in base_key.lower():
            return ("government", normalize_lookup_key(raw_text), aliases)
        if "security" in base_key.lower():
            return ("security", normalize_lookup_key(raw_text), aliases)
        if base_key == "Name" and str(node.get("Category") or "") in {"Raw", "Manufactured", "Encoded"}:
            return ("material", normalize_lookup_key(raw_text), aliases)
        if lowered.startswith("$") and lowered.endswith("_name;"):
            return ("commodity", normalize_commodity_symbol(raw_text), aliases)
        return ("term", normalize_lookup_key(raw_text), aliases)

    def _collect_market_entries(self) -> list[dict[str, Any]]:
        data = self._read_json(self.journal_dir / "Market.json") or {}
        items = data.get("Items") or data.get("Commodities") or data.get("commodities") or []
        entries: list[dict[str, Any]] = []
        for item in items:
            raw_name = item.get("Name") or item.get("name")
            name_fr = item.get("Name_Localised") or item.get("name")
            if raw_name and name_fr:
                key = normalize_commodity_symbol(raw_name, name_fr)
                entries.append(
                    self._entry(
                        "commodity",
                        key,
                        str(name_fr),
                        name=str(raw_name),
                        source="frontier_market",
                        is_exact=True,
                        confidence=100,
                        aliases=[str(raw_name)],
                    )
                )
            raw_category = item.get("Category") or item.get("category")
            category_fr = item.get("Category_Localised")
            if raw_category and category_fr:
                entries.append(
                    self._entry(
                        "commodity_category",
                        normalize_category_key(raw_category),
                        str(category_fr),
                        name=str(raw_category),
                        source="frontier_market",
                        is_exact=True,
                        confidence=100,
                        aliases=[str(raw_category)],
                    )
                )
        return entries

    def _collect_shipyard_entries(self) -> list[dict[str, Any]]:
        data = self._read_json(self.journal_dir / "Shipyard.json") or {}
        entries: list[dict[str, Any]] = []
        for item in data.get("PriceList", []):
            ship_code = item.get("ShipType")
            ship_name = item.get("ShipType_Localised")
            if not ship_code or not ship_name:
                continue
            normalized = normalize_ship_code(ship_code)
            self._remember_ship(normalized)
            entries.append(
                self._entry(
                    "ship",
                    normalized,
                    str(ship_name),
                    name=str(ship_code),
                    source="frontier_shipyard",
                    is_exact=True,
                    confidence=100,
                    aliases=[str(ship_code)],
                )
            )
        return entries

    def _collect_journal_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for path in sorted(self.journal_dir.glob("Journal.*.log")):
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if "Localised" not in line and "\"Item\":\"" not in line and "\"Ship\":\"" not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._walk_event(event, entries)
        return entries

    def _walk_event(self, node: Any, entries: list[dict[str, Any]]) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("Item"), str):
                self._remember_module(node["Item"])
            for base_key in ("Ship", "ShipType", "SRVType"):
                if isinstance(node.get(base_key), str):
                    self._remember_ship(node[base_key])
            for key, value in node.items():
                if key.endswith("_Localised") and isinstance(value, str):
                    base_key = key[:-10]
                    raw_value = node.get(base_key)
                    if isinstance(raw_value, str):
                        classified = self._classify_pair(raw_value, base_key, node)
                        if classified:
                            entry_type, lookup_key, aliases = classified
                            if lookup_key:
                                entries.append(
                                    self._entry(
                                        entry_type,
                                        lookup_key,
                                        value,
                                        name=raw_value,
                                        source="frontier_journal",
                                        is_exact=True,
                                        confidence=100,
                                        aliases=aliases,
                                    )
                                )
                self._walk_event(value, entries)
        elif isinstance(node, list):
            for item in node:
                self._walk_event(item, entries)

    def _collect_runtime_entries(self, existing_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        exact_module_map: dict[str, str] = {}
        for entry in existing_entries:
            if entry["entry_type"] != "module" or not entry["is_exact"]:
                continue
            exact_module_map[normalize_module_key(entry["lookup_key"])] = entry["name_fr"]
            exact_module_map[module_family_key(entry["lookup_key"])] = entry["name_fr"]

        for payload in (
            self._read_json(self.journal_dir / "Outfitting.json") or {},
            self._read_json(self.journal_dir / "ModulesInfo.json") or {},
        ):
            for item in payload.get("Items", []):
                self._remember_module(item.get("Name"))
            for item in payload.get("Modules", []):
                self._remember_module(item.get("Item"))

        entries: list[dict[str, Any]] = []
        exact_module_keys = {
            normalize_module_key(entry["lookup_key"])
            for entry in existing_entries
            if entry["entry_type"] == "module"
        }
        for module_code in sorted(self.seen_modules):
            if module_code in exact_module_keys:
                continue
            derived_name = derive_module_name_fr(module_code, exact_module_map)
            if not derived_name:
                continue
            family = module_family_key(module_code)
            entries.append(
                self._entry(
                    "module",
                    module_code,
                    derived_name,
                    name=module_code,
                    source="frontier_family" if family in exact_module_map else "catalogue_derive",
                    is_exact=False,
                    confidence=90 if family in exact_module_map else 72,
                    aliases=[module_code],
                )
            )

        exact_ship_keys = {
            normalize_ship_code(entry["lookup_key"])
            for entry in existing_entries
            if entry["entry_type"] == "ship"
        }
        for ship_code in sorted(self.seen_ships):
            if ship_code in exact_ship_keys:
                continue
            entries.append(
                self._entry(
                    "ship",
                    ship_code,
                    format_ship_name(ship_code),
                    name=ship_code,
                    source="catalogue_derive",
                    is_exact=False,
                    confidence=70,
                    aliases=[ship_code],
                )
            )
        return entries


class JournalImportService:
    def __init__(self, journal_dir: Path, repository: Repository):
        self.journal_dir = journal_dir
        self.repo = repository

    def import_all(self) -> dict[str, Any]:
        if not self.journal_dir.exists():
            raise FileNotFoundError(f"Dossier des journaux introuvable: {self.journal_dir}")

        stats = {
            "journal_files": 0,
            "events": 0,
            "systems_upserted": 0,
            "stations_upserted": 0,
            "market_rows_upserted": 0,
            "status_loaded": False,
            "cargo_loaded": False,
            "market_loaded": False,
            "last_event_at": None,
        }
        journal_files = sorted(self.journal_dir.glob("Journal.*.log"))
        stats["journal_files"] = len(journal_files)

        for path in journal_files:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    stats["events"] += 1
                    self._handle_event(event, stats)

        stats["status_loaded"] = self._load_status()
        stats["cargo_loaded"] = self._load_cargo()
        rows = self._load_market()
        if rows:
            stats["market_loaded"] = True
            stats["market_rows_upserted"] += rows

        if stats.get("last_event_at"):
            self.repo.set_state("source_local_last_event", stats["last_event_at"])
        self.repo.set_state("source_journal_last_import", utc_now_iso())
        return stats

    def _handle_event(self, event: dict[str, Any], stats: dict[str, Any]) -> None:
        kind = event.get("event")
        timestamp = event.get("timestamp")
        if timestamp:
            stats["last_event_at"] = timestamp

        if kind == "Fileheader":
            self.repo.set_states(
                {
                    "journal_language": event.get("language"),
                    "odyssey_enabled": bool(event.get("Odyssey")),
                    "game_version": event.get("gameversion"),
                    "game_build": event.get("build"),
                }
            )
            return

        if kind == "Commander":
            self.repo.set_states(
                {
                    "commander_name": event.get("Name"),
                    "commander_fid": event.get("FID"),
                }
            )
            return

        if kind == "LoadGame":
            self.repo.set_states(
                {
                    "commander_name": event.get("Commander"),
                    "credits": event.get("Credits"),
                    "loan": event.get("Loan"),
                    "current_ship_code": event.get("Ship"),
                    "current_ship_name": localised(event, "Ship"),
                    "current_ship_id": event.get("ShipID"),
                    "game_mode": event.get("GameMode"),
                }
            )
            return

        if kind in {"Rank", "Progress", "Reputation", "Statistics", "Powerplay", "EngineerProgress"}:
            self.repo.set_state(kind.lower(), event)
            return

        if kind == "Loadout":
            self.repo.set_states(
                {
                    "current_ship_code": event.get("Ship"),
                    "current_ship_id": event.get("ShipID"),
                    "ship_name": (event.get("ShipName") or "").strip(),
                    "ship_ident": (event.get("ShipIdent") or "").strip(),
                    "cargo_capacity": int(event.get("CargoCapacity") or 0),
                    "jump_range": round(float(event.get("MaxJumpRange") or 0), 2),
                    "rebuy": event.get("Rebuy"),
                }
            )
            return

        if kind == "Cargo":
            self.repo.set_states(
                {
                    "cargo_count": int(event.get("Count") or 0),
                    "cargo_inventory": event.get("Inventory", []),
                }
            )
            return

        if kind in {"Location", "Docked", "FSDJump"}:
            self._upsert_system_from_event(event, timestamp, stats)
            if kind != "FSDJump":
                self._upsert_station_from_event(event, timestamp, stats)
            self.repo.set_states(
                {
                    "current_system": event.get("StarSystem"),
                    "current_system_address": event.get("SystemAddress"),
                    "current_station": event.get("StationName") if kind != "FSDJump" else None,
                    "current_market_id": event.get("MarketID") if kind != "FSDJump" else None,
                    "current_body_name": event.get("StationName") if kind != "FSDJump" else event.get("StarSystem"),
                    "docking_target_name": None if kind != "FSDJump" else None,
                    "current_location_at": timestamp,
                }
            )
            return

        if kind in {"SupercruiseEntry", "StartJump"}:
            self.repo.set_states(
                {
                    "current_system": event.get("StarSystem") or self.repo.get_state("current_system"),
                    "current_station": None,
                    "current_market_id": None,
                    "current_location_at": timestamp,
                }
            )
            return

        if kind == "SupercruiseExit":
            self.repo.set_states(
                {
                    "current_system": event.get("StarSystem") or self.repo.get_state("current_system"),
                    "current_system_address": event.get("SystemAddress") or self.repo.get_state("current_system_address"),
                    "current_body_name": event.get("Body"),
                    "current_location_at": timestamp,
                }
            )
            return

        if kind in {"DockingRequested", "DockingGranted"}:
            self.repo.set_states(
                {
                    "current_station": event.get("StationName") or self.repo.get_state("current_station"),
                    "current_market_id": event.get("MarketID") or self.repo.get_state("current_market_id"),
                    "current_body_name": event.get("StationName") or self.repo.get_state("current_body_name"),
                    "docking_target_name": event.get("StationName") or self.repo.get_state("docking_target_name"),
                    "current_location_at": timestamp,
                }
            )
            return

        if kind == "Undocked":
            self.repo.set_states(
                {
                    "current_station": None,
                    "current_market_id": None,
                    "docking_target_name": event.get("StationName") or self.repo.get_state("docking_target_name"),
                    "current_body_name": event.get("StationName") or self.repo.get_state("current_body_name"),
                    "current_location_at": timestamp,
                }
            )
            return

        if kind == "ApproachSettlement":
            self.repo.set_states(
                {
                    "current_station": event.get("Name"),
                    "current_body_name": event.get("BodyName"),
                    "current_location_at": timestamp,
                }
            )
            return

    def _upsert_system_from_event(self, event: dict[str, Any], timestamp: str | None, stats: dict[str, Any]) -> None:
        name = event.get("StarSystem")
        if not name:
            return
        coords = event.get("StarPos") or [None, None, None]
        self.repo.upsert_system(
            {
                "name": name,
                "address": event.get("SystemAddress"),
                "x": coords[0] if len(coords) > 0 else None,
                "y": coords[1] if len(coords) > 1 else None,
                "z": coords[2] if len(coords) > 2 else None,
                "allegiance": event.get("SystemAllegiance"),
                "government": localised(event, "SystemGovernment"),
                "faction": (event.get("SystemFaction") or {}).get("Name"),
                "faction_state": (event.get("SystemFaction") or {}).get("FactionState"),
                "population": event.get("Population"),
                "security": localised(event, "SystemSecurity"),
                "economy_primary": localised(event, "SystemEconomy"),
                "economy_secondary": localised(event, "SystemSecondEconomy"),
                "controlling_power": event.get("ControllingPower"),
                "powerplay_state": event.get("PowerplayState"),
                "requires_permit": 0,
                "permit_name": None,
                "access_updated_at": None,
                "reserve": None,
                "source": "journal",
                "updated_at": timestamp or utc_now_iso(),
            }
        )
        stats["systems_upserted"] += 1

    def _upsert_station_from_event(self, event: dict[str, Any], timestamp: str | None, stats: dict[str, Any]) -> None:
        if not event.get("MarketID") or not event.get("StationName") or not event.get("StarSystem"):
            return
        station_type = event.get("StationType")
        services = event.get("StationServices") or []
        self.repo.upsert_station(
            {
                "market_id": int(event["MarketID"]),
                "system_name": event["StarSystem"],
                "name": event["StationName"],
                "type": station_type,
                "distance_to_arrival": event.get("DistFromStarLS"),
                "allegiance": event.get("SystemAllegiance"),
                "government": localised(event, "StationGovernment"),
                "economy_primary": localised(event, "StationEconomy"),
                "economy_secondary": None,
                "landing_pad": infer_pad_size(station_type),
                "is_planetary": 1 if is_planetary(station_type) else 0,
                "is_odyssey": 1 if is_odyssey_station(station_type) else 0,
                "is_fleet_carrier": 1 if is_fleet_carrier(station_type) else 0,
                "has_market": 1,
                "has_shipyard": 1 if "shipyard" in services else 0,
                "has_outfitting": 1 if "outfitting" in services else 0,
                "services_json": json.dumps(services, ensure_ascii=False),
                "source": "journal",
                "updated_at": timestamp or utc_now_iso(),
            }
        )
        stats["stations_upserted"] += 1

    def _load_status(self) -> bool:
        path = self.journal_dir / "Status.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return False
        if data.get("event") != "Status":
            return False
        self.repo.set_states(
            {
                "balance": data.get("Balance"),
                "cargo_count": int(data.get("Cargo") or 0),
                "legal_state": data.get("LegalState"),
                "destination": data.get("Destination"),
                "destination_name": (data.get("Destination") or {}).get("Name"),
                "status_timestamp": data.get("timestamp"),
                "status_flags": decode_status_flags(data.get("Flags"), data.get("Flags2")),
                "status_flags_raw": int(data.get("Flags") or 0),
                "status_flags2_raw": int(data.get("Flags2") or 0),
                "latitude": data.get("Latitude"),
                "longitude": data.get("Longitude"),
                "altitude": data.get("Altitude"),
                "heading": data.get("Heading"),
                "current_body_name": data.get("BodyName") or self.repo.get_state("current_body_name"),
            }
        )
        return True

    def _load_cargo(self) -> bool:
        path = self.journal_dir / "Cargo.json"
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return False
        if data.get("event") != "Cargo":
            return False
        self.repo.set_states(
            {
                "cargo_count": int(data.get("Count") or 0),
                "cargo_inventory": data.get("Inventory") or [],
            }
        )
        return True

    def _load_market(self) -> int:
        path = self.journal_dir / "Market.json"
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            return 0
        items = data.get("Items") or data.get("Commodities") or data.get("commodities")
        if not isinstance(items, list):
            return 0
        file_timestamp = data.get("timestamp")
        if not market_file_is_fresh(path, file_timestamp):
            return 0
        system_name = data.get("StarSystem") or self.repo.get_state("current_system")
        station_name = data.get("StationName") or self.repo.get_state("current_station")
        market_id = data.get("MarketID") or self.repo.get_state("current_market_id")
        current_market_id = self.repo.get_state("current_market_id")
        if current_market_id and market_id and int(current_market_id) != int(market_id):
            return 0
        station_type = data.get("StationType")
        if not system_name or not station_name or not market_id:
            return 0
        commodities = []
        for item in items:
            symbol = str(item.get("Name") or item.get("name") or "").strip().lower()
            if not symbol:
                continue
            commodities.append(
                {
                    "symbol": symbol,
                    "name": item.get("Name_Localised") or item.get("Name") or item.get("name") or symbol,
                    "name_fr": item.get("Name_Localised"),
                    "category": item.get("Category") or item.get("category"),
                    "buy_price": item.get("BuyPrice") or item.get("buyPrice") or 0,
                    "sell_price": item.get("SellPrice") or item.get("sellPrice") or 0,
                    "demand": item.get("Demand") or item.get("demand") or 0,
                    "stock": item.get("Stock") or item.get("stock") or 0,
                    "demand_bracket": item.get("DemandBracket") or item.get("demandBracket") or "",
                    "stock_bracket": item.get("StockBracket") or item.get("stockBracket") or "",
                }
            )
        return self.repo.upsert_market_snapshot(
            {
                "market_id": int(market_id),
                "system_name": system_name,
                "name": station_name,
                "type": station_type,
                "distance_to_arrival": None,
                "allegiance": None,
                "government": None,
                "economy_primary": None,
                "economy_secondary": None,
                "landing_pad": infer_pad_size(station_type),
                "is_planetary": is_planetary(station_type),
                "is_odyssey": is_odyssey_station(station_type),
                "is_fleet_carrier": is_fleet_carrier(station_type),
                "commodities": commodities,
                "services": [],
            },
            source="journal_market",
            updated_at=file_timestamp or utc_now_iso(),
        )


class LocalRealtimeSyncService:
    def __init__(
        self,
        journal_dir: Path,
        journal_service: JournalImportService,
        repository: Repository,
        spansh: "SpanshClient",
        edsm: "EDSMClient",
        poll_seconds: float = LOCAL_SYNC_POLL_SECONDS,
    ):
        self.journal_dir = journal_dir
        self.journal_service = journal_service
        self.repo = repository
        self.spansh = spansh
        self.edsm = edsm
        self.poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._journal_offsets: dict[str, int] = {}
        self._file_mtimes: dict[str, float] = {}
        self._last_remote_refresh_by_market: dict[int, float] = {}
        self._remote_refresh_task: asyncio.Task[None] | None = None
        self._status = {
            "running": False,
            "poll_seconds": poll_seconds,
            "last_poll_at": None,
            "last_error": None,
            "last_event_at": None,
        }

    def bootstrap(self) -> dict[str, Any]:
        stats = {
            "journal_files": 0,
            "events": 0,
            "journal_events": 0,
            "systems_upserted": 0,
            "stations_upserted": 0,
            "status_loaded": False,
            "cargo_loaded": False,
            "market_rows_upserted": 0,
            "market_loaded": False,
            "last_event_at": self.repo.get_state("source_local_last_event"),
        }
        if not self.journal_dir.exists():
            return stats

        latest_journal = self._latest_journal_file()
        if latest_journal is not None:
            stats["journal_files"] = len(list(self.journal_dir.glob("Journal.*.log")))
            recent_lines = self._read_recent_journal_lines(latest_journal)
            for line in recent_lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stats["events"] += 1
                stats["journal_events"] += 1
                self.journal_service._handle_event(event, stats)

        stats["status_loaded"] = self.journal_service._load_status()
        stats["cargo_loaded"] = self.journal_service._load_cargo()
        market_rows = self.journal_service._load_market()
        if market_rows:
            stats["market_loaded"] = True
            stats["market_rows_upserted"] = int(market_rows)

        self._prime_offsets_and_mtimes()
        now = utc_now_iso()
        self.repo.set_states(
            {
                "source_local_last_poll": now,
                "source_local_sync_stats": stats,
            }
        )
        if stats.get("last_event_at"):
            self.repo.set_state("source_local_last_event", stats["last_event_at"])
        self._status["last_poll_at"] = now
        self._status["last_error"] = None
        self._status["last_event_at"] = stats.get("last_event_at")
        return stats

    async def start(self) -> dict[str, Any]:
        if self._task and not self._task.done():
            return self.status()
        self._stop_event = asyncio.Event()
        self._status["running"] = True
        self._task = asyncio.create_task(self._run(), name="elite-local-sync")
        return self.status()

    async def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self._task:
            await self._task
        if self._remote_refresh_task and not self._remote_refresh_task.done():
            await self._remote_refresh_task
        self._status["running"] = False
        return self.status()

    def status(self) -> dict[str, Any]:
        result = dict(self._status)
        result["running"] = bool(self._task and not self._task.done())
        result["last_event_age_min"] = age_minutes(result.get("last_event_at"))
        result["last_poll_age_min"] = age_minutes(result.get("last_poll_at"))
        return result

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                started = time.perf_counter()
                try:
                    stats = await asyncio.to_thread(self.poll_once)
                    self._status["last_poll_at"] = utc_now_iso()
                    self._status["last_error"] = None
                    if stats.get("last_event_at"):
                        self._status["last_event_at"] = stats["last_event_at"]
                    await self._maybe_schedule_remote_refresh()
                except Exception as exc:
                    logger.exception("Local realtime sync failed")
                    self._status["last_error"] = str(exc)
                wait_seconds = max(0.2, self.poll_seconds - (time.perf_counter() - started))
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._status["running"] = False

    def poll_once(self) -> dict[str, Any]:
        stats = {
            "journal_files": 0,
            "events": 0,
            "journal_events": 0,
            "systems_upserted": 0,
            "stations_upserted": 0,
            "status_loaded": False,
            "cargo_loaded": False,
            "market_rows_upserted": 0,
            "market_loaded": False,
            "last_event_at": self.repo.get_state("source_local_last_event"),
        }
        if not self.journal_dir.exists():
            return stats

        stats["journal_events"] += self._poll_journals(stats)
        stats["status_loaded"] = self._poll_state_file("Status.json", self.journal_service._load_status)
        stats["cargo_loaded"] = self._poll_state_file("Cargo.json", self.journal_service._load_cargo)
        market_rows = self._poll_state_file("Market.json", self.journal_service._load_market)
        if market_rows:
            stats["market_loaded"] = True
            stats["market_rows_upserted"] = int(market_rows)

        now = utc_now_iso()
        self.repo.set_states(
            {
                "source_local_last_poll": now,
                "source_local_sync_stats": stats,
            }
        )
        if stats.get("last_event_at"):
            self.repo.set_state("source_local_last_event", stats["last_event_at"])
        return stats

    def _latest_journal_file(self) -> Path | None:
        journal_files = sorted(
            self.journal_dir.glob("Journal.*.log"),
            key=lambda path: path.stat().st_mtime,
        )
        return journal_files[-1] if journal_files else None

    def _read_recent_journal_lines(self, path: Path) -> list[str]:
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                read_size = min(size, BOOTSTRAP_JOURNAL_TAIL_BYTES)
                handle.seek(max(0, size - read_size))
                chunk = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        return chunk.splitlines()[-BOOTSTRAP_JOURNAL_MAX_LINES:]

    def _prime_offsets_and_mtimes(self) -> None:
        journal_files = sorted(
            self.journal_dir.glob("Journal.*.log"),
            key=lambda path: path.stat().st_mtime,
        )
        for path in journal_files[-3:]:
            try:
                self._journal_offsets[str(path)] = path.stat().st_size
            except OSError:
                continue
        for filename in ("Status.json", "Cargo.json", "Market.json"):
            path = self.journal_dir / filename
            if not path.exists():
                continue
            try:
                self._file_mtimes[filename] = path.stat().st_mtime
            except OSError:
                continue

    def _poll_journals(self, stats: dict[str, Any]) -> int:
        journal_files = sorted(
            self.journal_dir.glob("Journal.*.log"),
            key=lambda path: path.stat().st_mtime,
        )
        stats["journal_files"] = len(journal_files)
        relevant = journal_files[-3:]
        events = 0
        for path in relevant:
            key = str(path)
            size = path.stat().st_size
            offset = self._journal_offsets.get(key, 0)
            if size < offset:
                offset = 0
            if size == offset:
                continue
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    events += 1
                    stats["events"] += 1
                    self.journal_service._handle_event(event, stats)
                self._journal_offsets[key] = handle.tell()
        return events

    def _poll_state_file(self, filename: str, loader: Any) -> Any:
        path = self.journal_dir / filename
        if not path.exists():
            return False
        current_mtime = path.stat().st_mtime
        previous_mtime = self._file_mtimes.get(filename)
        if previous_mtime is not None and current_mtime <= previous_mtime:
            return False
        self._file_mtimes[filename] = current_mtime
        return loader()

    async def _maybe_schedule_remote_refresh(self) -> None:
        market_id = self.repo.get_state("current_market_id")
        if not market_id:
            return
        market_id = int(market_id)
        if self._remote_refresh_task and not self._remote_refresh_task.done():
            return
        last_run = self._last_remote_refresh_by_market.get(market_id, 0)
        if time.time() - last_run < REMOTE_MARKET_REFRESH_SECONDS:
            return
        self._last_remote_refresh_by_market[market_id] = time.time()
        self._remote_refresh_task = asyncio.create_task(self._refresh_remote_market(market_id))

    async def _refresh_remote_market(self, market_id: int) -> None:
        def _run() -> None:
            try:
                self.spansh.refresh_station(market_id)
            except Exception as exc:
                logger.warning("Spansh refresh failed for %s: %s", market_id, exc)
            try:
                self.edsm.refresh_market(market_id)
            except Exception as exc:
                logger.warning("EDSM refresh failed for %s: %s", market_id, exc)

        await asyncio.to_thread(_run)


class ArdentClient:
    def __init__(self, repository: Repository):
        self.repo = repository

    async def _get(self, path: str) -> Any:
        async with httpx.AsyncClient(base_url=ARDENT_API_BASE, timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

    async def sync_region(self, center_system: str, max_distance: int, max_days_ago: int, max_systems: int) -> dict[str, Any]:
        sync_errors: list[str] = []
        try:
            nearby = await self._get(f"/system/name/{center_system}/nearby?maxDistance={max_distance}")
        except Exception as exc:
            logger.warning("Ardent nearby lookup failed for %s: %s", center_system, exc)
            nearby = []
            sync_errors.append(f"{center_system} nearby: {exc.__class__.__name__}")
        systems = [{"systemName": center_system, "distance": 0}] + [row for row in nearby if row.get("systemName") != center_system]
        systems = systems[:max_systems]
        semaphore = asyncio.Semaphore(5)

        async def safe_fetch(system_name: str, label: str, path: str) -> tuple[Any, str | None]:
            try:
                async with semaphore:
                    return await self._get(path), None
            except Exception as exc:
                logger.warning("Ardent %s failed for %s: %s", label, system_name, exc)
                return [], f"{system_name} {label}: {exc.__class__.__name__}"

        async def sync_one(system_row: dict[str, Any]) -> dict[str, Any]:
            system_name = system_row["systemName"]
            stations, stations_error = await safe_fetch(system_name, "stations", f"/system/name/{system_name}/stations")
            exports, exports_error = await safe_fetch(
                system_name,
                "exports",
                f"/system/name/{system_name}/commodities/exports?maxDaysAgo={max_days_ago}",
            )
            imports, imports_error = await safe_fetch(
                system_name,
                "imports",
                f"/system/name/{system_name}/commodities/imports?maxDaysAgo={max_days_ago}",
            )
            errors = [err for err in (stations_error, exports_error, imports_error) if err]

            if stations:
                sample = stations[0]
                self.repo.upsert_system(
                    {
                        "name": sample.get("systemName"),
                        "address": sample.get("systemAddress"),
                        "x": sample.get("systemX"),
                        "y": sample.get("systemY"),
                        "z": sample.get("systemZ"),
                        "allegiance": None,
                        "government": None,
                        "faction": None,
                        "faction_state": None,
                        "population": None,
                        "security": None,
                        "economy_primary": None,
                        "economy_secondary": None,
                        "reserve": None,
                        "controlling_power": None,
                        "powerplay_state": None,
                        "requires_permit": 0,
                        "permit_name": None,
                        "access_updated_at": None,
                        "source": "ardent",
                        "updated_at": sample.get("updatedAt") or utc_now_iso(),
                    }
                )

            for station in stations:
                services = [name for name, enabled in [
                    ("shipyard", station.get("shipyard")),
                    ("outfitting", station.get("outfitting")),
                    ("blackMarket", station.get("blackMarket")),
                    ("contacts", station.get("contacts")),
                    ("crewLounge", station.get("crewLounge")),
                    ("interstellarFactors", station.get("interstellarFactors")),
                    ("materialTrader", station.get("materialTrader")),
                    ("missions", station.get("missions")),
                    ("refuel", station.get("refuel")),
                    ("repair", station.get("repair")),
                    ("restock", station.get("restock")),
                    ("searchAndRescue", station.get("searchAndRescue")),
                    ("technologyBroker", station.get("technologyBroker")),
                    ("tuning", station.get("tuning")),
                    ("universalCartographics", station.get("universalCartographics")),
                ] if enabled]
                self.repo.upsert_station(
                    {
                        "market_id": int(station["marketId"]),
                        "system_name": station["systemName"],
                        "name": station["stationName"],
                        "type": station.get("stationType"),
                        "distance_to_arrival": station.get("distanceToArrival"),
                        "allegiance": station.get("allegiance"),
                        "government": station.get("government"),
                        "economy_primary": station.get("primaryEconomy"),
                        "economy_secondary": station.get("secondaryEconomy"),
                        "landing_pad": infer_pad_size(station.get("stationType"), station.get("maxLandingPadSize")),
                        "is_planetary": 1 if is_planetary(station.get("stationType")) else 0,
                        "is_odyssey": 1 if is_odyssey_station(station.get("stationType")) else 0,
                        "is_fleet_carrier": 1 if is_fleet_carrier(station.get("stationType")) else 0,
                        "has_market": 1,
                        "has_shipyard": 1 if station.get("shipyard") else 0,
                        "has_outfitting": 1 if station.get("outfitting") else 0,
                        "services_json": json.dumps(services, ensure_ascii=False),
                        "source": "ardent",
                        "updated_at": station.get("updatedAt") or utc_now_iso(),
                    }
                )

            count = 0
            for entry in exports + imports:
                count += self.repo.upsert_market_snapshot(
                    {
                        "market_id": int(entry["marketId"]),
                        "system_name": entry["systemName"],
                        "name": entry["stationName"],
                        "type": entry.get("stationType"),
                        "distance_to_arrival": entry.get("distanceToArrival"),
                        "allegiance": entry.get("allegiance"),
                        "government": entry.get("government"),
                        "economy_primary": entry.get("primaryEconomy"),
                        "economy_secondary": entry.get("secondaryEconomy"),
                        "landing_pad": infer_pad_size(entry.get("stationType"), entry.get("maxLandingPadSize")),
                        "is_planetary": is_planetary(entry.get("stationType")),
                        "is_odyssey": is_odyssey_station(entry.get("stationType")),
                        "is_fleet_carrier": is_fleet_carrier(entry.get("stationType")),
                        "commodities": [
                            {
                                "symbol": str(entry["commodityName"]).strip().lower(),
                                "name": entry["commodityName"].replace("_", " ").title(),
                                "buy_price": entry.get("buyPrice", 0),
                                "sell_price": entry.get("sellPrice", 0),
                                "demand": entry.get("demand", 0),
                                "stock": entry.get("stock", 0),
                                "demand_bracket": entry.get("demandBracket", ""),
                                "stock_bracket": entry.get("stockBracket", ""),
                            }
                        ],
                        "services": [],
                    },
                    source="ardent",
                    updated_at=entry.get("updatedAt") or utc_now_iso(),
                )
            return {
                "system_name": system_name,
                "stations_loaded": len(stations),
                "market_rows_upserted": count,
                "errors": errors,
            }

        results = await asyncio.gather(*(sync_one(row) for row in systems))
        for result in results:
            sync_errors.extend(result["errors"])
        self.repo.set_state("source_ardent_last_sync", utc_now_iso())
        return {
            "systems_loaded": len(systems),
            "systems_synced": sum(1 for result in results if not result["errors"]),
            "systems_failed": sum(1 for result in results if result["errors"]),
            "stations_loaded": sum(result["stations_loaded"] for result in results),
            "market_rows_upserted": sum(result["market_rows_upserted"] for result in results),
            "systems_considered": [row["systemName"] for row in systems],
            "errors": sync_errors[:20],
        }


class SpanshClient:
    def __init__(self, repository: Repository):
        self.repo = repository

    def refresh_station(self, market_id: int) -> int:
        response = httpx.get(f"{SPANSH_API_BASE}/station/{market_id}", timeout=REQUEST_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
        record = response.json()["record"]

        self.repo.upsert_system(
            {
                "name": record.get("system_name"),
                "address": record.get("system_id64"),
                "x": record.get("system_x"),
                "y": record.get("system_y"),
                "z": record.get("system_z"),
                "allegiance": None,
                "government": None,
                "faction": record.get("controlling_minor_faction"),
                "faction_state": record.get("controlling_minor_faction_state"),
                "population": record.get("system_population"),
                "security": None,
                "economy_primary": record.get("system_primary_economy"),
                "economy_secondary": record.get("system_secondary_economy"),
                "reserve": None,
                "controlling_power": None,
                "powerplay_state": record.get("system_power_state"),
                "requires_permit": 0,
                "permit_name": None,
                "access_updated_at": None,
                "source": "spansh",
                "updated_at": record.get("updated_at") or utc_now_iso(),
            }
        )

        commodities = [
            {
                "symbol": str(item["commodity"]).strip().lower().replace(" ", ""),
                "name": item["commodity"],
                "category": item.get("category"),
                "buy_price": item.get("buy_price", 0),
                "sell_price": item.get("sell_price", 0),
                "demand": item.get("demand", 0),
                "stock": item.get("supply", 0),
            }
            for item in record.get("market", [])
        ]
        count = self.repo.upsert_market_snapshot(
            {
                "market_id": int(record["market_id"]),
                "system_name": record["system_name"],
                "name": record["name"],
                "type": record.get("type"),
                "distance_to_arrival": record.get("distance_to_arrival"),
                "allegiance": record.get("allegiance"),
                "government": record.get("government"),
                "economy_primary": record.get("primary_economy"),
                "economy_secondary": None,
                "landing_pad": infer_pad_size(record.get("type"), 3 if record.get("has_large_pad") else 2 if record.get("medium_pads") else 1 if record.get("small_pads") else None),
                "is_planetary": is_planetary(record.get("type")),
                "is_odyssey": is_odyssey_station(record.get("type")),
                "is_fleet_carrier": is_fleet_carrier(record.get("type")),
                "has_shipyard": bool(record.get("has_shipyard")),
                "has_outfitting": bool(record.get("has_outfitting")),
                "services": [service["name"] for service in record.get("services", [])],
                "commodities": commodities,
            },
            source="spansh",
            updated_at=record.get("market_updated_at") or record.get("updated_at") or utc_now_iso(),
        )
        self.repo.set_state("source_spansh_last_refresh", utc_now_iso())
        return count


class EDSMClient:
    def __init__(self, repository: Repository):
        self.repo = repository

    def _get(self, path: str, params: dict[str, Any], timeout: float = REQUEST_TIMEOUT) -> Any:
        response = httpx.get(
            f"{EDSM_BASE}{path}",
            params=params,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Elite-Plug/1.0"},
        )
        response.raise_for_status()
        return response.json()

    def refresh_market(self, market_id: int) -> int:
        payload = self._get("/api-system-v1/stations/market", {"marketId": market_id})
        commodities = [
            {
                "symbol": str(item.get("id") or item.get("name")).strip().lower(),
                "name": item.get("name") or item.get("id"),
                "buy_price": item.get("buyPrice", 0),
                "sell_price": item.get("sellPrice", 0),
                "demand": item.get("demand", 0),
                "stock": item.get("stock", 0),
                "stock_bracket": item.get("stockBracket", ""),
                "demand_bracket": item.get("demandBracket", ""),
            }
            for item in payload.get("commodities", [])
        ]
        count = self.repo.upsert_market_snapshot(
            {
                "market_id": int(payload["marketId"]),
                "system_name": payload["name"],
                "name": payload["sName"],
                "type": None,
                "distance_to_arrival": None,
                "allegiance": None,
                "government": None,
                "economy_primary": None,
                "economy_secondary": None,
                "landing_pad": "?",
                "is_planetary": False,
                "is_odyssey": False,
                "is_fleet_carrier": False,
                "services": [],
                "commodities": commodities,
            },
            source="edsm_market",
            updated_at=utc_now_iso(),
        )
        self.repo.set_state("source_edsm_last_refresh", utc_now_iso())
        return count

    def refresh_system_access(self, system_name: str) -> dict[str, Any]:
        payload = self._get(
            "/api-v1/system",
            {"systemName": system_name, "showInformation": 1, "showPermit": 1},
            timeout=ACCESS_REQUEST_TIMEOUT,
        )
        information = payload.get("information") or {}
        permit_name = payload.get("permitName")
        normalized_permit_name = normalize_permit_name(permit_name)
        requires_permit = bool(payload.get("requirePermit") or permit_name)
        now = utc_now_iso()
        current_system = self.repo.get_state("current_system")
        owned_permits = known_owned_permits()
        with self.repo.connect() as conn:
            visited_row = conn.execute(
                "SELECT 1 FROM systems WHERE name = ? AND source = 'journal' LIMIT 1",
                (system_name,),
            ).fetchone()
        if requires_permit and normalized_permit_name and (current_system == system_name or visited_row):
            owned_permits.add(normalized_permit_name)
            self.repo.set_state("owned_permits", sorted(owned_permits))
        self.repo.upsert_system(
            {
                "name": payload.get("name") or system_name,
                "address": None,
                "x": None,
                "y": None,
                "z": None,
                "allegiance": information.get("allegiance"),
                "government": information.get("government"),
                "faction": information.get("faction"),
                "faction_state": information.get("factionState"),
                "population": information.get("population"),
                "security": information.get("security"),
                "economy_primary": information.get("economy"),
                "economy_secondary": information.get("secondEconomy"),
                "reserve": information.get("reserve"),
                "controlling_power": None,
                "powerplay_state": None,
                "requires_permit": 1 if requires_permit else 0,
                "permit_name": permit_name,
                "access_updated_at": now,
                "source": "edsm_system",
                "updated_at": now,
            }
        )
        return {
            "system_name": payload.get("name") or system_name,
            "requires_permit": requires_permit,
            "permit_name": permit_name,
            "access_updated_at": now,
        }

    def refresh_system_accesses(self, system_names: list[str]) -> dict[str, Any]:
        checked = 0
        blocked = 0
        errors: list[str] = []
        for system_name in sorted({name for name in system_names if name}):
            try:
                result = self.refresh_system_access(system_name)
                checked += 1
                if result.get("requires_permit") and str(result.get("permit_name") or "").strip().lower() not in known_owned_permits():
                    blocked += 1
            except Exception as exc:
                logger.warning("EDSM system access lookup failed for %s: %s", system_name, exc)
                errors.append(f"{system_name}: {exc.__class__.__name__}")
        self.repo.set_state("source_edsm_access_last_refresh", utc_now_iso())
        return {
            "systems_checked": checked,
            "systems_blocked": blocked,
            "errors": errors,
        }


@dataclass
class EDDNStatus:
    running: bool = False
    connected: bool = False
    started_at: str | None = None
    last_message_at: str | None = None
    last_commodity_at: str | None = None
    last_error: str | None = None
    messages_seen: int = 0
    commodity_snapshots: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "connected": self.connected,
            "started_at": self.started_at,
            "last_message_at": self.last_message_at,
            "last_commodity_at": self.last_commodity_at,
            "last_error": self.last_error,
            "messages_seen": self.messages_seen,
            "commodity_snapshots": self.commodity_snapshots,
            "last_message_age_min": age_minutes(self.last_message_at),
            "last_commodity_age_min": age_minutes(self.last_commodity_at),
        }


class EDDNListener:
    def __init__(self, repository: Repository):
        self.repo = repository
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.status_data = EDDNStatus()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status_data.as_dict()
            self._stop.clear()
            self.status_data = EDDNStatus(running=True, started_at=utc_now_iso())
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            return self.status_data.as_dict()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        with self._lock:
            self.status_data.running = False
            self.status_data.connected = False
            return self.status_data.as_dict()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.status_data.as_dict()

    def _run(self) -> None:
        context = zmq.Context.instance()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        socket.setsockopt(zmq.RCVTIMEO, 2000)
        socket.connect(EDDN_ENDPOINT)
        with self._lock:
            self.status_data.connected = True

        try:
            while not self._stop.is_set():
                try:
                    payload = socket.recv()
                except zmq.Again:
                    continue
                except Exception as exc:
                    with self._lock:
                        self.status_data.last_error = str(exc)
                    continue
                try:
                    decoded = json.loads(zlib.decompress(payload).decode("utf-8"))
                except zlib.error:
                    decoded = json.loads(payload.decode("utf-8"))
                with self._lock:
                    self.status_data.messages_seen += 1
                    self.status_data.last_message_at = utc_now_iso()
                if "/commodity/" not in str(decoded.get("$schemaRef", "")):
                    continue
                try:
                    self._ingest(decoded)
                    with self._lock:
                        self.status_data.commodity_snapshots += 1
                        self.status_data.last_commodity_at = utc_now_iso()
                except Exception as exc:
                    with self._lock:
                        self.status_data.last_error = str(exc)
        finally:
            socket.close(0)
            with self._lock:
                self.status_data.running = False
                self.status_data.connected = False

    def _ingest(self, payload: dict[str, Any]) -> None:
        header = payload.get("header") or {}
        message = payload.get("message") or {}
        economies = message.get("economies") or []
        station_type = "Fleet Carrier" if any(item.get("name") == "Carrier" for item in economies) else "Station"
        if not message.get("marketId") or not message.get("systemName") or not message.get("stationName"):
            return
        current_market_id = int(self.repo.get_state("current_market_id") or 0)
        message_market_id = int(message.get("marketId") or 0)
        tracked_symbols = tracked_live_commodity_symbols()
        commodities = []
        for entry in message.get("commodities", []):
            symbol = str(entry.get("name") or "").strip().lower()
            if not symbol:
                continue
            if tracked_symbols and symbol not in tracked_symbols and message_market_id != current_market_id:
                continue
            commodities.append(
                {
                    "symbol": symbol,
                    "name": symbol.replace("_", " ").title(),
                    "buy_price": entry.get("buyPrice", 0),
                    "sell_price": entry.get("sellPrice", 0),
                    "demand": entry.get("demand", 0),
                    "stock": entry.get("stock", 0),
                    "demand_bracket": entry.get("demandBracket", ""),
                    "stock_bracket": entry.get("stockBracket", ""),
                }
            )
        if not commodities:
            return
        self.repo.upsert_market_snapshot(
            {
                "market_id": message_market_id,
                "system_name": message["systemName"],
                "name": message["stationName"],
                "type": station_type,
                "distance_to_arrival": 0,
                "allegiance": None,
                "government": None,
                "economy_primary": economies[0]["name"] if economies else None,
                "economy_secondary": None,
                "landing_pad": infer_pad_size(station_type),
                "is_planetary": False,
                "is_odyssey": bool(message.get("odyssey")),
                "is_fleet_carrier": station_type == "Fleet Carrier",
                "services": [],
                "commodities": commodities,
            },
            source="eddn",
            updated_at=header.get("gatewayTimestamp") or message.get("timestamp") or utc_now_iso(),
        )
        self.repo.set_state("source_eddn_last_refresh", utc_now_iso())


PAD_RANK = {"?": 0, "S": 1, "M": 2, "L": 3}
SOURCE_CONFIDENCE = {
    "journal_market": 98,
    "journal": 95,
    "eddn": 96,
    "spansh": 90,
    "ardent": 84,
    "edsm_market": 78,
}


def subsequence_bonus(query: str, candidate: str) -> int:
    if not query or not candidate:
        return 0
    cursor = 0
    gaps = 0
    for char in query:
        index = candidate.find(char, cursor)
        if index < 0:
            return 0
        gaps += max(0, index - cursor)
        cursor = index + 1
    return max(0, 26 - gaps - max(0, len(candidate) - len(query)))


def text_match_score(query: str, candidate: Any) -> tuple[int, str]:
    query_text = normalize_search_text(query)
    candidate_text = normalize_search_text(candidate)
    if not query_text or not candidate_text:
        return 0, ""
    query_compact = compact_search_key(query_text)
    candidate_compact = compact_search_key(candidate_text)
    query_words = search_words(query_text)
    candidate_words = search_words(candidate_text)
    if query_text == candidate_text or query_compact == candidate_compact:
        return 166, "Exact"
    if candidate_text.startswith(query_text) or candidate_compact.startswith(query_compact):
        return 132 + min(24, len(query_compact) * 6), "Préfixe"
    if query_words and any(word.startswith(query_words[0]) for word in candidate_words):
        return 118 + min(18, len(query_compact) * 4), "Mot-clé"
    if query_text in candidate_text or query_compact in candidate_compact:
        return 98 + min(14, len(query_compact) * 3), "Contient"
    fuzzy = subsequence_bonus(query_compact, candidate_compact)
    if fuzzy > 0:
        return 72 + fuzzy, "Fuzzy"
    return 0, ""


def best_variant_score(query: str, *variants: Any) -> tuple[int, str, str]:
    best_score = 0
    best_label = ""
    best_variant = ""
    for variant in variants:
        if not variant:
            continue
        score, label = text_match_score(query, variant)
        if score > best_score:
            best_score = score
            best_label = label
            best_variant = str(variant)
    return best_score, best_label, best_variant


def normalize_permit_name(value: Any) -> str:
    return normalize_search_text(value)


def permit_display_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    resolved = repo.resolve_system(text)
    return str((resolved or {}).get("name") or text)


def player_rank_value(rank_name: str) -> int:
    payload = repo.get_state("rank", {}) or {}
    if not isinstance(payload, dict):
        return -1
    try:
        return int(payload.get(rank_name, -1))
    except (TypeError, ValueError):
        return -1


def inferred_owned_permits() -> set[str]:
    permits: set[str] = set()
    federation_rank = player_rank_value("Federation")
    empire_rank = player_rank_value("Empire")
    for permit_name, required_rank in FEDERATION_RANK_PERMITS.items():
        if federation_rank >= required_rank:
            permits.add(normalize_permit_name(permit_name))
    for permit_name, required_rank in EMPIRE_RANK_PERMITS.items():
        if empire_rank >= required_rank:
            permits.add(normalize_permit_name(permit_name))
    current_system = str(repo.get_state("current_system") or "").strip()
    if current_system:
        current = repo.resolve_system(current_system) or {"name": current_system}
        if current.get("requires_permit") or current.get("permit_name"):
            permits.add(normalize_permit_name(current.get("permit_name") or current.get("name")))
    return {permit for permit in permits if permit}


def known_owned_permits() -> set[str]:
    owned = repo.get_state("owned_permits", []) or []
    explicit = {normalize_permit_name(item) for item in owned if str(item).strip()}
    return {permit for permit in {*(explicit or set()), *inferred_owned_permits()} if permit}


def known_owned_permit_labels() -> list[str]:
    labels = [permit_display_name(item) for item in known_owned_permits()]
    labels = [label for label in labels if label]
    return sorted(set(labels), key=lambda item: normalize_search_text(item))


def tracked_live_commodity_symbols() -> set[str]:
    tracked = {normalize_commodity_symbol(symbol) for symbol in WATCHLIST_SYMBOLS}
    focus_symbol = normalize_commodity_symbol(repo.get_state("focus_commodity"))
    mission_symbol = normalize_commodity_symbol(repo.get_state("mission_commodity"))
    if focus_symbol:
        tracked.add(focus_symbol)
    if mission_symbol:
        tracked.add(mission_symbol)
    return {symbol for symbol in tracked if symbol}


def station_accessible(row: dict[str, Any], owned_permits: set[str] | None = None) -> bool:
    if not int(row.get("has_market") or 0):
        return False
    permit_name = normalize_permit_name(row.get("permit_name"))
    if not permit_name:
        return True
    permits = owned_permits if owned_permits is not None else known_owned_permits()
    return permit_name in permits


def station_badges(row: dict[str, Any], owned_permits: set[str] | None = None) -> list[str]:
    badges: list[str] = []
    pad = str(row.get("landing_pad") or "?").strip().upper()
    if pad in {"S", "M", "L"}:
        badges.append(f"Pad {pad}")
    else:
        badges.append("Pad ?")
    if station_accessible(row, owned_permits):
        badges.append("Accès OK")
    elif row.get("permit_name"):
        badges.append(f"Permis {row['permit_name']}")
    if int(row.get("has_market") or 0):
        badges.append("Marché confirmé")
    if row.get("is_planetary"):
        badges.append("Planétaire")
    if row.get("is_odyssey"):
        badges.append("Odyssey")
    if row.get("is_fleet_carrier"):
        badges.append("Carrier")
    return badges[:5]


def station_accessibility_label(row: dict[str, Any], owned_permits: set[str] | None = None) -> str:
    if not int(row.get("has_market") or 0):
        return "Sans marché"
    if not station_accessible(row, owned_permits):
        return "Sous permis"
    if row.get("is_fleet_carrier"):
        return "Carrier"
    if row.get("is_planetary"):
        return "Planétaire"
    if row.get("is_odyssey"):
        return "Odyssey"
    return "Accès direct"


@dataclass
class TradeFilters:
    cargo_capacity: int
    jump_range: float
    max_age_hours: float
    max_station_distance_ls: int
    min_profit_unit: int
    min_buy_stock: int
    min_sell_demand: int
    min_pad_size: str
    include_planetary: bool
    include_settlements: bool
    include_fleet_carriers: bool
    no_surprise: bool
    max_results: int


DEFAULT_CONFIDENCE_FILTERS = TradeFilters(
    cargo_capacity=100,
    jump_range=15,
    max_age_hours=72,
    max_station_distance_ls=5000,
    min_profit_unit=1000,
    min_buy_stock=0,
    min_sell_demand=0,
    min_pad_size="M",
    include_planetary=True,
    include_settlements=False,
    include_fleet_carriers=False,
    no_surprise=False,
    max_results=25,
)


def euclidean_distance(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    coords = [a.get("x"), a.get("y"), a.get("z"), b.get("x"), b.get("y"), b.get("z")]
    if any(value is None for value in coords):
        return None
    return round(
        math.sqrt(
            (a["x"] - b["x"]) ** 2
            + (a["y"] - b["y"]) ** 2
            + (a["z"] - b["z"]) ** 2
        ),
        2,
    )


def station_allowed(row: dict[str, Any], filters: TradeFilters, owned_permits: set[str] | None = None) -> bool:
    if not station_accessible(row, owned_permits):
        return False
    if PAD_RANK.get(row.get("landing_pad") or "?", 0) < PAD_RANK.get(filters.min_pad_size, 0):
        return False
    if not filters.include_planetary and row.get("is_planetary"):
        return False
    if not filters.include_settlements and row.get("is_odyssey") and "settlement" in str(row.get("station_type") or "").lower():
        return False
    if not filters.include_fleet_carriers and row.get("is_fleet_carrier"):
        return False
    if row.get("distance_to_arrival") and float(row["distance_to_arrival"]) > filters.max_station_distance_ls:
        return False
    freshness = age_hours(row.get("price_updated_at"))
    if freshness is None or freshness > filters.max_age_hours:
        return False
    if filters.no_surprise:
        if PAD_RANK.get(row.get("landing_pad") or "?", 0) <= 0:
            return False
        if row.get("distance_to_arrival") and float(row["distance_to_arrival"]) > min(filters.max_station_distance_ls, 2500):
            return False
        if freshness > min(filters.max_age_hours, 24):
            return False
    return True


def minimum_trade_units(filters: TradeFilters) -> int:
    cargo_capacity = max(int(filters.cargo_capacity or 0), 1)
    return max(4, min(32, math.ceil(cargo_capacity * 0.10)))


def minimum_buy_stock(filters: TradeFilters) -> int:
    return max(minimum_trade_units(filters), int(filters.min_buy_stock or 0))


def minimum_sell_demand(filters: TradeFilters) -> int:
    return max(minimum_trade_units(filters), int(filters.min_sell_demand or 0))


def meaningful_buy_rows(rows: list[dict[str, Any]], filters: TradeFilters) -> list[dict[str, Any]]:
    candidates = [row for row in rows if int(row.get("buy_price") or 0) > 0 and int(row.get("stock") or 0) > 0]
    if not candidates:
        return []
    minimum_units = minimum_buy_stock(filters)
    preferred = [row for row in candidates if int(row.get("stock") or 0) >= minimum_units]
    return preferred or candidates


def meaningful_sell_rows(rows: list[dict[str, Any]], filters: TradeFilters) -> list[dict[str, Any]]:
    candidates = [row for row in rows if int(row.get("sell_price") or 0) > 0 and int(row.get("demand") or 0) > 0]
    if not candidates:
        return []
    minimum_units = minimum_sell_demand(filters)
    preferred = [row for row in candidates if int(row.get("demand") or 0) >= minimum_units]
    return preferred or candidates


def relaxed_trade_filters(filters: TradeFilters) -> TradeFilters:
    return TradeFilters(
        cargo_capacity=filters.cargo_capacity,
        jump_range=filters.jump_range,
        max_age_hours=max(float(filters.max_age_hours or 0), 96.0),
        max_station_distance_ls=max(int(filters.max_station_distance_ls or 0), 20000),
        min_profit_unit=0,
        min_buy_stock=max(0, int(filters.min_buy_stock or 0) // 2),
        min_sell_demand=max(0, int(filters.min_sell_demand or 0) // 2),
        min_pad_size=filters.min_pad_size,
        include_planetary=filters.include_planetary,
        include_settlements=filters.include_settlements,
        include_fleet_carriers=filters.include_fleet_carriers,
        no_surprise=False,
        max_results=max(int(filters.max_results or 0), 40),
    )


def commodity_price_filters(filters: TradeFilters) -> TradeFilters:
    # For a direct commodity lookup, price comes first. Distance stays informational.
    return replace(
        filters,
        max_station_distance_ls=NO_DISTANCE_LIMIT_LS,
        min_profit_unit=0,
        no_surprise=False,
        max_results=max(int(filters.max_results or 0), 40),
    )


def resolve_trade_context(system_name: str | None = None, station_name: str | None = None) -> dict[str, Any]:
    resolved_system = repo.resolve_system(system_name) if system_name else None
    normalized_system_name = str((resolved_system or {}).get("name") or (system_name or "")).strip() or None
    resolved_station = repo.resolve_station(station_name, system_name=normalized_system_name) if station_name else None
    if station_name and not resolved_station:
        resolved_station = repo.resolve_station(station_name)
    normalized_station_name = str((resolved_station or {}).get("station_name") or (station_name or "")).strip() or None
    market_id = int(resolved_station["market_id"]) if resolved_station and resolved_station.get("market_id") else None
    if normalized_system_name is None and resolved_station and resolved_station.get("system_name"):
        normalized_system_name = str(resolved_station["system_name"]).strip()
    elif resolved_station and resolved_station.get("system_name"):
        normalized_system_name = str(resolved_station["system_name"]).strip()
    return {
        "system_name": normalized_system_name,
        "station_name": normalized_station_name,
        "market_id": market_id,
    }


def filter_trade_rows_by_context(
    rows: list[dict[str, Any]],
    *,
    system_name: str | None = None,
    market_id: int | None = None,
) -> list[dict[str, Any]]:
    filtered = rows
    if system_name:
        normalized_system = normalize_search_text(system_name)
        filtered = [row for row in filtered if normalize_search_text(row.get("system_name")) == normalized_system]
    if market_id is not None:
        filtered = [row for row in filtered if int(row.get("market_id") or 0) == int(market_id)]
    return filtered


def rows_for_symbol_with_fallback(
    symbol: str,
    filters: TradeFilters,
    permits: set[str] | None,
    *,
    all_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    base_rows = all_rows if all_rows is not None else repo.filtered_trade_rows(filters, commodity_symbols=[symbol])
    rows = [row for row in base_rows if row["commodity_symbol"] == symbol and station_allowed(row, filters, permits)]
    if meaningful_buy_rows(rows, filters) and meaningful_sell_rows(rows, filters):
        return rows, False

    fallback_filters = relaxed_trade_filters(filters)
    fallback_base_rows = repo.filtered_trade_rows(fallback_filters, commodity_symbols=[symbol])
    fallback_rows = [
        row
        for row in fallback_base_rows
        if row["commodity_symbol"] == symbol and station_allowed(row, fallback_filters, permits)
    ]
    if not fallback_rows:
        return rows, False

    merged: dict[tuple[int, str], dict[str, Any]] = {
        (int(row["market_id"]), row["commodity_symbol"]): row
        for row in rows
    }
    for row in fallback_rows:
        merged[(int(row["market_id"]), row["commodity_symbol"])] = row
    return list(merged.values()), True


def clamp_score(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return max(minimum, min(maximum, int(round(value))))


def source_confidence(source: str | None) -> int:
    return SOURCE_CONFIDENCE.get(str(source or "").strip().lower(), 72)


def freshness_confidence(freshness_hours: float | None, max_age_hours: float) -> int:
    if freshness_hours is None:
        return 18
    if max_age_hours <= 0:
        return 100
    ratio = min(max(float(freshness_hours) / max_age_hours, 0.0), 1.4)
    return clamp_score(100 - (ratio * 55))


def ls_confidence(distance_ls: float | None, max_station_distance_ls: int) -> int:
    if distance_ls is None:
        return 62
    if max_station_distance_ls <= 0:
        return 100
    ratio = min(max(float(distance_ls) / max_station_distance_ls, 0.0), 1.5)
    return clamp_score(100 - (ratio * 45))


def pad_confidence(row: dict[str, Any], min_pad_size: str) -> int:
    actual = PAD_RANK.get(row.get("landing_pad") or "?", 0)
    minimum = PAD_RANK.get(min_pad_size, 0)
    if actual <= 0:
        return 55
    if actual < minimum:
        return 0
    return 100 if actual == minimum else 92


def row_confidence(row: dict[str, Any], filters: TradeFilters, owned_permits: set[str] | None = None) -> int:
    freshness = age_hours(row.get("price_updated_at"))
    score = (
        source_confidence(row.get("price_source") or row.get("source")) * 0.34
        + freshness_confidence(freshness, filters.max_age_hours) * 0.28
        + ls_confidence(row.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.18
        + pad_confidence(row, filters.min_pad_size) * 0.12
        + (100 if station_accessible(row, owned_permits) else 0) * 0.08
    )
    return clamp_score(score)


def confidence_label(score: int) -> str:
    if score >= 90:
        return "Très haute"
    if score >= 78:
        return "Haute"
    if score >= 64:
        return "Bonne"
    if score >= 48:
        return "Moyenne"
    return "Prudence"


def estimate_minutes(route_distance_ly: float | None, source_ls: float | None, target_ls: float | None, jump_range: float) -> float:
    jumps = 1
    if route_distance_ly and jump_range > 0:
        jumps = max(1, math.ceil(route_distance_ly / max(jump_range * 0.9, 1)))
    supercruise = ((source_ls or 0) + (target_ls or 0)) / 900
    return max(5.0, jumps * 1.6 + supercruise + 2.2)


def build_route_candidate(
    source: dict[str, Any],
    target: dict[str, Any],
    filters: TradeFilters,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    if source["market_id"] == target["market_id"]:
        return None
    unit_profit = int(target["sell_price"]) - int(source["buy_price"])
    if unit_profit < filters.min_profit_unit:
        return None
    units = min(
        filters.cargo_capacity,
        int(source.get("stock") or filters.cargo_capacity),
        int(target.get("demand") or filters.cargo_capacity),
    )
    if units <= 0:
        return None
    if units < minimum_trade_units(filters):
        return None
    route_distance = euclidean_distance(source, target)
    minutes = estimate_minutes(route_distance, source.get("distance_to_arrival"), target.get("distance_to_arrival"), filters.jump_range)
    trip_profit = unit_profit * units
    freshness = max(age_hours(source.get("price_updated_at")) or 0, age_hours(target.get("price_updated_at")) or 0)
    player_distance = euclidean_distance(source, player_position) if player_position else None
    source_conf = row_confidence(source, filters, owned_permits)
    target_conf = row_confidence(target, filters, owned_permits)
    confidence = clamp_score((source_conf + target_conf) / 2)
    profit_per_hour = round(trip_profit * 60 / minutes, 2)
    profit_per_minute = round(trip_profit / max(minutes, 1), 2)
    profit_score = clamp_score(math.log10(max(profit_per_hour, 1)) * 18)
    trip_score = clamp_score(math.log10(max(trip_profit, 1)) * 18)
    travel_score = clamp_score(100 - min(minutes, 35) * 2.2)
    freshness_score = freshness_confidence(freshness, filters.max_age_hours)
    route_score = clamp_score(
        profit_score * 0.32
        + trip_score * 0.18
        + confidence * 0.26
        + freshness_score * 0.14
        + travel_score * 0.10
    )
    return {
        "commodity_symbol": source["commodity_symbol"],
        "commodity_name": source.get("commodity_name_fr") or source.get("commodity_name"),
        "source_market_id": source["market_id"],
        "source_system": source["system_name"],
        "source_station": source["station_name"],
        "source_buy_price": source["buy_price"],
        "source_stock": source["stock"],
        "source_distance_ls": source.get("distance_to_arrival"),
        "target_market_id": target["market_id"],
        "target_system": target["system_name"],
        "target_station": target["station_name"],
        "target_sell_price": target["sell_price"],
        "target_demand": target["demand"],
        "target_distance_ls": target.get("distance_to_arrival"),
        "route_distance_ly": route_distance,
        "distance_from_player_ly": player_distance,
        "units": units,
        "unit_profit": unit_profit,
        "trip_profit": trip_profit,
        "estimated_minutes": round(minutes, 1),
        "profit_per_hour": profit_per_hour,
        "profit_per_minute": profit_per_minute,
        "freshness_hours": round(freshness, 2),
        "confidence_score": confidence,
        "confidence_label": confidence_label(confidence),
        "route_score": route_score,
        "source_confidence_score": source_conf,
        "target_confidence_score": target_conf,
        "source_badges": station_badges(source, owned_permits),
        "target_badges": station_badges(target, owned_permits),
        "accessibility": f"{station_accessibility_label(source, owned_permits)} -> {station_accessibility_label(target, owned_permits)}",
    }


def player_distance_confidence(distance_ly: float | None) -> int:
    if distance_ly is None:
        return 58
    return clamp_score(100 - min(float(distance_ly), 120.0) * 0.75)


def relative_value_score(value: int | float, minimum: int | float, maximum: int | float, *, higher_is_better: bool) -> int:
    if maximum <= minimum:
        return 100
    ratio = (float(value) - float(minimum)) / max(float(maximum) - float(minimum), 1.0)
    ratio = min(max(ratio, 0.0), 1.0)
    if higher_is_better:
        return clamp_score(ratio * 100)
    return clamp_score((1.0 - ratio) * 100)


def summarize_market_offer(
    row: dict[str, Any],
    player_position: dict[str, Any] | None,
    *,
    mode: Literal["buy", "sell"],
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    freshness = round(age_hours(row.get("price_updated_at")) or 0, 2)
    confidence = row_confidence(row, DEFAULT_CONFIDENCE_FILTERS, owned_permits)
    return {
        "commodity_symbol": row["commodity_symbol"],
        "commodity_name": row.get("commodity_name_fr") or row.get("commodity_name"),
        "system_name": row["system_name"],
        "station_name": row["station_name"],
        "market_id": row["market_id"],
        "distance_ls": row.get("distance_to_arrival"),
        "landing_pad": row.get("landing_pad"),
        "price": row["buy_price"] if mode == "buy" else row["sell_price"],
        "stock": row.get("stock"),
        "demand": row.get("demand"),
        "freshness_hours": freshness,
        "distance_from_player_ly": euclidean_distance(row, player_position) if player_position else None,
        "confidence_score": confidence,
        "confidence_label": confidence_label(confidence),
        "source_name": row.get("price_source") or row.get("source"),
        "badges": station_badges(row, owned_permits),
        "accessibility": station_accessibility_label(row, owned_permits),
        "updated_at": row.get("price_updated_at"),
    }


def select_best_local_buy(
    rows: list[dict[str, Any]],
    filters: TradeFilters,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    prices = [int(row.get("buy_price") or 0) for row in rows]
    price_min = min(prices)
    price_max = max(prices)
    best_offer: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        distance_from_player = euclidean_distance(row, player_position) if player_position else None
        deal_score = clamp_score(
            relative_value_score(int(row.get("buy_price") or 0), price_min, price_max, higher_is_better=False) * 0.46
            + player_distance_confidence(distance_from_player) * 0.24
            + ls_confidence(row.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.12
            + freshness_confidence(age_hours(row.get("price_updated_at")), filters.max_age_hours) * 0.08
            + row_confidence(row, filters, owned_permits) * 0.10
        )
        if deal_score <= best_score:
            continue
        offer = summarize_market_offer(row, player_position, mode="buy", owned_permits=owned_permits)
        offer["deal_score"] = deal_score
        offer["deal_label"] = "Prix bas + proche"
        best_offer = offer
        best_score = deal_score
    return best_offer


def select_best_local_sell(
    rows: list[dict[str, Any]],
    filters: TradeFilters,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    if not rows:
        return None
    prices = [int(row.get("sell_price") or 0) for row in rows]
    price_min = min(prices)
    price_max = max(prices)
    best_offer: dict[str, Any] | None = None
    best_score = -1
    for row in rows:
        distance_from_player = euclidean_distance(row, player_position) if player_position else None
        deal_score = clamp_score(
            relative_value_score(int(row.get("sell_price") or 0), price_min, price_max, higher_is_better=True) * 0.48
            + player_distance_confidence(distance_from_player) * 0.22
            + freshness_confidence(age_hours(row.get("price_updated_at")), filters.max_age_hours) * 0.12
            + ls_confidence(row.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.08
            + row_confidence(row, filters, owned_permits) * 0.10
        )
        if deal_score <= best_score:
            continue
        offer = summarize_market_offer(row, player_position, mode="sell", owned_permits=owned_permits)
        offer["deal_score"] = deal_score
        offer["deal_label"] = "Prix haut + exécution rapide"
        best_offer = offer
        best_score = deal_score
    return best_offer


def summarize_purchase_plan(
    row: dict[str, Any],
    quantity: int,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    available = max(0, int(row.get("stock") or 0))
    units = min(quantity, available)
    price = int(row.get("buy_price") or 0)
    confidence = row_confidence(row, DEFAULT_CONFIDENCE_FILTERS, owned_permits)
    return {
        "commodity_symbol": row["commodity_symbol"],
        "commodity_name": row.get("commodity_name_fr") or row.get("commodity_name"),
        "system_name": row["system_name"],
        "station_name": row["station_name"],
        "market_id": row["market_id"],
        "landing_pad": row.get("landing_pad"),
        "distance_ls": row.get("distance_to_arrival"),
        "price": price,
        "available_units": available,
        "requested_units": quantity,
        "units_covered": units,
        "units_missing": max(0, quantity - units),
        "coverage_percent": clamp_score((units / max(quantity, 1)) * 100),
        "total_cost": price * units,
        "freshness_hours": round(age_hours(row.get("price_updated_at")) or 0, 2),
        "distance_from_player_ly": euclidean_distance(row, player_position) if player_position else None,
        "confidence_score": confidence,
        "confidence_label": confidence_label(confidence),
        "badges": station_badges(row, owned_permits),
        "accessibility": station_accessibility_label(row, owned_permits),
    }


def build_mission_delivery_candidate(
    source: dict[str, Any],
    destination: dict[str, Any],
    quantity: int,
    filters: TradeFilters,
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any] | None:
    available = max(0, int(source.get("stock") or 0))
    units = min(quantity, available)
    if units <= 0:
        return None
    route_distance = euclidean_distance(source, destination)
    minutes = estimate_minutes(route_distance, source.get("distance_to_arrival"), destination.get("distance_to_arrival"), filters.jump_range)
    source_conf = row_confidence(source, filters, owned_permits)
    destination_conf = clamp_score(
        ls_confidence(destination.get("distance_to_arrival"), filters.max_station_distance_ls) * 0.45
        + pad_confidence(destination, filters.min_pad_size) * 0.35
        + (100 if station_accessible(destination, owned_permits) else 0) * 0.20
    )
    confidence = clamp_score((source_conf + destination_conf) / 2)
    target_sell_price = int(destination.get("sell_price") or 0)
    source_buy_price = int(source.get("buy_price") or 0)
    margin_per_unit = target_sell_price - source_buy_price if target_sell_price > 0 else None
    return {
        "commodity_symbol": source["commodity_symbol"],
        "commodity_name": source.get("commodity_name_fr") or source.get("commodity_name"),
        "source_system": source["system_name"],
        "source_station": source["station_name"],
        "source_market_id": source["market_id"],
        "source_buy_price": source_buy_price,
        "source_stock": available,
        "source_distance_ls": source.get("distance_to_arrival"),
        "target_system": destination.get("system_name"),
        "target_station": destination.get("station_name"),
        "target_market_id": destination.get("market_id"),
        "target_distance_ls": destination.get("distance_to_arrival"),
        "target_sell_price": target_sell_price if target_sell_price > 0 else None,
        "route_distance_ly": route_distance,
        "distance_from_player_ly": euclidean_distance(source, player_position) if player_position else None,
        "units": units,
        "total_cost": source_buy_price * units,
        "margin_per_unit": margin_per_unit,
        "estimated_minutes": round(minutes, 1),
        "profit_per_minute": round(((margin_per_unit or 0) * units) / max(minutes, 1), 2) if margin_per_unit is not None else 0,
        "freshness_hours": round(age_hours(source.get("price_updated_at")) or 0, 2),
        "confidence_score": confidence,
        "confidence_label": confidence_label(confidence),
        "route_score": clamp_score(
            confidence * 0.42
            + freshness_confidence(age_hours(source.get("price_updated_at")), filters.max_age_hours) * 0.18
            + clamp_score(100 - min(minutes, 35) * 2.0) * 0.22
            + clamp_score((units / max(quantity, 1)) * 100) * 0.18
        ),
        "source_badges": station_badges(source, owned_permits),
        "target_badges": station_badges(destination, owned_permits),
        "accessibility": f"{station_accessibility_label(source, owned_permits)} -> {station_accessibility_label(destination, owned_permits)}",
    }


def build_commodity_intel(
    query: str | None,
    filters: TradeFilters,
    *,
    origin_system: str | None = None,
    origin_station: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
    all_rows: list[dict[str, Any]] | None = None,
    player_position: dict[str, Any] | None = None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    resolved = repo.resolve_commodity(query)
    origin_context = resolve_trade_context(origin_system, origin_station)
    target_context = resolve_trade_context(target_system, target_station)
    if not resolved:
        return {
            "query": query,
            "resolved": False,
            "symbol": None,
            "commodity_name": None,
            "selection_context": {
                "origin": origin_context,
                "target": target_context,
            },
            "best_buys": [],
            "best_sells": [],
            "best_routes": [],
            "history": [],
            "quick_trade": None,
            "decision_cards": {},
            "route_views": {},
        }

    permits = owned_permits if owned_permits is not None else known_owned_permits()
    if player_position is None:
        player_position = repo.system_position(repo.get_state("current_system"))
    market_filters = commodity_price_filters(filters)
    strict_base_rows = repo.filtered_trade_rows(market_filters, commodity_symbols=[resolved["symbol"]])
    strict_rows = [
        row
        for row in strict_base_rows
        if row["commodity_symbol"] == resolved["symbol"] and station_allowed(row, market_filters, permits)
    ]
    strict_buy_rows = meaningful_buy_rows(
        filter_trade_rows_by_context(
            strict_rows,
            system_name=origin_context.get("system_name"),
            market_id=origin_context.get("market_id"),
        ),
        market_filters,
    )
    strict_sell_rows = meaningful_sell_rows(
        filter_trade_rows_by_context(
            strict_rows,
            system_name=target_context.get("system_name"),
            market_id=target_context.get("market_id"),
        ),
        market_filters,
    )

    fallback_used = False
    fallback_buy_used = False
    fallback_sell_used = False
    buy_rows = list(strict_buy_rows)
    sell_rows = list(strict_sell_rows)

    if not strict_buy_rows or not strict_sell_rows:
        relaxed_filters = relaxed_trade_filters(market_filters)
        fallback_base_rows = repo.filtered_trade_rows(relaxed_filters, commodity_symbols=[resolved["symbol"]])
        fallback_rows = [
            row
            for row in fallback_base_rows
            if row["commodity_symbol"] == resolved["symbol"] and station_allowed(row, relaxed_filters, permits)
        ]
        fallback_buy_rows = meaningful_buy_rows(
            filter_trade_rows_by_context(
                fallback_rows,
                system_name=origin_context.get("system_name"),
                market_id=origin_context.get("market_id"),
            ),
            relaxed_filters,
        )
        fallback_sell_rows = meaningful_sell_rows(
            filter_trade_rows_by_context(
                fallback_rows,
                system_name=target_context.get("system_name"),
                market_id=target_context.get("market_id"),
            ),
            relaxed_filters,
        )
        if not strict_buy_rows and fallback_buy_rows:
            buy_rows = fallback_buy_rows
            fallback_buy_used = True
            fallback_used = True
        if not strict_sell_rows and fallback_sell_rows:
            sell_rows = fallback_sell_rows
            fallback_sell_used = True
            fallback_used = True

    buy_rows.sort(key=lambda row: (int(row["buy_price"]), age_hours(row.get("price_updated_at")) or 9999, -int(row.get("stock") or 0)))
    sell_rows.sort(key=lambda row: (-int(row["sell_price"]), -int(row.get("demand") or 0), age_hours(row.get("price_updated_at")) or 9999))

    routes = []
    for source in buy_rows[:16]:
        for target in sell_rows[:16]:
            candidate = build_route_candidate(source, target, market_filters, player_position, permits)
            if candidate:
                routes.append(candidate)
    routes.sort(key=lambda row: (row["route_score"], row["profit_per_hour"], row["trip_profit"], row["unit_profit"]), reverse=True)
    history = repo.commodity_history(resolved["symbol"], limit=32)
    best_buy = summarize_market_offer(buy_rows[0], player_position, mode="buy", owned_permits=permits) if buy_rows else None
    alternate_sell_rows = [row for row in sell_rows if not best_buy or row.get("market_id") != best_buy.get("market_id")]
    top_sell_rows = alternate_sell_rows
    best_sell = summarize_market_offer(top_sell_rows[0], player_position, mode="sell", owned_permits=permits) if top_sell_rows else None
    best_near_buy = select_best_local_buy(buy_rows[:20], market_filters, player_position, permits) if buy_rows else None
    best_live_sell = select_best_local_sell(top_sell_rows[:20], market_filters, player_position, permits) if top_sell_rows else None
    best_route = routes[0] if routes else None
    route_views = select_route_views(routes, {"current_system": repo.get_state("current_system"), "current_market_id": repo.get_state("current_market_id")})

    return {
        "query": query,
        "resolved": True,
        "symbol": resolved["symbol"],
        "commodity_name": resolved["commodity_name"],
        "selection_context": {
            "origin": origin_context,
            "target": target_context,
        },
        "best_buys": [summarize_market_offer(row, player_position, mode="buy", owned_permits=permits) for row in buy_rows[:8]],
        "best_sells": [summarize_market_offer(row, player_position, mode="sell", owned_permits=permits) for row in top_sell_rows[:8]],
        "best_routes": routes[:8],
        "history": history,
        "fallback_used": fallback_used,
        "fallback_buy_used": fallback_buy_used,
        "fallback_sell_used": fallback_sell_used,
        "sell_same_market_only": bool(sell_rows) and not bool(top_sell_rows),
        "route_views": route_views,
        "decision_cards": {
            "cheapest_buy": best_buy,
            "nearest_buy": best_near_buy,
            "highest_sell": best_sell,
            "live_sell": best_live_sell,
            **route_views,
        },
        "quick_trade": {
            "best_buy": best_buy,
            "best_near_buy": best_near_buy,
            "best_sell": best_sell,
            "best_live_sell": best_live_sell,
            "best_route": best_route,
            "spread": (int(best_sell["price"]) - int(best_buy["price"])) if best_buy and best_sell else None,
            "history_points": len(history),
        },
    }


def build_mission_intel(
    commodity_query: str | None,
    quantity: int,
    filters: TradeFilters,
    *,
    target_system: str | None = None,
    target_station: str | None = None,
    all_rows: list[dict[str, Any]] | None = None,
    player_position: dict[str, Any] | None = None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    requested_quantity = max(1, int(quantity or 1))
    resolved = repo.resolve_commodity(commodity_query)
    if not resolved:
        return {
            "query": commodity_query,
            "resolved": False,
            "commodity_name": None,
            "quantity": requested_quantity,
            "target_system": target_system,
            "target_station": target_station,
            "best_sources": [],
            "best_routes": [],
            "target": None,
            "history": [],
            "alternatives": [],
            "stock_status": None,
            "route_views": {},
        }

    if player_position is None:
        player_position = repo.system_position(repo.get_state("current_system"))
    permits = owned_permits if owned_permits is not None else known_owned_permits()
    rows, fallback_used = rows_for_symbol_with_fallback(resolved["symbol"], filters, permits, all_rows=all_rows)
    buy_rows = meaningful_buy_rows(rows, filters)
    sell_rows = meaningful_sell_rows(rows, filters)
    buy_rows.sort(key=lambda row: (int(row["buy_price"]), -(int(row.get("stock") or 0)), age_hours(row.get("price_updated_at")) or 9999))
    sell_rows.sort(key=lambda row: (-int(row["sell_price"]), -(int(row.get("demand") or 0)), age_hours(row.get("price_updated_at")) or 9999))

    resolved_target_system = repo.resolve_system(target_system) if target_system else None
    target_system_name = resolved_target_system.get("name") if resolved_target_system else target_system
    target = repo.find_station(system_name=target_system_name, station_name=target_station)
    if target is None and target_station:
        target = repo.resolve_station(target_station, system_name=target_system_name)
    if target is None and target_system:
        position = repo.system_position(target_system_name)
        if position:
            target = {
                "market_id": None,
                "system_name": target_system_name,
                "station_name": target_station or "Destination mission",
                "distance_to_arrival": None,
                "landing_pad": filters.min_pad_size,
                "has_market": 1,
                "is_planetary": 0,
                "is_odyssey": 0,
                "is_fleet_carrier": 0,
                "requires_permit": 0,
                "permit_name": None,
                "x": position.get("x"),
                "y": position.get("y"),
                "z": position.get("z"),
                "sell_price": 0,
            }

    sources = [summarize_purchase_plan(row, requested_quantity, player_position, owned_permits=permits) for row in buy_rows[:12]]
    routes: list[dict[str, Any]] = []
    if target is not None:
        for source in buy_rows[:20]:
            candidate = build_mission_delivery_candidate(source, target, requested_quantity, filters, player_position, permits)
            if candidate:
                routes.append(candidate)
    else:
        mission_filters = TradeFilters(
            cargo_capacity=requested_quantity,
            jump_range=filters.jump_range,
            max_age_hours=filters.max_age_hours,
            max_station_distance_ls=filters.max_station_distance_ls,
            min_profit_unit=0,
            min_buy_stock=filters.min_buy_stock,
            min_sell_demand=filters.min_sell_demand,
            min_pad_size=filters.min_pad_size,
            include_planetary=filters.include_planetary,
            include_settlements=filters.include_settlements,
            include_fleet_carriers=filters.include_fleet_carriers,
            no_surprise=filters.no_surprise,
            max_results=filters.max_results,
        )
        for source in buy_rows[:16]:
            for target_row in sell_rows[:16]:
                candidate = build_route_candidate(source, target_row, mission_filters, player_position, permits)
                if candidate:
                    candidate["units"] = min(candidate["units"], requested_quantity)
                    candidate["trip_profit"] = candidate["unit_profit"] * candidate["units"]
                    candidate["profit_per_hour"] = round(candidate["trip_profit"] * 60 / max(candidate["estimated_minutes"], 1), 2)
                    candidate["profit_per_minute"] = round(candidate["trip_profit"] / max(candidate["estimated_minutes"], 1), 2)
                    candidate["total_cost"] = int(candidate["source_buy_price"] or 0) * candidate["units"]
                    routes.append(candidate)
    routes.sort(key=lambda row: (row.get("route_score", 0), row.get("trip_profit", 0), -row.get("estimated_minutes", 0)), reverse=True)
    best_covered = max((item.get("units_covered", 0) for item in sources), default=0)
    stock_status = {
        "requested_units": requested_quantity,
        "max_covered_units": best_covered,
        "shortfall_units": max(0, requested_quantity - best_covered),
        "coverage_percent": clamp_score((best_covered / max(requested_quantity, 1)) * 100),
        "full_coverage": best_covered >= requested_quantity,
    }

    return {
        "query": commodity_query,
        "resolved": True,
        "symbol": resolved["symbol"],
        "commodity_name": resolved["commodity_name"],
        "quantity": requested_quantity,
        "target_system": target_system_name,
        "target_station": target_station,
        "target": target,
        "best_sources": sources[:8],
        "best_routes": routes[:8],
        "history": repo.commodity_history(resolved["symbol"], limit=24),
        "alternatives": [item for item in sources[1:8] if item.get("units_covered", 0) > 0],
        "fallback_used": fallback_used,
        "stock_status": stock_status,
        "route_views": select_route_views(routes, {"current_system": repo.get_state("current_system"), "current_market_id": repo.get_state("current_market_id")}),
    }


def build_watchlist(
    filters: TradeFilters,
    *,
    all_rows: list[dict[str, Any]] | None = None,
    player_position: dict[str, Any] | None = None,
    owned_permits: set[str] | None = None,
) -> list[dict[str, Any]]:
    memory = trader_memory_snapshot()
    favorite_symbols = [normalize_commodity_symbol(item.get("id")) for item in memory.get("favorites", {}).get("commodity", [])]
    recent_symbols = [normalize_commodity_symbol(item.get("id")) for item in memory.get("recents", {}).get("commodity", [])]
    symbols: list[str] = []
    for symbol in [*favorite_symbols, *recent_symbols, *WATCHLIST_SYMBOLS]:
        normalized = normalize_commodity_symbol(symbol)
        if normalized and normalized not in symbols:
            symbols.append(normalized)
    entries = []
    for symbol in symbols[:8]:
        intel = build_commodity_intel(
            symbol,
            filters,
            all_rows=all_rows,
            player_position=player_position,
            owned_permits=owned_permits,
        )
        if not intel.get("resolved"):
            continue
        best_buy = intel["best_buys"][0] if intel["best_buys"] else None
        best_sell = intel["best_sells"][0] if intel["best_sells"] else None
        best_route = intel["best_routes"][0] if intel["best_routes"] else None
        entries.append(
            {
                "symbol": intel["symbol"],
                "commodity_name": intel["commodity_name"],
                "best_buy": best_buy,
                "best_sell": best_sell,
                "best_route": best_route,
                "spread": intel.get("quick_trade", {}).get("spread"),
                "favorite": any(item.get("id") == intel["symbol"] for item in memory.get("favorites", {}).get("commodity", [])),
            }
        )
    return entries


def select_route_views(routes: list[dict[str, Any]], player: dict[str, Any] | None = None) -> dict[str, Any]:
    if not routes:
        return {
            "best_margin": None,
            "best_margin_per_minute": None,
            "best_trip_profit": None,
            "best_safe_route": None,
            "best_from_current_system": None,
            "best_from_current_station": None,
        }
    current_system = str((player or {}).get("current_system") or "").strip()
    current_market_id = (player or {}).get("current_market_id")
    safe_routes = [row for row in routes if row.get("confidence_score", 0) >= 82 and row.get("freshness_hours", 999) <= 24]
    current_system_routes = [row for row in routes if current_system and row.get("source_system") == current_system]
    current_station_routes = [row for row in routes if current_market_id and row.get("source_market_id") == current_market_id]
    return {
        "best_margin": max(routes, key=lambda row: (row.get("unit_profit", 0), row.get("trip_profit", 0), row.get("route_score", 0))),
        "best_margin_per_minute": max(routes, key=lambda row: (row.get("profit_per_minute", 0), row.get("profit_per_hour", 0), row.get("route_score", 0))),
        "best_trip_profit": max(routes, key=lambda row: (row.get("trip_profit", 0), row.get("profit_per_hour", 0), row.get("route_score", 0))),
        "best_safe_route": max(safe_routes, key=lambda row: (row.get("route_score", 0), row.get("confidence_score", 0), row.get("trip_profit", 0))) if safe_routes else routes[0],
        "best_from_current_system": max(current_system_routes, key=lambda row: (row.get("route_score", 0), row.get("trip_profit", 0))) if current_system_routes else None,
        "best_from_current_station": max(current_station_routes, key=lambda row: (row.get("route_score", 0), row.get("trip_profit", 0))) if current_station_routes else None,
    }


def build_dashboard_decision_cards(
    rows: list[dict[str, Any]],
    routes: list[dict[str, Any]],
    filters: TradeFilters,
    player: dict[str, Any],
    player_position: dict[str, Any] | None,
    owned_permits: set[str] | None = None,
) -> dict[str, Any]:
    buy_rows = meaningful_buy_rows(rows, filters)
    sell_rows = meaningful_sell_rows(rows, filters)
    buy_rows.sort(key=lambda row: (int(row.get("buy_price") or 0), age_hours(row.get("price_updated_at")) or 9999))
    sell_rows.sort(key=lambda row: (-int(row.get("sell_price") or 0), -int(row.get("demand") or 0), age_hours(row.get("price_updated_at")) or 9999))
    best_buy_row = buy_rows[0] if buy_rows else None
    alternate_sell_rows = [row for row in sell_rows if not best_buy_row or row.get("market_id") != best_buy_row.get("market_id")]
    best_sell_row = alternate_sell_rows[0] if alternate_sell_rows else (sell_rows[0] if sell_rows else None)
    route_views = select_route_views(routes, player)
    return {
        "cheapest_buy": summarize_market_offer(best_buy_row, player_position, mode="buy", owned_permits=owned_permits) if best_buy_row else None,
        "nearest_buy": select_best_local_buy(buy_rows[:40], filters, player_position, owned_permits) if buy_rows else None,
        "highest_sell": summarize_market_offer(best_sell_row, player_position, mode="sell", owned_permits=owned_permits) if best_sell_row else None,
        "live_sell": select_best_local_sell(sell_rows[:40], filters, player_position, owned_permits) if sell_rows else None,
        **route_views,
    }


def build_trade_dashboard(
    filters: TradeFilters,
    *,
    player: dict[str, Any] | None = None,
    all_rows: list[dict[str, Any]] | None = None,
    owned_permits: set[str] | None = None,
    player_position: dict[str, Any] | None = None,
) -> dict[str, Any]:
    player = player or player_runtime_snapshot(repo.get_all_state())
    all_rows = all_rows if all_rows is not None else repo.filtered_trade_rows(filters)
    owned_permits = owned_permits if owned_permits is not None else known_owned_permits()
    if player_position is None:
        player_position = repo.system_position(player.get("current_system"))
    rows = [row for row in all_rows if station_allowed(row, filters, owned_permits)]
    exports_by_symbol: dict[str, list[dict[str, Any]]] = {}
    imports_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        symbol = row["commodity_symbol"]
        if int(row.get("buy_price") or 0) > 0 and int(row.get("stock") or 0) > 0:
            exports_by_symbol.setdefault(symbol, []).append(row)
        if int(row.get("sell_price") or 0) > 0 and int(row.get("demand") or 0) > 0:
            imports_by_symbol.setdefault(symbol, []).append(row)

    routes = []
    best_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for symbol, sources in exports_by_symbol.items():
        targets = imports_by_symbol.get(symbol, [])
        if not targets:
            continue
        for source in sources:
            for target in targets:
                route = build_route_candidate(source, target, filters, player_position, owned_permits)
                if not route:
                    continue
                routes.append(route)
                key = (source["market_id"], target["market_id"])
                if key not in best_by_pair or route["trip_profit"] > best_by_pair[key]["trip_profit"]:
                    best_by_pair[key] = route

    routes.sort(key=lambda row: (row["route_score"], row["profit_per_hour"], row["trip_profit"], row["unit_profit"]), reverse=True)

    loops = []
    seen: set[tuple[int, int]] = set()
    for (a, b), outbound in best_by_pair.items():
        reverse = best_by_pair.get((b, a))
        if not reverse:
            continue
        canonical = tuple(sorted((a, b)))
        if canonical in seen:
            continue
        seen.add(canonical)
        total_profit = outbound["trip_profit"] + reverse["trip_profit"]
        total_minutes = outbound["estimated_minutes"] + reverse["estimated_minutes"]
        loops.append(
            {
                "from_system": outbound["source_system"],
                "from_station": outbound["source_station"],
                "to_system": outbound["target_system"],
                "to_station": outbound["target_station"],
                "go_commodity": outbound["commodity_name"],
                "return_commodity": reverse["commodity_name"],
                "go_profit": outbound["trip_profit"],
                "return_profit": reverse["trip_profit"],
                "total_profit": total_profit,
                "profit_per_hour": round(total_profit * 60 / total_minutes, 2),
                "freshness_hours": max(outbound["freshness_hours"], reverse["freshness_hours"]),
                "confidence_score": clamp_score((outbound["confidence_score"] + reverse["confidence_score"]) / 2),
                "confidence_label": confidence_label(clamp_score((outbound["confidence_score"] + reverse["confidence_score"]) / 2)),
                "route_score": clamp_score((outbound["route_score"] + reverse["route_score"]) / 2),
            }
        )
    loops.sort(key=lambda row: (row["route_score"], row["profit_per_hour"], row["total_profit"]), reverse=True)

    return {
        "player": player,
        "routes": routes[: filters.max_results],
        "loops": loops[: filters.max_results],
        "route_views": select_route_views(routes, player),
        "dataset": {
            "rows": len(rows),
            "export_symbols": len(exports_by_symbol),
            "import_symbols": len(imports_by_symbol),
        },
        "decision_cards": build_dashboard_decision_cards(rows, routes, filters, player, player_position, owned_permits),
        "watchlist": build_watchlist(
            filters,
            all_rows=all_rows,
            player_position=player_position,
            owned_permits=owned_permits,
        ),
        "local_sync": repo.get_state("source_local_sync_stats", {}),
        "current_market": repo.current_market(),
        "knowledge": repo.knowledge(),
    }


SUGGESTION_TYPE_LABELS = {
    "system": "Système",
    "station": "Station",
    "commodity": "Marchandise",
    "module": "Module",
    "ship": "Vaisseau",
    "material": "Matériau",
    "economy": "Économie",
    "government": "Gouvernement",
    "security": "Sécurité",
    "commodity_category": "Catégorie",
    "term": "Terme",
    "library": "Bibliothèque FR",
}


def _memory_bonus(memory: dict[str, Any], kind: str, entity_id: str) -> tuple[int, bool, bool]:
    favorite, recent, usage_count = memory_flags(memory, kind, entity_id)
    bonus = (18 if favorite else 0) + (10 if recent else 0) + min(18, usage_count * 3)
    return bonus, favorite, recent


def _distance_bonus(distance_ly: float | None) -> int:
    if distance_ly is None:
        return 0
    return clamp_score(16 - min(float(distance_ly), 32.0) * 0.45, minimum=0, maximum=16)


def build_engine_status_from_values(
    rows: int,
    name_summary: dict[str, Any],
    local_status: dict[str, Any],
    current_market: dict[str, Any],
    current_system: str | None,
) -> dict[str, Any]:
    if rows < 500:
        phase = "bootstrapping"
        message = "Base locale en constitution"
    elif not local_status.get("running"):
        phase = "degraded"
        message = "Surveillance locale inactive"
    elif not current_system:
        phase = "waiting_position"
        message = "Position locale encore inconnue"
    elif not current_market.get("station_name"):
        phase = "waiting_market"
        message = "Marché courant en attente"
    else:
        phase = "ready"
        message = "Moteur trader prêt"
    return {
        "phase": phase,
        "ready": phase == "ready",
        "message": message,
        "market_rows": rows,
        "name_library_total": name_summary.get("total", 0),
        "current_system": current_system,
        "current_market": current_market.get("station_name"),
        "local_sync": local_status,
        "remote_seed_running": bool(background_flags.get("remote_seed_running")),
    }


def build_engine_status() -> dict[str, Any]:
    rows = repo.commodity_price_count()
    name_summary = repo.name_library_summary()
    local_status = local_sync_service.status() if "local_sync_service" in globals() else {"running": False}
    current_market = repo.current_market()
    current_system = repo.get_state("current_system")
    return build_engine_status_from_values(rows, name_summary, local_status, current_market, current_system)


def build_suggestions(
    query: str,
    *,
    scope: str = "universal",
    limit: int = 8,
    system_name: str | None = None,
) -> list[dict[str, Any]]:
    clean_query = (query or "").strip()
    if not clean_query:
        return []
    player = player_runtime_snapshot(repo.get_all_state())
    player_position = repo.system_position(player.get("current_system"))
    owned_permits = known_owned_permits()
    memory = get_trader_memory()
    desired_scope = (scope or "universal").strip().lower()
    resolved_system = repo.resolve_system(system_name) if system_name else None
    scoped_system_name = resolved_system.get("name") if resolved_system else system_name
    results: list[dict[str, Any]] = []

    def append_result(result: dict[str, Any], base_score: int, extra_score: int = 0) -> None:
        total = clamp_score(base_score + extra_score, minimum=0, maximum=200)
        if total <= 0:
            return
        result["relevance"] = total
        results.append(result)

    if desired_scope in {"system", "mission_system", "universal"}:
        for row in repo.systems_catalog():
            base, match_label, _ = best_variant_score(clean_query, row.get("name"), row.get("permit_name"))
            if base <= 0:
                continue
            distance_ly = euclidean_distance(row, player_position) if player_position else None
            memory_boost, favorite, recent = _memory_bonus(memory, "system", row["name"])
            badges = []
            if favorite:
                badges.append("Favori")
            if recent:
                badges.append("Récent")
            if row.get("requires_permit"):
                badges.append(f"Permis {row.get('permit_name') or row['name']}")
            else:
                badges.append("Accès libre")
            if distance_ly is not None:
                badges.append(f"{distance_ly:.1f} Ly")
            append_result(
                {
                    "kind": "system",
                    "entity_id": row["name"],
                    "label": row["name"],
                    "secondary": "Système",
                    "type_label": SUGGESTION_TYPE_LABELS["system"],
                    "match_label": match_label,
                    "distance_ly": distance_ly,
                    "distance_ls": None,
                    "favorite": favorite,
                    "recent": recent,
                    "badges": badges,
                    "meta": {
                        "system_name": row["name"],
                        "permit_name": row.get("permit_name"),
                    },
                },
                base,
                memory_boost + _distance_bonus(distance_ly) + (12 if row["name"] == player.get("current_system") else 0),
            )

    if desired_scope in {"station", "mission_station", "universal"}:
        for row in repo.stations_catalog():
            if scoped_system_name and normalize_search_text(row.get("system_name")) != normalize_search_text(scoped_system_name):
                continue
            base, match_label, _ = best_variant_score(
                clean_query,
                row.get("station_name"),
                f"{row.get('system_name')} {row.get('station_name')}",
                row.get("station_type"),
            )
            if base <= 0:
                continue
            distance_ly = euclidean_distance(row, player_position) if player_position else None
            memory_boost, favorite, recent = _memory_bonus(memory, "station", f"{row['system_name']}::{row['station_name']}")
            badges = station_badges(row, owned_permits)
            if favorite:
                badges.insert(0, "Favori")
            elif recent:
                badges.insert(0, "Récent")
            append_result(
                {
                    "kind": "station",
                    "entity_id": f"{row['system_name']}::{row['station_name']}",
                    "label": row["station_name"],
                    "secondary": row["system_name"],
                    "type_label": SUGGESTION_TYPE_LABELS["station"],
                    "match_label": match_label,
                    "distance_ly": distance_ly,
                    "distance_ls": row.get("distance_to_arrival"),
                    "favorite": favorite,
                    "recent": recent,
                    "badges": badges[:6],
                    "meta": {
                        "system_name": row["system_name"],
                        "station_name": row["station_name"],
                        "landing_pad": row.get("landing_pad"),
                        "station_type": row.get("station_type"),
                    },
                },
                base,
                memory_boost + _distance_bonus(distance_ly) + (10 if scoped_system_name and row["system_name"] == scoped_system_name else 0),
            )

    if desired_scope in {"commodity", "mission", "universal"}:
        commodity_aliases = {
            entry["lookup_key"]: entry.get("aliases", [])
            for entry in repo.name_entries_catalog("commodity")
        }
        for row in repo.commodities_catalog():
            aliases = commodity_aliases.get(row["symbol"], [])
            base, match_label, _ = best_variant_score(clean_query, row.get("symbol"), row.get("name_fr"), row.get("name"), *aliases)
            if base <= 0:
                continue
            memory_boost, favorite, recent = _memory_bonus(memory, "commodity", row["symbol"])
            badges = []
            if favorite:
                badges.append("Favori")
            elif recent:
                badges.append("Récent")
            if row.get("category"):
                badges.append(str(row["category"]).title())
            append_result(
                {
                    "kind": "commodity",
                    "entity_id": row["symbol"],
                    "label": row.get("name_fr") or row.get("name") or row["symbol"],
                    "secondary": row["symbol"],
                    "type_label": SUGGESTION_TYPE_LABELS["commodity"],
                    "match_label": match_label,
                    "distance_ly": None,
                    "distance_ls": None,
                    "favorite": favorite,
                    "recent": recent,
                    "badges": badges[:4],
                    "meta": {
                        "symbol": row["symbol"],
                        "category": row.get("category"),
                    },
                },
                base,
                memory_boost,
            )

    if desired_scope in {"module", "library", "universal"}:
        for row in repo.name_entries_catalog(None if desired_scope == "universal" else ("module" if desired_scope == "module" else None)):
            if desired_scope == "module" and row["entry_type"] != "module":
                continue
            base, match_label, _ = best_variant_score(clean_query, row.get("lookup_key"), row.get("name_fr"), row.get("name"), *(row.get("aliases") or []))
            if base <= 0:
                continue
            kind = "module" if row["entry_type"] == "module" else "library"
            memory_boost, favorite, recent = _memory_bonus(memory, kind if kind == "module" else "module", row["lookup_key"])
            badges = []
            if favorite:
                badges.append("Favori")
            elif recent:
                badges.append("Récent")
            if row.get("is_exact"):
                badges.append("Frontier")
            if row.get("source"):
                badges.append(str(row["source"]).replace("_", " "))
            append_result(
                {
                    "kind": kind,
                    "entity_id": row["lookup_key"],
                    "label": row.get("name_fr") or row.get("name") or row["lookup_key"],
                    "secondary": row["lookup_key"],
                    "type_label": SUGGESTION_TYPE_LABELS.get(row["entry_type"], SUGGESTION_TYPE_LABELS.get(kind, SUGGESTION_TYPE_LABELS["library"])),
                    "match_label": match_label,
                    "distance_ly": None,
                    "distance_ls": None,
                    "favorite": favorite,
                    "recent": recent,
                    "badges": badges[:4],
                    "meta": {
                        "entry_type": row["entry_type"],
                        "lookup_key": row["lookup_key"],
                    },
                },
                base,
                memory_boost + min(18, int(row.get("confidence") or 0) // 6),
            )

    results.sort(
        key=lambda row: (
            -int(row.get("relevance", 0)),
            -1 if row.get("favorite") else 0,
            -1 if row.get("recent") else 0,
            float(row.get("distance_ly")) if row.get("distance_ly") is not None else 9999.0,
            normalize_search_text(row.get("label", "")),
        )
    )
    return results[: max(1, min(int(limit or 8), 16))]


journal_service = JournalImportService(JOURNAL_DIR, repo)
name_library_service = NameLibraryService(JOURNAL_DIR, repo)
ardent_client = ArdentClient(repo)
spansh_client = SpanshClient(repo)
edsm_client = EDSMClient(repo)
eddn_listener = EDDNListener(repo)
local_sync_service = LocalRealtimeSyncService(JOURNAL_DIR, journal_service, repo, spansh_client, edsm_client)


class PlayerConfigRequest(BaseModel):
    cargo_capacity_override: int | None = Field(default=None, ge=0, le=5000)
    jump_range_override: float | None = Field(default=None, ge=0, le=500)
    preferred_pad_size: Literal["S", "M", "L"] = "M"


class SyncRegionRequest(BaseModel):
    center_system: str | None = None
    max_distance: int = Field(default=40, ge=1, le=500)
    max_days_ago: int = Field(default=7, ge=1, le=30)
    max_systems: int = Field(default=20, ge=1, le=80)


class RouteRequest(BaseModel):
    cargo_capacity: int | None = Field(default=None, ge=0, le=5000)
    jump_range: float | None = Field(default=None, ge=0, le=500)
    max_age_hours: float = Field(default=72, ge=0.1, le=168)
    max_station_distance_ls: int = Field(default=5000, ge=0, le=1000000)
    min_profit_unit: int = Field(default=1000, ge=0, le=1000000)
    min_buy_stock: int = Field(default=0, ge=0, le=1000000)
    min_sell_demand: int = Field(default=0, ge=0, le=1000000)
    min_pad_size: Literal["S", "M", "L"] = "M"
    include_planetary: bool = True
    include_settlements: bool = False
    include_fleet_carriers: bool = False
    no_surprise: bool = False
    max_results: int = Field(default=25, ge=5, le=100)


class MissionRequest(BaseModel):
    commodity_query: str = Field(min_length=1, max_length=120)
    quantity: int = Field(default=100, ge=1, le=50000)
    target_system: str | None = Field(default=None, max_length=120)
    target_station: str | None = Field(default=None, max_length=120)
    max_age_hours: float | None = Field(default=None, ge=0.1, le=168)


class LiveSnapshotRequest(BaseModel):
    route: RouteRequest | None = None
    commodity_query: str | None = Field(default=None, max_length=120)
    mission: MissionRequest | None = None


class TraderMemoryTrackRequest(BaseModel):
    kind: Literal["commodity", "system", "station", "module", "query"]
    entity_id: str = Field(min_length=1, max_length=220)
    label: str = Field(min_length=1, max_length=220)
    secondary: str | None = Field(default=None, max_length=220)
    extra: dict[str, Any] | None = None


class TraderFavoriteToggleRequest(BaseModel):
    kind: Literal["commodity", "system", "station", "module"]
    entity_id: str = Field(min_length=1, max_length=220)
    label: str = Field(min_length=1, max_length=220)
    secondary: str | None = Field(default=None, max_length=220)
    extra: dict[str, Any] | None = None


def default_route_request() -> RouteRequest:
    return RouteRequest(
        cargo_capacity=repo.get_state("cargo_capacity_override"),
        jump_range=repo.get_state("jump_range_override"),
        min_pad_size=repo.get_state("preferred_pad_size", "M"),
    )


def build_filters(payload: RouteRequest) -> TradeFilters:
    cargo_capacity = payload.cargo_capacity
    if cargo_capacity is None:
        cargo_capacity = repo.get_state("cargo_capacity_override")
    if cargo_capacity is None:
        cargo_capacity = repo.get_state("cargo_capacity", 0)
    if not cargo_capacity:
        cargo_capacity = 100

    jump_range = payload.jump_range
    if jump_range is None:
        jump_range = repo.get_state("jump_range_override")
    if jump_range is None:
        jump_range = repo.get_state("jump_range", 15)

    return TradeFilters(
        cargo_capacity=int(cargo_capacity or 0),
        jump_range=float(jump_range or 15),
        max_age_hours=payload.max_age_hours,
        max_station_distance_ls=payload.max_station_distance_ls,
        min_profit_unit=payload.min_profit_unit,
        min_buy_stock=payload.min_buy_stock,
        min_sell_demand=payload.min_sell_demand,
        min_pad_size=payload.min_pad_size,
        include_planetary=payload.include_planetary,
        include_settlements=payload.include_settlements,
        include_fleet_carriers=payload.include_fleet_carriers,
        no_surprise=payload.no_surprise,
        max_results=payload.max_results,
    )


def enrich_dashboard_payload(data: dict[str, Any], route_request: RouteRequest, owned_permits: set[str] | None = None) -> dict[str, Any]:
    permits = owned_permits if owned_permits is not None else known_owned_permits()
    permit_labels = known_owned_permit_labels()
    data["local_sync"] = local_sync_service.status()
    data["eddn"] = eddn_listener.status()
    data["nav_route"] = nav_route_payload()
    data["combat_support"] = combat_support_payload()
    data["name_library"] = repo.name_library_summary()
    data["engine_status"] = build_engine_status()
    data["trader_memory"] = trader_memory_snapshot()
    data["sources"] = sources_payload()
    data["defaults"] = {
        "max_distance": 40,
        "max_days_ago": 7,
        "max_systems": 20,
        "max_age_hours": 72,
        "max_station_distance_ls": 5000,
        "min_profit_unit": 1000,
        "min_buy_stock": 0,
        "min_sell_demand": 0,
        "max_results": 25,
        "preferred_pad_size": repo.get_state("preferred_pad_size", "M"),
        "no_surprise": False,
    }
    data["journal_dir"] = str(JOURNAL_DIR)
    data["game_dir"] = str(GAME_DIR) if GAME_DIR else None
    data["owned_permits"] = sorted(permits)
    data["owned_permit_labels"] = permit_labels
    return data


def sources_payload() -> dict[str, Any]:
    return {
        "journal_last_import": repo.get_state("source_journal_last_import"),
        "ardent_last_sync": repo.get_state("source_ardent_last_sync"),
        "spansh_last_refresh": repo.get_state("source_spansh_last_refresh"),
        "edsm_last_refresh": repo.get_state("source_edsm_last_refresh"),
        "eddn_last_refresh": repo.get_state("source_eddn_last_refresh"),
        "edsm_access_last_refresh": repo.get_state("source_edsm_access_last_refresh"),
        "local_last_poll": repo.get_state("source_local_last_poll"),
        "local_last_event": repo.get_state("source_local_last_event"),
    }


def nav_route_payload() -> dict[str, Any]:
    path = JOURNAL_DIR / "NavRoute.json"
    empty = {
        "available": False,
        "updated_at": None,
        "age_minutes": None,
        "current_system": repo.get_state("current_system"),
        "first_system": None,
        "destination_system": None,
        "step_count": 0,
        "hops": 0,
        "direct_distance_ly": None,
        "route_preview": [],
        "truncated": False,
    }
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return empty

    raw_steps = data.get("Route") or data.get("route") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        return empty

    steps: list[dict[str, Any]] = []
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            continue
        system_name = str(raw_step.get("StarSystem") or "").strip()
        if not system_name:
            continue
        coords = raw_step.get("StarPos") or raw_step.get("Starpos") or []
        steps.append(
            {
                "system_name": system_name,
                "star_class": raw_step.get("StarClass"),
                "x": coords[0] if len(coords) > 0 else None,
                "y": coords[1] if len(coords) > 1 else None,
                "z": coords[2] if len(coords) > 2 else None,
            }
        )
    if not steps:
        return empty

    updated_at = data.get("timestamp")
    if not updated_at:
        try:
            updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            updated_at = None

    current_system = str(repo.get_state("current_system") or "").strip() or None
    current_position = repo.system_position(current_system) if current_system else None
    first = steps[0]
    destination = steps[-1]
    origin_position = current_position or {
        "x": first.get("x"),
        "y": first.get("y"),
        "z": first.get("z"),
    }
    destination_position = {
        "x": destination.get("x"),
        "y": destination.get("y"),
        "z": destination.get("z"),
    }
    if any(value is None for value in destination_position.values()):
        destination_position = repo.system_position(destination["system_name"]) or destination_position

    direct_distance = None
    if origin_position and destination_position and not any(value is None for value in destination_position.values()):
        direct_distance = euclidean_distance(origin_position, destination_position)

    preview = [
        {
            "system_name": row["system_name"],
            "star_class": row.get("star_class"),
        }
        for row in steps[:10]
    ]
    return {
        "available": True,
        "updated_at": updated_at,
        "age_minutes": age_minutes(updated_at),
        "current_system": current_system,
        "first_system": first["system_name"],
        "destination_system": destination["system_name"],
        "step_count": len(steps),
        "hops": max(0, len(steps) - 1),
        "direct_distance_ly": direct_distance,
        "route_preview": preview,
        "truncated": len(steps) > len(preview),
    }


def station_services(row: dict[str, Any]) -> set[str]:
    raw = row.get("services_json")
    if not raw:
        return set()
    if isinstance(raw, list):
        return {str(item).strip().lower() for item in raw if str(item).strip()}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(data, list):
        return set()
    return {str(item).strip().lower() for item in data if str(item).strip()}


def combat_station_sort_key(row: dict[str, Any], current_system: str | None = None) -> tuple[int, float, float, float]:
    same_system = (
        0
        if current_system
        and normalize_search_text(row.get("system_name")) == normalize_search_text(current_system)
        else 1
    )
    distance_ly = float(row.get("distance_ly")) if row.get("distance_ly") is not None else 999999.0
    distance_ls = float(row.get("distance_ls")) if row.get("distance_ls") is not None else 999999999.0
    freshness = float(row.get("freshness_hours")) if row.get("freshness_hours") is not None else 999999.0
    return (same_system, distance_ly, distance_ls, freshness)


def combat_support_payload(limit: int = 10) -> dict[str, Any]:
    current_system = str(repo.get_state("current_system") or "").strip() or None
    player_position = repo.system_position(current_system) if current_system else None
    preferred_pad = str(repo.get_state("preferred_pad_size", "M") or "M").upper()
    permits = known_owned_permits()
    with repo.connect() as conn:
        rows = conn.execute(
            """
            SELECT
                st.market_id,
                st.system_name,
                st.name AS station_name,
                st.type AS station_type,
                st.distance_to_arrival,
                st.landing_pad,
                st.has_market,
                st.is_planetary,
                st.is_odyssey,
                st.is_fleet_carrier,
                st.services_json,
                st.updated_at,
                sy.x,
                sy.y,
                sy.z,
                sy.requires_permit,
                sy.permit_name
            FROM stations st
            LEFT JOIN systems sy ON sy.name = st.system_name
            ORDER BY st.updated_at DESC, st.name COLLATE NOCASE ASC
            """
        ).fetchall()

    candidates: list[dict[str, Any]] = []
    for raw_row in rows:
        row = dict(raw_row)
        if PAD_RANK.get(row.get("landing_pad") or "?", 0) < PAD_RANK.get(preferred_pad, 0):
            continue
        if not station_accessible(row, permits):
            continue
        services = station_services(row)
        has_restock = "restock" in services
        has_repair = "repair" in services
        has_refuel = "refuel" in services
        if not any([has_restock, has_repair, has_refuel]):
            continue
        distance_ly = euclidean_distance(row, player_position) if player_position else None
        badges = [f"Pad {row.get('landing_pad') or '?'}"]
        if has_restock:
            badges.append("Munitions")
        if has_repair:
            badges.append("Reparation")
        if has_refuel:
            badges.append("Refuel")
        candidates.append(
            {
                "market_id": row.get("market_id"),
                "system_name": row.get("system_name"),
                "station_name": row.get("station_name"),
                "station_type": row.get("station_type"),
                "distance_ly": distance_ly,
                "distance_ls": row.get("distance_to_arrival"),
                "same_system": bool(
                    current_system
                    and normalize_search_text(row.get("system_name")) == normalize_search_text(current_system)
                ),
                "landing_pad": row.get("landing_pad"),
                "has_restock": has_restock,
                "has_repair": has_repair,
                "has_refuel": has_refuel,
                "services": sorted(services),
                "badges": badges,
                "updated_at": row.get("updated_at"),
                "freshness_hours": age_hours(row.get("updated_at")),
                "accessibility": station_accessibility_label(row, permits),
            }
        )

    candidates.sort(key=lambda row: combat_station_sort_key(row, current_system))

    def nearest_for(service_key: str) -> dict[str, Any] | None:
        service_rows = [row for row in candidates if row.get(service_key)]
        if not service_rows:
            return None
        service_rows.sort(key=lambda row: combat_station_sort_key(row, current_system))
        return service_rows[0]

    best_restock = nearest_for("has_restock")
    best_repair = nearest_for("has_repair")
    best_refuel = nearest_for("has_refuel")
    return {
        "current_system": current_system,
        "preferred_pad_size": preferred_pad,
        "best_restock": best_restock,
        "best_repair": best_repair,
        "best_refuel": best_refuel,
        "stations": candidates[: max(3, min(int(limit or 10), 20))],
    }


def local_pulse_payload() -> dict[str, Any]:
    player = player_runtime_snapshot(repo.get_all_state())
    local_sync = local_sync_service.status()
    current_market = repo.current_market()
    name_library = repo.name_library_summary()
    market_rows = repo.commodity_price_count()
    current_system = player.get("current_system") or repo.get_state("current_system")
    permit_labels = known_owned_permit_labels()
    return {
        "player": player,
        "current_market": current_market,
        "local_sync": local_sync,
        "eddn": eddn_listener.status(),
        "name_library": name_library,
        "engine_status": build_engine_status_from_values(market_rows, name_library, local_sync, current_market, current_system),
        "sources": sources_payload(),
        "nav_route": nav_route_payload(),
        "combat_support": combat_support_payload(),
        "journal_dir": str(JOURNAL_DIR),
        "game_dir": str(GAME_DIR) if GAME_DIR else None,
        "owned_permits": sorted(known_owned_permits()),
        "owned_permit_labels": permit_labels,
        "dataset": {
            "rows": market_rows,
        },
    }


def live_snapshot_cache_key(payload: LiveSnapshotRequest) -> str:
    return json.dumps(payload.model_dump(mode="json", exclude_none=False), ensure_ascii=False, sort_keys=True)


def get_cached_live_snapshot(key: str, *, max_age_seconds: float) -> dict[str, Any] | None:
    with snapshot_cache_lock:
        cached = snapshot_cache.get(key)
    if not cached:
        return None
    cached_at, value = cached
    if time.monotonic() - cached_at > max_age_seconds:
        return None
    return value


def store_cached_live_snapshot(key: str, value: dict[str, Any]) -> None:
    with snapshot_cache_lock:
        snapshot_cache[key] = (time.monotonic(), value)
        if len(snapshot_cache) > 12:
            oldest_key = min(snapshot_cache.items(), key=lambda item: item[1][0])[0]
            snapshot_cache.pop(oldest_key, None)


def dashboard_payload(route_request: RouteRequest | None = None) -> dict[str, Any]:
    payload = route_request or default_route_request()
    filters = build_filters(payload)
    data = build_trade_dashboard(filters)
    return enrich_dashboard_payload(data, payload)


def build_live_snapshot_payload(payload: LiveSnapshotRequest | None = None) -> dict[str, Any]:
    snapshot = payload or LiveSnapshotRequest()
    route_request = snapshot.route or default_route_request()
    filters = build_filters(route_request)
    player = player_runtime_snapshot(repo.get_all_state())
    all_rows = repo.filtered_trade_rows(filters)
    owned_permits = known_owned_permits()
    player_position = repo.system_position(player.get("current_system"))

    dashboard = build_trade_dashboard(
        filters,
        player=player,
        all_rows=all_rows,
        owned_permits=owned_permits,
        player_position=player_position,
    )
    dashboard = enrich_dashboard_payload(dashboard, route_request, owned_permits)

    commodity_query = snapshot.commodity_query
    if commodity_query is None:
        commodity_query = player.get("focus_commodity") or repo.get_state("focus_commodity") or "gold"
    commodity_intel = build_commodity_intel(
        commodity_query,
        filters,
        all_rows=all_rows,
        player_position=player_position,
        owned_permits=owned_permits,
    )

    mission_payload = snapshot.mission
    mission_query = commodity_query
    mission_quantity = max(1, int(player.get("cargo_capacity_override") or player.get("cargo_capacity") or filters.cargo_capacity or 100))
    mission_target_system = None
    mission_target_station = None
    if mission_payload is not None:
        mission_query = mission_payload.commodity_query
        mission_quantity = mission_payload.quantity
        mission_target_system = mission_payload.target_system
        mission_target_station = mission_payload.target_station
    mission_intel = build_mission_intel(
        mission_query,
        mission_quantity,
        filters,
        target_system=mission_target_system,
        target_station=mission_target_station,
        all_rows=all_rows,
        player_position=player_position,
        owned_permits=owned_permits,
    )
    return {
        "dashboard": dashboard,
        "commodity_intel": commodity_intel,
        "mission_intel": mission_intel,
    }


async def startup_seed_remote_data() -> None:
    background_flags["remote_seed_running"] = True
    try:
        current_system = str(repo.get_state("current_system") or "").strip()
        if not current_system:
            return
        current_market_id = repo.get_state("current_market_id")
        existing_rows = repo.commodity_price_count()
        last_sync = repo.get_state("source_ardent_last_sync")
        last_sync_age = age_hours(last_sync) or 9999
        if current_market_id:
            logger.info("Startup current-market refresh for %s", current_market_id)
            try:
                await asyncio.to_thread(spansh_client.refresh_station, int(current_market_id))
            except Exception:
                logger.exception("Startup Spansh refresh failed for market %s", current_market_id)
            try:
                await asyncio.to_thread(edsm_client.refresh_market, int(current_market_id))
            except Exception:
                logger.exception("Startup EDSM refresh failed for market %s", current_market_id)
            try:
                await asyncio.to_thread(edsm_client.refresh_system_accesses, [current_system])
            except Exception:
                logger.exception("Startup access refresh failed for %s", current_system)
            return
        if existing_rows > 0 and last_sync_age <= 12.0:
            return
        logger.info("Startup remote seed sync for %s", current_system)
        await ardent_client.sync_region(current_system, 5, 1, 2)
        try:
            await asyncio.to_thread(edsm_client.refresh_system_accesses, [current_system])
        except Exception:
            logger.exception("Startup access refresh failed for %s", current_system)
    except Exception:
        logger.exception("Startup remote seed sync failed")
    finally:
        background_flags["remote_seed_running"] = False


async def delayed_background_startup() -> None:
    await asyncio.sleep(BACKGROUND_START_DELAY_SECONDS)
    await startup_seed_remote_data()


app = FastAPI(title="Elite55")
app.mount("/static", StaticFiles(directory=APP_DIR / "app" / "static"), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "app" / "templates"))


@app.on_event("startup")
async def startup_event() -> None:
    try:
        await asyncio.to_thread(local_sync_service.bootstrap)
    except Exception:
        logger.exception("Initial local bootstrap failed")
    await local_sync_service.start()
    if repo.name_library_summary().get("total", 0) == 0:
        asyncio.create_task(asyncio.to_thread(name_library_service.refresh))
    asyncio.create_task(delayed_background_startup())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await local_sync_service.stop()
    eddn_listener.stop()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"request": request, "app_name": "Elite55"},
    )


@app.get("/api/health")
async def api_health() -> dict[str, Any]:
    return {
        "ok": True,
        "build_token": os.environ.get("ELITE55_BUILD_TOKEN"),
        "engine_status": build_engine_status(),
        "market_rows": repo.commodity_price_count(),
        "name_library_total": repo.name_library_summary().get("total", 0),
    }


@app.get("/api/dashboard")
async def api_dashboard() -> dict[str, Any]:
    return dashboard_payload()


@app.get("/api/local-pulse")
async def api_local_pulse() -> dict[str, Any]:
    return {"ok": True, "dashboard": local_pulse_payload()}


@app.get("/api/suggest")
async def api_suggest(q: str, scope: str = "universal", limit: int = 8, system_name: str | None = None) -> dict[str, Any]:
    return {
        "query": q,
        "scope": scope,
        "results": build_suggestions(q, scope=scope, limit=limit, system_name=system_name),
        "engine_status": build_engine_status(),
    }


@app.get("/api/trader-memory")
async def api_trader_memory() -> dict[str, Any]:
    return trader_memory_snapshot()


@app.post("/api/trader-memory/track")
async def api_trader_memory_track(payload: TraderMemoryTrackRequest) -> dict[str, Any]:
    remember_trader_selection(payload.kind, payload.entity_id, payload.label, secondary=payload.secondary, extra=payload.extra)
    return trader_memory_snapshot()


@app.post("/api/trader-memory/toggle-favorite")
async def api_trader_toggle_favorite(payload: TraderFavoriteToggleRequest) -> dict[str, Any]:
    return toggle_trader_favorite(payload.kind, payload.entity_id, payload.label, secondary=payload.secondary, extra=payload.extra)


@app.post("/api/import/journals")
async def api_import_journals() -> dict[str, Any]:
    stats = journal_service.import_all()
    current_system = repo.get_state("current_system")
    if current_system:
        try:
            stats["access"] = await asyncio.to_thread(edsm_client.refresh_system_accesses, [str(current_system)])
        except Exception:
            stats["access"] = {"systems_checked": 0, "systems_blocked": 0, "errors": ["current_system: access lookup failed"]}
    market_id = repo.get_state("current_market_id")
    if market_id:
        try:
            stats["spansh_rows"] = spansh_client.refresh_station(int(market_id))
        except Exception:
            stats["spansh_rows"] = 0
        try:
            stats["edsm_rows"] = edsm_client.refresh_market(int(market_id))
        except Exception:
            stats["edsm_rows"] = 0
    stats["name_library"] = name_library_service.refresh()
    return {"ok": True, "stats": stats, "dashboard": dashboard_payload()}


@app.post("/api/names/refresh")
async def api_refresh_names() -> dict[str, Any]:
    stats = name_library_service.refresh()
    return {
        "ok": True,
        "stats": stats,
        "summary": repo.name_library_summary(),
        "results": repo.search_name_library(limit=40),
    }


@app.get("/api/names")
async def api_names(q: str = "", entry_type: str | None = None, limit: int = 60) -> dict[str, Any]:
    return {
        "summary": repo.name_library_summary(),
        "results": repo.search_name_library(query=q, entry_type=entry_type, limit=limit),
    }


@app.post("/api/sync/ardent")
async def api_sync_ardent(payload: SyncRegionRequest) -> dict[str, Any]:
    center_system = payload.center_system or repo.get_state("current_system")
    if not center_system:
        raise HTTPException(status_code=400, detail="Aucun système courant connu. Importe d'abord les journaux.")
    resolved_center = repo.resolve_system(center_system)
    center_system = resolved_center.get("name") if resolved_center else center_system
    remember_trader_selection("system", center_system, center_system)
    stats = await ardent_client.sync_region(
        center_system=center_system,
        max_distance=payload.max_distance,
        max_days_ago=payload.max_days_ago,
        max_systems=payload.max_systems,
    )
    try:
        stats["access"] = await asyncio.to_thread(edsm_client.refresh_system_accesses, stats.get("systems_considered", []))
    except Exception:
        stats["access"] = {"systems_checked": 0, "systems_blocked": 0, "errors": ["region: access lookup failed"]}
    return {"ok": True, "stats": stats, "dashboard": dashboard_payload()}


@app.post("/api/refresh/current-market")
async def api_refresh_current_market() -> dict[str, Any]:
    market_id = repo.get_state("current_market_id")
    if not market_id:
        raise HTTPException(status_code=400, detail="Aucun marché courant connu.")
    stats = {"spansh_rows": 0, "edsm_rows": 0}
    try:
        stats["spansh_rows"] = spansh_client.refresh_station(int(market_id))
    except Exception:
        pass
    try:
        stats["edsm_rows"] = edsm_client.refresh_market(int(market_id))
    except Exception:
        pass
    current_system = repo.get_state("current_system")
    if current_system:
        try:
            stats["access"] = await asyncio.to_thread(edsm_client.refresh_system_accesses, [str(current_system)])
        except Exception:
            stats["access"] = {"systems_checked": 0, "systems_blocked": 0, "errors": ["current_system: access lookup failed"]}
    return {"ok": True, "stats": stats, "dashboard": dashboard_payload()}


@app.get("/api/commodity-intel")
async def api_commodity_intel(
    q: str,
    max_age_hours: float | None = None,
    origin_system: str | None = None,
    origin_station: str | None = None,
    target_system: str | None = None,
    target_station: str | None = None,
) -> dict[str, Any]:
    repo.set_state("focus_commodity", normalize_commodity_symbol(q) or q)
    resolved = repo.resolve_commodity(q)
    if resolved:
        remember_trader_selection("commodity", resolved["symbol"], resolved["commodity_name"])
    remember_trader_query(q)
    payload = default_route_request()
    if max_age_hours is not None:
        payload.max_age_hours = max_age_hours
    return build_commodity_intel(
        q,
        build_filters(payload),
        origin_system=origin_system,
        origin_station=origin_station,
        target_system=target_system,
        target_station=target_station,
    )


@app.post("/api/live-snapshot")
async def api_live_snapshot(payload: LiveSnapshotRequest) -> dict[str, Any]:
    if payload.commodity_query:
        repo.set_state("focus_commodity", normalize_commodity_symbol(payload.commodity_query) or payload.commodity_query)
    if payload.mission and payload.mission.commodity_query:
        repo.set_state("mission_commodity", normalize_commodity_symbol(payload.mission.commodity_query) or payload.mission.commodity_query)
    cache_key = live_snapshot_cache_key(payload)
    fresh = get_cached_live_snapshot(cache_key, max_age_seconds=SNAPSHOT_CACHE_TTL_SECONDS)
    if fresh is not None:
        return fresh
    if background_flags.get("remote_seed_running"):
        stale = get_cached_live_snapshot(cache_key, max_age_seconds=SNAPSHOT_CACHE_BUSY_STALE_SECONDS)
        if stale is not None:
            return stale
    result = build_live_snapshot_payload(payload)
    store_cached_live_snapshot(cache_key, result)
    return result


@app.post("/api/mission-intel")
async def api_mission_intel(payload: MissionRequest) -> dict[str, Any]:
    repo.set_state("mission_commodity", normalize_commodity_symbol(payload.commodity_query) or payload.commodity_query)
    route_request = default_route_request()
    if payload.max_age_hours is not None:
        route_request.max_age_hours = payload.max_age_hours
    result = build_mission_intel(
        payload.commodity_query,
        payload.quantity,
        build_filters(route_request),
        target_system=payload.target_system,
        target_station=payload.target_station,
    )
    if result.get("resolved"):
        remember_trader_selection("commodity", result["symbol"], result["commodity_name"])
    if result.get("target_system"):
        remember_trader_selection("system", result["target_system"], result["target_system"])
    if result.get("target_station"):
        remember_trader_selection(
            "station",
            f"{result.get('target_system') or ''}::{result['target_station']}",
            result["target_station"],
            secondary=result.get("target_system"),
        )
    remember_mission_plan(
        payload.commodity_query,
        payload.quantity,
        commodity_name=result.get("commodity_name"),
        target_system=result.get("target_system"),
        target_station=result.get("target_station"),
    )
    return result


@app.post("/api/eddn/start")
async def api_eddn_start() -> dict[str, Any]:
    return {"ok": True, "status": eddn_listener.start()}


@app.post("/api/eddn/stop")
async def api_eddn_stop() -> dict[str, Any]:
    return {"ok": True, "status": eddn_listener.stop()}


@app.post("/api/player-config")
async def api_player_config(payload: PlayerConfigRequest) -> dict[str, Any]:
    repo.set_states(
        {
            "cargo_capacity_override": payload.cargo_capacity_override,
            "jump_range_override": payload.jump_range_override,
            "preferred_pad_size": payload.preferred_pad_size,
        }
    )
    dashboard = dashboard_payload()
    remember_ship_profile(dashboard["player"])
    return {"ok": True, "dashboard": dashboard}


@app.post("/api/routes")
async def api_routes(payload: RouteRequest) -> dict[str, Any]:
    return {"ok": True, "dashboard": dashboard_payload(payload)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8899, reload=False)
