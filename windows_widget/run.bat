@echo off
setlocal
cd /d "%~dp0.."
pythonw -m windows_widget.widget_host %*
