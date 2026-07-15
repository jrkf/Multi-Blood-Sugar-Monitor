@echo off
setlocal enabledelayedexpansion
title Monitor Cukru - Instalacja i uruchomienie
cd /d "%~dp0"

echo ============================================================
echo   MONITOR CUKRU - automatyczna instalacja i uruchomienie
echo ============================================================
echo.

REM ============================================================
REM KROK 1: Sprawdz czy jest zainstalowany działający Python
REM ============================================================
echo [1/4] Sprawdzam obecnosc srodowiska Python...

python --version >nul 2>&1
if %errorlevel%==0 goto krok2

echo       Nie znaleziono dzialajacego Pythona na tym komputerze.
echo       Pobieram instalator Pythona (moze potrwac chwile)...
echo.

set "PY_URL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
set "PY_INSTALLER=%TEMP%\python_installer_monitor_cukru.exe"

curl -L -o "%PY_INSTALLER%" "%PY_URL%"
if not exist "%PY_INSTALLER%" (
    echo.
    echo BLAD: nie udalo sie pobrac instalatora Pythona.
    echo Sprawdz polaczenie z internetem i uruchom ten plik ponownie.
    echo.
    pause
    exit /b 1
)

echo Instaluje Pythona – to moze potrwac 1-2 minuty, prosze czekac...
REM Zmiana: InstallAllUsers=0 pozwala na instalacje bez praw administratora
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del "%PY_INSTALLER%" >nul 2>&1

echo.
echo Python zainstalowany. Aktualizuje sciezki systemowe w tym oknie...
REM Dynamiczne odswiezenie zmiennej PATH dla biezacego okna terminala
set "PATH=%USERPROFILE%\AppData\Local\Programs\Python\Python312\;%USERPROFILE%\AppData\Local\Programs\Python\Python312\Scripts\;%PATH%"

python --version >nul 2>&1
if not %errorlevel%==0 (
    echo.
    echo Python zostal zainstalowany, ale wymaga ponownego uruchomienia konsoli.
    echo Uruchamiam skrypt w nowym oknie...
    timeout /t 3 /nobreak >nul
    start "" cmd /c "%~f0"
    exit /b 0
)

REM ============================================================
REM KROK 2: Sprawdz czy program jest juz pobrany z GitHub
REM ============================================================
:krok2
echo [1/4] Python OK.

set "APP_DIR=%~dp0MonitorCukru"

if exist "%APP_DIR%\app.py" (
    echo [2/4] Program juz pobrany - pomijam pobieranie.
    goto krok3
)

echo [2/4] Pobieram program z GitHub...
set "ZIP_FILE=%TEMP%\monitor_cukru_repo.zip"
set "REPO_ZIP_URL=https://github.com/jrkf/Multi-Blood-Sugar-Monitor/archive/refs/heads/main.zip"

curl -L -o "%ZIP_FILE%" "%REPO_ZIP_URL%"

REM jesli galaz "main" nie istnieje, sprobuj "master"
findstr /m "PK" "%ZIP_FILE%" >nul 2>&1
if errorlevel 1 (
    echo Probuje alternatywnej galezi repozytorium...
    set "REPO_ZIP_URL=https://github.com/jrkf/Multi-Blood-Sugar-Monitor/archive/refs/heads/master.zip"
    curl -L -o "%ZIP_FILE%" "!REPO_ZIP_URL!"
)

if not exist "%ZIP_FILE%" (
    echo.
    echo BLAD: nie udalo sie pobrac programu z GitHub.
    echo Sprawdz polaczenie z internetem i uruchom ten plik ponownie.
    echo.
    pause
    exit /b 1
)

echo Rozpakowuje program...
set "EXTRACT_DIR=%TEMP%\monitor_cukru_extract"
if exist "%EXTRACT_DIR%" rmdir /s /q "%EXTRACT_DIR%"
mkdir "%EXTRACT_DIR%"
tar -xf "%ZIP_FILE%" -C "%EXTRACT_DIR%"

REM folder w zipie nazywa sie np. "Multi-Blood-Sugar-Monitor-main" - znajdz go i przenies
for /d %%D in ("%EXTRACT_DIR%\*") do (
    move "%%D" "%APP_DIR%" >nul
)

del "%ZIP_FILE%" >nul 2>&1
rmdir /s /q "%EXTRACT_DIR%" >nul 2>&1

if not exist "%APP_DIR%\app.py" (
    echo.
    echo BLAD: pobrano dane, ale nie znaleziono pliku app.py.
    echo Skontaktuj sie z osoba techniczna.
    echo.
    pause
    exit /b 1
)

echo Program pobrany pomyslnie.

REM ============================================================
REM KROK 3: Zainstaluj wymagane biblioteki
REM ============================================================
:krok3
echo [3/4] Sprawdzam i instaluje wymagane biblioteki (requirements.txt)...
cd /d "%APP_DIR%"
python -m pip install --disable-pip-version-check -q -r requirements.txt

if errorlevel 1 (
    echo.
    echo BLAD: nie udalo sie zainstalowac wymaganych bibliotek.
    echo Sprawdz polaczenie z internetem i uruchom ten plik ponownie.
    echo.
    pause
    exit /b 1
)

echo Biblioteki gotowe.

REM ============================================================
REM KROK 4: Uruchom program i otworz przegladarke
REM ============================================================
:krok4
echo [4/4] Uruchamiam program...
echo.
echo Za chwile otworzy sie przegladarka z podgladem.
echo NIE ZAMYKAJ okna, ktore zaraz sie pojawi - to w nim dziala program!
echo.

start "Monitor Cukru - SERWER (NIE ZAMYKAJ TEGO OKNA)" cmd /k "cd /d "%APP_DIR%" && python app.py"

timeout /t 5 /nobreak >nul
start "" "http://localhost:5000"

echo.
echo Gotowe! To okno mozna teraz zamknac.
timeout /t 5 /nobreak >nul
exit /b 0
