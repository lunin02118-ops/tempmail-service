# SamGPT Windows Desktop Widget

This folder contains a native Windows host for the `/widget` page so the temp-mail UI can run as a small desktop widget instead of a browser tab.

## Fast Start

1. Install desktop dependencies:

```powershell
python -m pip install -r windows_widget\requirements.txt
```

2. Launch the widget directly:

```powershell
windows_widget\run.bat
```

## Build a Portable EXE

```powershell
powershell -ExecutionPolicy Bypass -File windows_widget\build.ps1
```

The executable is created at:

```text
dist\SamGPTDesktopWidget.exe
```

## Create a Desktop Shortcut

If you already built the EXE:

```powershell
powershell -ExecutionPolicy Bypass -File windows_widget\install.ps1
```

If you want the widget to auto-start with Windows:

```powershell
powershell -ExecutionPolicy Bypass -File windows_widget\install.ps1 -Startup
```

## Useful Flags

```powershell
windows_widget\run.bat --always-on-top
windows_widget\run.bat --show-in-taskbar
windows_widget\run.bat --reset-settings
```

Optional desktop-layer experiment:

```powershell
windows_widget\run.bat --pin-desktop
```

`--pin-desktop` attaches the widget to the desktop layer. Keep it optional because interactive behavior can vary by Windows setup.
