$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --noconsole `
  --name SamGPTDesktopWidget `
  windows_widget\widget_host.py

Write-Host ""
Write-Host "Build complete:" -ForegroundColor Green
Write-Host "  $root\\dist\\SamGPTDesktopWidget.exe"
