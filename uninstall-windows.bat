@echo off
:: PlayDate — launches the GUI uninstaller without showing a console window
cd /d "%~dp0"
pythonw uninstall.py
if errorlevel 1 python uninstall.py
