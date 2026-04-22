param(
  [switch]$Startup,
  [switch]$AlwaysOnTop,
  [switch]$PinDesktop
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$exePath = Join-Path $root "dist\\SamGPTDesktopWidget.exe"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$startupPath = [Environment]::GetFolderPath("Startup")
$shortcutName = "SamGPT Desktop Widget.lnk"

$arguments = @()
if ($AlwaysOnTop) { $arguments += "--always-on-top" }
if ($PinDesktop) { $arguments += "--pin-desktop" }
$argumentString = $arguments -join " "

if (Test-Path $exePath) {
  $targetPath = $exePath
}
else {
  $pythonPath = Join-Path (Split-Path (Get-Command python).Source) "pythonw.exe"
  $targetPath = $pythonPath
  $argumentString = "-m windows_widget.widget_host $argumentString".Trim()
}

$wsh = New-Object -ComObject WScript.Shell

function New-WidgetShortcut([string]$shortcutPath) {
  $shortcut = $wsh.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $targetPath
  $shortcut.Arguments = $argumentString
  $shortcut.WorkingDirectory = "$root"
  $shortcut.Description = "SamGPT temporary mail desktop widget"
  $shortcut.Save()
}

New-WidgetShortcut (Join-Path $desktopPath $shortcutName)

if ($Startup) {
  New-WidgetShortcut (Join-Path $startupPath $shortcutName)
}

Write-Host "Shortcut created:" -ForegroundColor Green
Write-Host "  Desktop: $(Join-Path $desktopPath $shortcutName)"
if ($Startup) {
  Write-Host "  Startup: $(Join-Path $startupPath $shortcutName)"
}
