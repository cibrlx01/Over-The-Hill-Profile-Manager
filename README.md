# Over the Hill Profile Manager 1.0.2

Portable, unofficial Windows utility for separate Over the Hill save profiles, timestamped backups, and cumulative vehicle distance. No game saves, game files, or vehicle unlocks are distributed.

## Run
Extract the ZIP and open OverTheHill.ProfileManager.exe. Python does not need to be installed. The EXE can be kept anywhere; its private runtime is unpacked to %LOCALAPPDATA%\OverTheHillProfileManager\Runtime and verified before launch. No administrator access, account, or internet connection is required by the manager. Play Game invokes Steam separately.

Built for 64-bit Windows 10/11 with the .NET Framework supplied by Windows. Bundles CPython 3.12.5 and Tcl/Tk 8.6.13; their original notices are included. The executable is unsigned. Source and tests are included for inspection.

## First setup
1. Close Over the Hill.
2. Check the detected save location. Browse accepts the over the hill folder or its Saves subfolder. Typical location: Documents\My games\over the hill, including OneDrive-redirected Documents.
3. Name the existing live journey, for example Main Profile. An optional description is just a note.
4. Choose Create profile from current save. The manager creates BackupSaves beside Saves, copies Player1.json and Player1.json.bak into the profile, and records which profile is live. It will not overwrite an existing saved profile.

If no live primary save exists, start the game and save a journey first. Existing profiles and tracking from earlier builds are detected without resetting them. No personal profile names are hardcoded.

## Profiles
Add Profile creates an empty slot. Switching to an empty slot backs up the outgoing journey and clears only the two live save files so the game can create a fresh journey. Other profiles stay archived.

Rename Profile moves the whole profile folder, including .backup history, and updates the active identity, distance baselines, and description together. Use the manager instead of manually renaming folders. Names must be unique valid Windows folder names; capitalization-only renames are rejected because Windows treats them as the same name.

Edit Description changes optional notes without changing progression. Back Up Profile archives the live pair. Play Game launches the Steam game.

## Distance and switching
Switch Profile opens a review of old combined distance, new driving, updated distance, and destination ownership. Show all vehicles includes unchanged vehicles. Cancel makes no save changes. Sync & Switch commits distance and switching together with safety backups. If files change during review, a fresh preview is required. Manual sync also checks that reviewed files have not changed.

The first sync adds distance from independent profiles. Copied journeys may share old distance; do not treat that shared driving as independent on the first combine. Later syncs add only new driving using saved baselines. Keep BackupSaves\.profile-manager: it stores the current identity and distance tracking.

Only vehicles present in a save are updated. Missing or locked vehicles are not added or unlocked. Their known distance is retained for later. The interface shows vehicle names only; numeric identifiers are used internally. Unknown vehicles can be named.

Combined Total Distance KM counts each tracked vehicle once. Individual profile totals cover the vehicles in that save and may differ. Current-profile summaries use the live save. Last played uses YYYY-MM-DD - HH:MM, retaining the saved timestamp's time. Table distances offer km/mi; summary totals use km.

## Backups and recovery
Every normal opening and save-changing operation appends raw dated copies to each profile's .backup folder. Live and archived copies have separate labels. Filenames include UTC time, microseconds, and a random identifier; old backups are never overwritten. Manager-state backups and transaction histories live under .profile-manager.

Interrupted operations block further changes and offer Recover interrupted change. Recovery validates the journal before restoring approved files, while preserving current copies. Rename journals recover the directory and its tracking state together.

There is no graphical historical-backup browser in this release. Restoring an older odometer stops sync rather than guessing; retain matching state backups if restoring distance history.

Close the game before save changes, let OneDrive finish syncing, and avoid using the same save directory from multiple computers simultaneously. The app checks processes and file freshness but cannot control another program's writes. Local snapshots are not a substitute for separate backup storage.

## Settings, removal, and source
Save-location settings and vehicle-label overrides are under %LOCALAPPDATA%\OverTheHillProfileManager. Runtime extraction never modifies the game installation. To remove the utility, delete the EXE and its app-data folder; game saves and BackupSaves stay in the selected game-save directory.

The source folder contains the Python application, C# launcher, build script, and tests. Build on Windows with 64-bit Python 3.12 including Tkinter and the Windows .NET Framework C# compiler: python build_public_release.py. No third-party Python packages are required. Run source tests there with python -m unittest discover -s . -p "test*.py".

Advanced flags: --root "D:\My games\over the hill", --smoke-test (no setup/backup writes), and --runtime-cache "D:\PrivateCache" (launcher cache override).

MIT covers the utility's original code. Bundled components retain their licenses. This unofficial utility is not affiliated with or endorsed by the game's developer or publisher.
