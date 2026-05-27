@echo off
echo ===================================
echo  Scraper stanovi - lokalno testiranje
echo ===================================

REM Proveri da li postoji Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo GRESKA: Python nije instaliran!
    pause
    exit /b
)

REM Instaliraj zavisnosti ako je potrebno
echo Instaliram zavisnosti...
pip install -r requirements.txt --quiet

REM Pokreni scraper jednom
echo.
echo Pokretam scraper...
python scraper.py

echo.
echo Gotovo! Pritisni bilo koji taster za izlaz.
pause
