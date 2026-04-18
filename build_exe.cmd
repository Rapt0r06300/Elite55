@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo =====================================
echo   Elite55 - Compilation bureau Windows
echo =====================================
echo.

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
    goto :python_ok
)

where py >nul 2>nul
if %errorlevel%==0 (
    echo [1/6] Création de l'environnement virtuel Python...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
    set "PYTHON=.venv\Scripts\python.exe"
    goto :python_ok
)

where python >nul 2>nul
if %errorlevel%==0 (
    echo [1/6] Création de l'environnement virtuel Python...
    python -m venv .venv
    if errorlevel 1 goto :error
    set "PYTHON=.venv\Scripts\python.exe"
    goto :python_ok
)

echo [ERREUR] Python n'a pas été trouvé sur ce PC.
echo Installe Python 3 puis relance ce fichier.
goto :end

:python_ok
echo [2/6] Mise à jour de pip...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/6] Installation des dépendances du projet...
"%PYTHON%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo [4/6] Nettoyage des anciens dossiers build et dist...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Elite55.spec" del /q "Elite55.spec"
if exist "Elite Dangerous - Plug.spec" del /q "Elite Dangerous - Plug.spec"

echo [5/6] Compilation de l'exécutable bureau...
"%PYTHON%" -m PyInstaller --noconfirm --clean --windowed --onedir --name "Elite55" --add-data "app\static;app\static" --add-data "app\templates;app\templates" --hidden-import sitecustomize --hidden-import app.trade_ranking --hidden-import app.live_snapshot_backend --hidden-import app.live_snapshot_service --hidden-import app.commodity_intel_service --hidden-import app.mission_intel_service --hidden-import app.dashboard_service --hidden-import PySide6.QtWebEngineCore --hidden-import PySide6.QtWebEngineWidgets elite55_desktop.py
if errorlevel 1 goto :error

if exist "elite_trade.db" (
    echo [6/6] Copie de la base locale dans le dossier dist...
    copy /Y "elite_trade.db" "dist\Elite55\elite_trade.db" >nul
) else (
    echo [6/6] Aucune base locale à copier, le logiciel la créera si nécessaire.
)

echo.
echo ==========================================
echo Compilation terminée avec succès.
echo Exécutable : dist\Elite55\Elite55.exe
echo ==========================================
echo.
start "" explorer "dist\Elite55"
pause
goto :end

:error
echo.
echo [ERREUR] La compilation a échoué.
echo Regarde les lignes juste au-dessus puis envoie-moi le message exact.
echo.
pause

:end
endlocal
