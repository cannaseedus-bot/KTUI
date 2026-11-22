@echo off
rem ---------------------------------------------------------------------------------------------
rem  start.bat - bring the whole local stack up: llama-server (runtime\llama) and the chat app.
rem
rem    start.bat                default_model from gpt-oss.toml (currently gpt-oss-20b)
rem    start.bat qwen3-4b       serve another alias from [models]; `python task-engine.py models`
rem                             lists them fastest first
rem    start.bat advisor        add or replace a cloud advisor token in .env, then exit
rem    start.bat stop           stop the llama-server this stack leaves running
rem
rem  Local models are the default: with weights on disk nothing here needs a key or the network.
rem  Cloud models are advisors - optional, asked for once and saved to .env (gitignored) - reached
rem  inside the app with /advisor openai or /advisor deepseek, and /local comes back.
rem ---------------------------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"
title KNUMATIC .aiml

set "ENDPOINT=http://127.0.0.1:9032"
set "HEALTH=%ENDPOINT%/health"
set "WAIT_SECONDS=180"

if /i "%~1"=="stop" goto :stop

set "ADVISOR_ONLY="
if /i "%~1"=="advisor" set "ADVISOR_ONLY=1"

if defined ADVISOR_ONLY goto :prepare_advisor

where python >nul 2>&1 || goto :nopython

rem --- which model: the argument, else the one gpt-oss.toml calls the default -------------------
set "MODEL=%~1"
if not defined MODEL for /f "usebackq delims=" %%M in (`python -c "import tomllib;print(tomllib.load(open('gpt-oss.toml','rb'))['server']['default_model'])" 2^>nul`) do set "MODEL=%%M"
if not defined MODEL set "MODEL=gpt-oss-20b"

if not exist "runtime\llama\llama-server.exe" goto :noruntime

python -c "import sys,tomllib;sys.exit(0 if '%MODEL%' in tomllib.load(open('gpt-oss.toml','rb'))['models'] else 1)"
if errorlevel 1 goto :nomodel

rem --- what is actually on disk, so the choice below is informed ---------------------------------
rem (percent is the batch escape character, so this formats with .format rather than %d)
python -c "import os,sys,tomllib;c=tomllib.load(open('gpt-oss.toml','rb'));d=c['model_dir'];m=c['models'];ok=[a for a,v in m.items() if os.path.isfile(v if os.path.isabs(v) else os.path.join(d,v))];print('[start] local weights: {} of {} aliases found'.format(len(ok),len(m)));print('[start] default: '+c['server']['default_model']);sys.exit(0 if ok else 3)"
if errorlevel 3 echo [start] no local weights on disk - a cloud advisor is the only usable option here.

rem --- cloud advisors: free to refuse, saved once, respected forever ------------------------------
:prepare_advisor
call :env_state
if defined HAVE_OPENAI echo [start] cloud advisor ready: openai ^(OPENAI_API_KEY in .env^)
if defined HAVE_DEEPSEEK echo [start] cloud advisor ready: deepseek ^(DEEPSEEK_API_KEY in .env^)
if defined HAVE_OPENAI goto :after_advisor
if defined HAVE_DEEPSEEK goto :after_advisor

echo.
echo [start] Local models need no key and no network.
echo [start] A cloud advisor is optional - press Enter to skip and stay local.
echo.
set "PICK="
set /p "PICK=[start] add one? [openai / deepseek / skip] : "
if not defined PICK goto :local_only
if /i "%PICK%"=="skip" goto :local_only
if /i "%PICK%"=="openai" goto :key_openai
if /i "%PICK%"=="deepseek" goto :key_deepseek
echo [start] "%PICK%" is not a choice - staying local.
goto :local_only

:key_openai
call :read_key OPENAI_API_KEY
goto :after_advisor

:key_deepseek
call :read_key DEEPSEEK_API_KEY
goto :after_advisor

:local_only
echo [start] staying local.

:after_advisor
if defined ADVISOR_ONLY (
    echo [start] done - run start.bat to bring the stack up.
    exit /b 0
)

rem --- reuse a server that is already answering, otherwise start one in its own window ----------
call :is_up
if not errorlevel 1 goto :reuse

echo [start] serving %MODEL% with runtime\llama\llama-server.exe ...
start "llama-server - %MODEL%" /min cmd /c "python task-engine.py launch --model %MODEL% --keep-alive"
set "OWNED=1"
call :wait_up || goto :timeout
goto :chat

:reuse
echo [start] reusing the llama-server already answering on %ENDPOINT%
set "OWNED=0"

:chat
echo [start] local model: %MODEL%
echo [start] in the app: /models  /model alias  /advisor openai  /advisor deepseek  /local
echo.
python chat_app.py
echo.
if "%OWNED%"=="1" (
    echo [start] chat closed. llama-server is still listening in its own window.
    echo         close that window, or run:  start.bat stop
) else (
    echo [start] chat closed. The server that was already running is left alone.
)
pause
exit /b 0

rem --- subroutines ------------------------------------------------------------------------------
:is_up
powershell -NoProfile -NonInteractive -Command "try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%HEALTH%'; if ($r.StatusCode -eq 200) { exit 0 } } catch { }; exit 1" >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0

:wait_up
set /a waited=0
:wait_loop
call :is_up
if not errorlevel 1 exit /b 0
set /a waited+=2
if %waited% GEQ %WAIT_SECONDS% exit /b 1
>nul 2>&1 ping -n 2 127.0.0.1
goto :wait_loop

:env_state
set "HAVE_OPENAI="
set "HAVE_DEEPSEEK="
if not exist ".env" exit /b 0
for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
    if /i "%%A"=="OPENAI_API_KEY" if not "%%B"=="" set "HAVE_OPENAI=1"
    if /i "%%A"=="DEEPSEEK_API_KEY" if not "%%B"=="" set "HAVE_DEEPSEEK=1"
)
exit /b 0

rem %1 is the variable name. Preferred path: typed hidden, written straight to .env by PowerShell, so
rem the token never shows on screen or in this console's history. A console-less run falls back to a
rem visible prompt rather than dead-ending. Either way .env is gitignored and blocked from the model.
:read_key
powershell -NoProfile -NonInteractive -Command "try { $s = Read-Host -AsSecureString 'paste %~1 (hidden, Enter to skip)' } catch { exit 4 }; if ($null -eq $s) { exit 4 }; $k = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)); if ([string]::IsNullOrWhiteSpace($k)) { exit 3 }; $p = Join-Path (Get-Location) '.env'; $name = '%~1'; $lines = @(); if (Test-Path $p) { $lines = @(Get-Content $p | Where-Object { $_ -notmatch ('^\s*' + $name + '\s*=') }) }; $lines += ($name + '=' + $k.Trim()); [System.IO.File]::WriteAllLines($p, $lines); exit 0"
if not errorlevel 1 goto :read_key_saved
if errorlevel 4 goto :read_key_visible
goto :read_key_skipped

:read_key_visible
echo [start] hidden input is not available here - the key will be visible as you type.
set "KEYVAL="
set /p "KEYVAL=%~1: "
if not defined KEYVAL goto :read_key_skipped
powershell -NoProfile -NonInteractive -Command "$p = Join-Path (Get-Location) '.env'; $name = '%~1'; $lines = @(); if (Test-Path $p) { $lines = @(Get-Content $p | Where-Object { $_ -notmatch ('^\s*' + $name + '\s*=') }) }; $lines += ($name + '=' + $env:KEYVAL.Trim()); [System.IO.File]::WriteAllLines($p, $lines); exit 0"
set "KEYVAL="
if errorlevel 1 goto :read_key_skipped

:read_key_saved
echo [start] saved %~1 to .env
echo         the app reads it on start; nothing else in the repo ever sees it.
exit /b 0

:read_key_skipped
echo [start] no key entered - staying local.
exit /b 1

rem --- failure paths ----------------------------------------------------------------------------
:nopython
echo [start] python was not found on PATH. Install Python 3.11+ or use the "py" launcher.
pause
exit /b 1

:noruntime
echo [start] runtime\llama\llama-server.exe is missing.
echo         run:  python task-engine.py prepare     (stages the llama-haswell package)
pause
exit /b 1

:nomodel
echo [start] "%MODEL%" is not an alias in gpt-oss.toml. Known models, fastest first:
python task-engine.py models
pause
exit /b 1

:timeout
echo [start] llama-server did not answer on %HEALTH% within %WAIT_SECONDS%s.
echo         newest log:
for /f "delims=" %%L in ('dir /b /o-d "logs\llama-server\*.log" 2^>nul') do (
    echo           logs\llama-server\%%L
    goto :timeout_done
)
:timeout_done
echo         try by hand:  python task-engine.py launch --model %MODEL% --keep-alive
pause
exit /b 1

:stop
taskkill /f /im llama-server.exe >nul 2>&1
if errorlevel 1 (
    echo [stop] no llama-server.exe was running.
) else (
    echo [stop] llama-server stopped.
)
exit /b 0
