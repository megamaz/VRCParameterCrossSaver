@echo off
setlocal

set VENV_DIR=venv
set REQ_FILE=requirements.txt

if not exist "%VENV_DIR%" (
    echo creating venv in %VENV_DIR%
    python -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"

if exist "%REQ_FILE%" (
    python -m pip install --upgrade pip
    python -m pip install -r "%REQ_FILE%"
) else (
    echo no %REQ_FILE% found, skipping deps
)