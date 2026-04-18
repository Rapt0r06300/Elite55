@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "ROOT_DIR=%CD%"
set "BUILD_DIR=build_pyinstaller"
set "DIST_DIR=dist_build"
set "SPEC_DIR=build_spec"
set "FINAL_EXE=%DIST_DIR%\Elite55\Elite55.exe"
set "STATIC_DATA=%ROOT_DIR%\app\static;app\static"
set "TEMPLATES_DATA=%ROOT_DIR%\app\templates;app\templates"

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
    echo [1/7] Création de l'environnement virtuel Python...
    py -3 -m venv .venv
    if errorlevel 1 goto :error
    set "PYTHON=.venv\Scripts\python.exe"
    goto :python_ok
)

where python >nul 2>nul
if %errorlevel%==0 (
    echo [1/7] Création de l'environnement virtuel Python...
    python -m venv .venv
    if errorlevel 1 goto :error
    set "PYTHON=.venv\Scripts\python.exe"
    goto :python_ok
)

echo [ERREUR] Python n'a pas été trouvé sur ce PC.
echo Installe Python 3 puis relance ce fichier.
goto :end

:python_ok
echo [2/7] Mise à jour de pip...
"%PYTHON%" -m pip install --upgrade pip
if errorlevel 1 goto :error

echo [3/7] Installation des dépendances du projet...
"%PYTHON%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo [4/7] Fermeture d'une ancienne instance d'Elite55 si elle tourne encore...
taskkill /F /IM "Elite55.exe" >nul 2>nul
taskkill /F /IM "Elite Dangerous - Plug.exe" >nul 2>nul
timeout /t 1 /nobreak >nul

echo [5/7] Nettoyage des anciens dossiers de compilation temporaires...
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%" rmdir /s /q "%DIST_DIR%"
if exist "%SPEC_DIR%" rmdir /s /q "%SPEC_DIR%"
if exist "%BUILD_DIR%" goto :temp_locked
if exist "%DIST_DIR%" goto :temp_locked
if exist "%SPEC_DIR%" goto :temp_locked
if exist "Elite55.spec" del /q "Elite55.spec"
if exist "Elite Dangerous - Plug.spec" del /q "Elite Dangerous - Plug.spec"

echo [6/7] Compilation de l'exécutable bureau...
"%PYTHON%" -m PyInstaller --noconfirm --clean --windowed --onedir --name "Elite55" --distpath "%DIST_DIR%" --workpath "%BUILD_DIR%" --specpath "%SPEC_DIR%" --add-data "%STATIC_DATA%" --add-data "%TEMPLATES_DATA%" --hidden-import sitecustomize --hidden-import app.trade_ranking --hidden-import app.live_snapshot_backend --hidden-import app.live_snapshot_service --hidden-import app.commodity_intel_service --hidden-import app.mission_intel_service --hidden-import app.dashboard_service --hidden-import PySide6.QtWebEngineCore --hidden-import PySide6.QtWebEngineWidgets elite55_desktop.py
if errorlevel 1 goto :error

if exist "elite_trade.db" (
    echo [7/7] Copie de la base locale dans le dossier compilé...
    copy /Y "elite_trade.db" "%DIST_DIR%\Elite55\elite_trade.db" >nul
) else (
    echo [7/7] Aucune base locale à copier, le logiciel la créera si nécessaire.
)

echo.
echo ==========================================
echo Compilation terminée avec succès.
echo Exécutable : %FINAL_EXE%
echo ==========================================
echo.
start "" explorer "%DIST_DIR%\Elite55"
pause
goto :end

:temp_locked
echo.
echo [ERREUR] Impossible de nettoyer les dossiers temporaires de compilation.
echo Ferme :
echo - Elite55
echo - toute fenêtre ouverte sur build_pyinstaller, dist_build ou build_spec
echo - puis relance build_exe.cmd
echo.
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
