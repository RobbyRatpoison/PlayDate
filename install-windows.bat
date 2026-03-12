@echo off
:: PlayDate — launches the GUI installer without showing a console window
cd /d "%~dp0"
pythonw install.py
if errorlevel 1 python install.py
