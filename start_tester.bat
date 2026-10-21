@echo off
rem Starts the tester in the background (pythonw, no console) and opens the browser.
rem Edit PYW if pythonw.exe is not on PATH, e.g. set PYW=C:\Python312\pythonw.exe
setlocal
cd /d "%~dp0"
if "%PYW%"=="" set PYW=pythonw
if "%PORT%"=="" set PORT=5088
netstat -ano | findstr "127.0.0.1:%PORT%" | findstr LISTENING >nul || start "" "%PYW%" run.py --port %PORT%
timeout /t 3 >nul
start http://127.0.0.1:%PORT%
