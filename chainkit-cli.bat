@echo off
rem Command line: chainkit-cli.bat build --iso "Burnout Revenge.iso"   (see README.md)
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
"%~dp0.venv\Scripts\python.exe" -m chainkit %*
