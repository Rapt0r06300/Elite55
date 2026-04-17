from __future__ import annotations

import html
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import uvicorn
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMessageBox, QPushButton, QProgressBar, QVBoxLayout, QWidget
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


BOOT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
LOG_PATH = BOOT_ROOT / "elite_plug_desktop.log"

logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("elite_plug")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)


HOST = "127.0.0.1"
PREFERRED_PORT = 8899
STARTUP_TIMEOUT_SECONDS = 45
CHECK_INTERVAL_MS = 250
_ASGI_APP = None
APP_NAME = "Elite55"
VC_REDIST_X64_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VC_REDIST_REG_PATH = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"


def get_asgi_app():
    global _ASGI_APP
    if _ASGI_APP is not None:
        return _ASGI_APP
    try:
        from app.main import app as loaded_app
    except Exception:
        logger.exception("Impossible d'importer app.main")
        raise
    _ASGI_APP = loaded_app
    return _ASGI_APP


def runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def current_build_token() -> str:
    target = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve()
    try:
        stat = target.stat()
        return f"{target.name}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        return f"{target.name}:unknown"


BUILD_TOKEN = current_build_token()


def configure_runtime_environment() -> None:
    if os.environ.get("ELITE55_SAFE_RENDER", "").strip() != "1":
        return
    existing_flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    requested_flags = ["--disable-gpu", "--disable-gpu-compositing"]
    for flag in requested_flags:
        if flag not in existing_flags:
            existing_flags = f"{existing_flags} {flag}".strip()
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = existing_flags
    os.environ.setdefault("QT_OPENGL", "software")


def read_vc_redist_state() -> dict[str, object]:
    if winreg is None:
        return {"installed": True, "version": None}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, VC_REDIST_REG_PATH) as key:
            installed = int(winreg.QueryValueEx(key, "Installed")[0]) == 1
            version = str(winreg.QueryValueEx(key, "Version")[0] or "").strip()
            major = int(winreg.QueryValueEx(key, "Major")[0] or 0)
            minor = int(winreg.QueryValueEx(key, "Minor")[0] or 0)
            bld = int(winreg.QueryValueEx(key, "Bld")[0] or 0)
            return {
                "installed": installed,
                "version": version or f"{major}.{minor}.{bld}",
            }
    except OSError:
        return {"installed": False, "version": None}


def ensure_windows_prerequisites(status_callback: Callable[[str], None] | None = None) -> dict[str, object]:
    def report(message: str) -> None:
        logger.info(message)
        if status_callback is not None:
            status_callback(message)

    state = read_vc_redist_state()
    if state.get("installed"):
        report(f"Runtime Microsoft detecte ({state.get('version') or 'version inconnue'}).")
        return {"ok": True, "installed": False, "version": state.get("version")}

    report("Runtime Microsoft manquant, installation automatique en cours...")
    temp_installer = Path(tempfile.gettempdir()) / "elite55_vc_redist_x64.exe"
    try:
        urllib.request.urlretrieve(VC_REDIST_X64_URL, temp_installer)
        result = subprocess.run(
            [str(temp_installer), "/install", "/quiet", "/norestart"],
            check=False,
            timeout=900,
        )
        if result.returncode not in {0, 1638, 3010}:
            raise RuntimeError(f"vc_redist.x64.exe a echoue avec le code {result.returncode}")
        refreshed = read_vc_redist_state()
        report("Runtime Microsoft installe ou deja present.")
        return {"ok": True, "installed": True, "version": refreshed.get("version"), "exit_code": result.returncode}
    finally:
        try:
            temp_installer.unlink(missing_ok=True)
        except OSError:
            logger.warning("Impossible de supprimer l'installateur temporaire %s", temp_installer)


def build_server_url(port: int) -> str:
    return f"http://{HOST}:{int(port)}"


def build_health_url(port: int) -> str:
    return f"{build_server_url(port)}/api/health"


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, int(port))) == 0


def server_ready(port: int, expected_build_token: str | None = None) -> bool:
    try:
        with urllib.request.urlopen(build_health_url(port), timeout=1.5) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if not payload.get("ok"):
                return False
            if expected_build_token and payload.get("build_token") != expected_build_token:
                return False
            return True
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


class BackendServer(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = int(port)
        self.server: uvicorn.Server | None = None
        self.start_error: Exception | None = None

    def run(self) -> None:
        logger.info("BackendServer.run start on port %s", self.port)
        try:
            config = uvicorn.Config(
                get_asgi_app(),
                host=HOST,
                port=self.port,
                reload=False,
                log_level="warning",
                log_config=None,
                access_log=False,
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception:
            self.start_error = sys.exc_info()[1]
            logger.exception("Echec du serveur local embarque")
            raise
        finally:
            logger.info("BackendServer.run stop on port %s", self.port)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True


class ElitePage(QWebEnginePage):
    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool) -> bool:  # type: ignore[override]
        if url.scheme() in {"http", "https"} and url.host() not in {"127.0.0.1", "localhost"}:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message: str, line_number: int, source_id: str) -> None:  # type: ignore[override]
        logger.info("JS console [%s] %s (%s:%s)", level, message, source_id, line_number)
        super().javaScriptConsoleMessage(level, message, line_number, source_id)


class LoadingWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(520, 260)

        title = QLabel(APP_NAME)
        title.setObjectName("loading-title")

        subtitle = QLabel("Demarrage du moteur commerce, de la base locale et des flux temps reel...")
        subtitle.setObjectName("loading-subtitle")
        subtitle.setWordWrap(True)

        self.message = QLabel("Initialisation en cours")
        self.message.setObjectName("loading-message")
        self.message.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)

        self.retry_button = QPushButton("Reessayer")
        self.retry_button.hide()

        layout = QVBoxLayout()
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)
        layout.addWidget(self.message)
        layout.addWidget(self.progress)
        layout.addWidget(self.retry_button)
        self.setLayout(layout)

        self.setStyleSheet(
            """
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #08131d, stop:1 #13263a);
                color: #eef5ff;
                font-family: Bahnschrift, "Segoe UI Variable", "Trebuchet MS", sans-serif;
            }
            QLabel#loading-title {
                font-size: 24px;
                font-weight: 700;
                color: #f2b248;
            }
            QLabel#loading-subtitle {
                font-size: 13px;
                color: #95abc0;
            }
            QLabel#loading-message {
                font-size: 14px;
                color: #dceaf9;
            }
            QProgressBar {
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 999px;
                background: rgba(255, 255, 255, 0.05);
                min-height: 14px;
            }
            QProgressBar::chunk {
                border-radius: 999px;
                background: #60d8e7;
            }
            QPushButton {
                min-height: 38px;
                border-radius: 18px;
                padding: 0 16px;
                background: rgba(96, 216, 231, 0.15);
                border: 1px solid rgba(96, 216, 231, 0.4);
                color: #eef5ff;
                font: 600 13px Bahnschrift;
            }
            """
        )


class MainWindow(QMainWindow):
    def __init__(self, server_url: str, port: int) -> None:
        super().__init__()
        self.server_url = server_url
        self.port = int(port)
        self.setWindowTitle(APP_NAME)
        self.resize(1460, 920)
        self.setMinimumSize(1180, 760)

        self.browser = QWebEngineView()
        self.browser.setPage(ElitePage(self.browser))
        self.setCentralWidget(self.browser)

        toolbar = self.addToolBar("Navigation")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)

        action_home = QAction("Accueil", self)
        action_home.triggered.connect(self.reload_app)

        action_refresh = QAction("Actualiser", self)
        action_refresh.triggered.connect(self.reload_app)

        action_browser = QAction("Ouvrir dans le navigateur", self)
        action_browser.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(self.server_url)))

        toolbar.addAction(action_home)
        toolbar.addAction(action_refresh)
        toolbar.addSeparator()
        toolbar.addAction(action_browser)

        self.statusBar().showMessage("Pret")
        self.browser.loadStarted.connect(lambda: self.statusBar().showMessage("Chargement de l'interface..."))
        self.browser.loadFinished.connect(self._handle_load_finished)
        self.browser.renderProcessTerminated.connect(self._handle_render_process_terminated)
        self.reload_app()

    def reload_app(self) -> None:
        if server_ready(self.port):
            logger.info("Chargement de l'interface depuis %s", self.server_url)
            self.browser.setUrl(QUrl(self.server_url))
            return
        self._show_browser_error(
            "Le moteur local ne repond pas.",
            f"Impossible de joindre {self.server_url}. Relance le logiciel ou utilise Reessayer.",
        )

    def _show_browser_error(self, title: str, details: str) -> None:
        logger.error("Affichage d'une page d'erreur: %s | %s", title, details)
        safe_title = html.escape(title)
        safe_details = html.escape(details)
        html_page = f"""
        <!doctype html>
        <html lang="fr">
        <head>
          <meta charset="utf-8">
          <title>{APP_NAME}</title>
          <style>
            body {{
              margin: 0;
              min-height: 100vh;
              display: grid;
              place-items: center;
              background: linear-gradient(135deg, #08131d, #13263a);
              color: #eef5ff;
              font-family: "Segoe UI", Bahnschrift, sans-serif;
            }}
            main {{
              width: min(680px, calc(100vw - 48px));
              padding: 28px;
              border-radius: 18px;
              background: rgba(7, 18, 29, 0.88);
              border: 1px solid rgba(255, 255, 255, 0.08);
              box-shadow: 0 20px 48px rgba(0, 0, 0, 0.28);
            }}
            h1 {{
              margin: 0 0 12px;
              color: #f2b248;
              font-size: 28px;
            }}
            p {{
              margin: 0 0 10px;
              line-height: 1.5;
              color: #d9e7f5;
            }}
            code {{
              font-family: Consolas, "Cascadia Code", monospace;
              color: #60d8e7;
            }}
          </style>
        </head>
        <body>
          <main>
            <h1>{safe_title}</h1>
            <p>{safe_details}</p>
            <p>Consulte <code>elite_plug_desktop.log</code> si le probleme persiste.</p>
          </main>
        </body>
        </html>
        """
        self.browser.setHtml(html_page, QUrl("about:blank"))
        self.statusBar().showMessage(title)

    def _handle_load_finished(self, ok: bool) -> None:
        if ok:
            self.statusBar().showMessage("Pret")
            return
        self._show_browser_error(
            "Erreur de chargement de l'interface.",
            "Le navigateur integre n'a pas pu afficher l'application locale.",
        )

    def _handle_render_process_terminated(self, status, exit_code: int) -> None:
        logger.error("Processus de rendu termine: status=%s exit_code=%s", status, exit_code)
        self._show_browser_error(
            "Le moteur d'affichage a plante.",
            "Relance le logiciel. Si cela se reproduit, le journal desktop contient le detail technique.",
        )


def main() -> int:
    configure_runtime_environment()
    if os.environ.get("ELITE55_SAFE_RENDER", "").strip() == "1":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    os.environ["ELITE55_BUILD_TOKEN"] = BUILD_TOKEN
    os.chdir(runtime_root())
    logger.info("Demarrage desktop dans %s", runtime_root())

    app_qt = QApplication(sys.argv)
    app_qt.setApplicationName(APP_NAME)
    app_qt.setOrganizationName(APP_NAME)

    loading = LoadingWindow()
    loading.show()

    def set_loading_message(message: str) -> None:
        loading.message.setText(message)
        app_qt.processEvents()

    try:
        set_loading_message("Verification des prerequis Windows...")
        ensure_windows_prerequisites(set_loading_message)
    except Exception:
        logger.exception("Verification des prerequis Windows en echec")
        set_loading_message("Prerequis additionnels non installes, poursuite du demarrage...")

    backend: BackendServer | None = None
    owns_server = False
    selected_port = PREFERRED_PORT
    server_url = build_server_url(selected_port)
    startup_deadline = [time.monotonic() + STARTUP_TIMEOUT_SECONDS]

    def start_embedded_backend(port: int) -> BackendServer:
        logger.info("Lancement du backend embarque sur le port %s", port)
        server = BackendServer(port)
        server.start()
        return server

    if server_ready(PREFERRED_PORT, BUILD_TOKEN):
        logger.info("Serveur existant reutilise sur le port prefere %s", PREFERRED_PORT)
        initial_message = "Serveur local detecte, ouverture de l'interface..."
    elif not is_port_open(HOST, PREFERRED_PORT):
        logger.info("Le port prefere est libre, demarrage du backend embarque")
        initial_message = "Lancement du serveur local integre..."
        backend = start_embedded_backend(PREFERRED_PORT)
        owns_server = True
    else:
        selected_port = find_free_port()
        server_url = build_server_url(selected_port)
        logger.warning(
            "Le port prefere %s est occupe par un autre service. Bascule automatique vers %s.",
            PREFERRED_PORT,
            selected_port,
        )
        initial_message = f"Port {PREFERRED_PORT} occupe, demarrage local sur {selected_port}..."
        backend = start_embedded_backend(selected_port)
        owns_server = True

    loading.message.setText(initial_message)

    main_window: dict[str, MainWindow] = {}

    def open_main_window() -> None:
        logger.info("Ouverture de la fenetre principale via %s", server_url)
        loading.close()
        main_window["window"] = MainWindow(server_url, selected_port)
        main_window["window"].show()

    def retry_startup() -> None:
        nonlocal backend, owns_server, selected_port, server_url
        logger.info("Nouvelle tentative de demarrage")
        loading.retry_button.hide()
        loading.progress.setRange(0, 0)
        loading.message.setText("Nouvelle tentative de connexion au moteur local...")
        startup_deadline[0] = time.monotonic() + STARTUP_TIMEOUT_SECONDS

        if backend is not None and owns_server:
            backend.stop()
            backend.join(timeout=4)
            backend = None
            owns_server = False

        if server_ready(PREFERRED_PORT, BUILD_TOKEN):
            selected_port = PREFERRED_PORT
            server_url = build_server_url(selected_port)
            logger.info("Serveur existant detecte sur le port prefere apres reessai")
        elif not is_port_open(HOST, PREFERRED_PORT):
            selected_port = PREFERRED_PORT
            server_url = build_server_url(selected_port)
            backend = start_embedded_backend(selected_port)
            owns_server = True
        else:
            selected_port = find_free_port()
            server_url = build_server_url(selected_port)
            backend = start_embedded_backend(selected_port)
            owns_server = True
        check_timer.start(CHECK_INTERVAL_MS)

    def check_backend() -> None:
        if backend is not None and backend.start_error is not None:
            logger.error("Demarrage backend echoue: %s", backend.start_error)
            check_timer.stop()
            loading.progress.setRange(0, 1)
            loading.progress.setValue(0)
            loading.message.setText(
                "Le moteur local a echoue au demarrage. Le fichier elite_plug_desktop.log contient le detail technique."
            )
            loading.retry_button.show()
            return
        if server_ready(selected_port, BUILD_TOKEN):
            logger.info("Serveur pret sur %s, bascule vers la fenetre principale", selected_port)
            check_timer.stop()
            open_main_window()
            return
        if time.monotonic() >= startup_deadline[0]:
            logger.error("Timeout de demarrage du moteur local sur %s", selected_port)
            check_timer.stop()
            loading.progress.setRange(0, 1)
            loading.progress.setValue(0)
            loading.message.setText(
                f"Le moteur local ne repond pas sur {selected_port}. Reessayez, un autre port sera choisi si besoin."
            )
            loading.retry_button.show()

    loading.retry_button.clicked.connect(retry_startup)

    check_timer = QTimer()
    check_timer.timeout.connect(check_backend)
    check_timer.start(CHECK_INTERVAL_MS)

    exit_code = app_qt.exec()
    logger.info("Boucle Qt terminee avec code %s", exit_code)

    if owns_server and backend is not None:
        logger.info("Arret du backend embarque")
        backend.stop()
        backend.join(timeout=4)

    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        logger.exception("Crash desktop")
        app_qt = QApplication.instance()
        if app_qt is None:
            app_qt = QApplication(sys.argv)
        QMessageBox.critical(None, APP_NAME, f"Impossible de demarrer le logiciel.\n\n{exc}")
        raise
