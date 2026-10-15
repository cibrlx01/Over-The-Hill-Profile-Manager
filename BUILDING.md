# Building version 1.0.2

This repository contains the application and launcher source shipped in the Nexus Mods v1.0.2 download:
https://www.nexusmods.com/overthehill/mods/16

## Requirements

- 64-bit Windows 10 or 11.
- Official 64-bit CPython 3.12 with Tcl/Tk (Tkinter) installed. The published build used Python 3.12.5 and Tcl/Tk 8.6.13.
- The Windows .NET Framework C# compiler at `%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`.

No third-party Python packages are required. A different Python patch version or runtime installation can change the output bytes.

## Build

Open a terminal in this repository and run these commands with the required Python installation:

```powershell
python --version
python -m tkinter
python build_public_release.py
```

Close the Tkinter demonstration window before running the build command. The script validates Windows, Python 3.12, and a 64-bit interpreter.

The output is placed under `build/1.0.2/`, including the release ZIP and `OverTheHill-ProfileManager-v1.0.2-Windows-x64/OverTheHill.ProfileManager.exe`. The script refuses to overwrite an existing build directory; move the previous build output aside before rebuilding.

## Tests

```powershell
python -m unittest discover -s . -p "test*.py"
```

## Packaging and review

`PublicLauncher.cs` is compiled into the Windows executable. It embeds a ZIP containing the Python runtime, Tcl/Tk, and application files, plus a SHA-256 payload manifest. On launch, it extracts and verifies that private runtime under `%LOCALAPPDATA%\OverTheHillProfileManager\Runtime`.

`build_public_release.py` contains the packaging steps. `profile_manager.py` contains the interface and `profile_core.py` contains the profile-management logic. `vehicle_names.json` contains vehicle labels.

The original application code is MIT licensed; bundled runtime components retain their own licenses. See `LICENSE.txt` and `THIRD-PARTY-NOTICES/`. The release is unsigned. No game saves or game files are distributed.
