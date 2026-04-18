from __future__ import annotations

import json
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

import uvicorn
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox, QToolBar

import app.main as elite_main

HOST = "127.0.0.1"
PORT = 8899
ROOT_URL = f"http://{HOST}:{PORT}"
HEALTH_URL = f"{ROOT_URL}/api/health"
WINDOW_TITLE = "Elite55"
STARTUP_TIMEOUT_SECONDS = 45.0


def _url_json(url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def elite55_server_ready() -> bool:
    data = _url_json(HEALTH_URL)
    return bool(data and data.get("ok") is True)


def tcp_port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        try:
            return sock.connect_ex((host, port)) == 0
        except OSError:
            return False


class EliteServerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(name="elite55-uvicorn", daemon=True)
        self.failed_error: str | None = None
        self.server: uvicorn.Server | None = None

    def run(self) -> None:
        try:
            config = uvicorn.Config(
                elite_main.app,
                host=HOST,
                port=PORT,
                reload=False,
                log_level="info",
            )
            self.server = uvicorn.Server(config)
            self.server.run()
        except Exception as error:
            self.failed_error = str(error)
            traceback.print_exc()

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True


class Elite55Window(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1500, 950)

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)
        self.view.setHtml(
            """
            <html>
              <body style='background:#0b1020;color:#e8eefc;font-family:Segoe UI,Arial,sans-serif;'>
                <div style='max-width:720px;margin:70px auto;padding:24px;border-radius:14px;background:#121a2e;'>
                  <h1 style='margin-top:0;'>Elite55 démarre...</h1>
                  <p>Le moteur local se lance. Merci de patienter quelques secondes.</p>
                  <p>Si le chargement dure trop longtemps, une erreur claire s'affichera.</p>
                </div>
              </body>
            </html>
            """
        )

        toolbar = QToolBar("Navigation", self)
        self.addToolBar(toolbar)

        action_reload = QAction("Rafraîchir", self)
        action_reload.triggered.connect(self.view.reload)
        toolbar.addAction(action_reload)

        action_home = QAction("Accueil", self)
        action_home.triggered.connect(lambda: self.view.load(QUrl(ROOT_URL)))
        toolbar.addAction(action_home)

        self.server_thread: EliteServerThread | None = None
        self.external_server = False
        self.start_monotonic = time.monotonic()
        self.loaded = False

        self.timer = QTimer(self)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self._check_server_ready)

        self._start_backend_and_wait()

    def _start_backend_and_wait(self) -> None:
        if elite55_server_ready():
            self.external_server = True
            self.timer.start()
            return

        if tcp_port_busy(HOST, PORT):
            QMessageBox.critical(
                self,
                "Elite55",
                (
                    "Le port 8899 est déjà utilisé par un autre programme.\n\n"
                    "Ferme l'ancien Elite55 ou le programme qui occupe ce port, puis relance l'exécutable."
                ),
            )
            self.close()
            return

        self.server_thread = EliteServerThread()
        self.server_thread.start()
        self.timer.start()

    def _check_server_ready(self) -> None:
        if self.server_thread and self.server_thread.failed_error:
            self.timer.stop()
            QMessageBox.critical(
                self,
                "Elite55",
                f"Le moteur local n'a pas réussi à démarrer.\n\nErreur : {self.server_thread.failed_error}",
            )
            self.close()
            return

        if elite55_server_ready():
            self.timer.stop()
            if not self.loaded:
                self.loaded = True
                self.view.load(QUrl(ROOT_URL))
            return

        if time.monotonic() - self.start_monotonic >= STARTUP_TIMEOUT_SECONDS:
            self.timer.stop()
            QMessageBox.critical(
                self,
                "Elite55",
                (
                    "Le moteur local a mis trop de temps à répondre.\n\n"
                    "Relance l'exécutable. Si le problème revient, envoie le message affiché."
                ),
            )
            self.close()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.timer.stop()
        if self.server_thread and not self.external_server:
            self.server_thread.stop()
            self.server_thread.join(timeout=5.0)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = Elite55Window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
