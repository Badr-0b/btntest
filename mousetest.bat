@echo off
title Mouse Button Tester
cd /d "%~dp0"
python mousetest.py
if errorlevel 1 pause
