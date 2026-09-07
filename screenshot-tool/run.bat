@echo off
REM Command-line version.  Usage:  run.bat shot.png -o results.csv
"%~dp0.venv\Scripts\python.exe" "%~dp0playstore_finder.py" %*
