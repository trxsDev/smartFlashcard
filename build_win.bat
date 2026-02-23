@echo off
echo =========================================
echo  SmartFlashCard - Windows Build Script
echo =========================================
echo.
echo Installing requirements...
pip install -r requirements.txt
pip install pyinstaller
echo.
echo Starting PyInstaller build process...
pyinstaller --clean build_scripts\build_win.spec
echo.
echo =========================================
echo Build Complete! 
echo Your .exe file is located in the "dist\SmartFlashCard" folder.
echo =========================================
pause
