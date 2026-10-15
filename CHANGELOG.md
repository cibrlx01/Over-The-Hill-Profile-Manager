# Changelog

## 1.0.2
- Preserve newer external profile tracking when a rename is cancelled before changes begin.
- Add regression coverage for a OneDrive-style state conflict during renaming.

## 1.0.1
- Fix false Game - Running status caused by the standalone launcher matching its own name. Only exact game executable names are detected.

## 1.0.0
- Public first-run setup, detected save locations, Browse, and user-chosen profile names.
- Creates BackupSaves beside live Saves; preserves both save files.
- Portable Windows x64 EXE with bundled runtime; no installed Python required.
- Journaled profile renaming and optional descriptions, retaining backup history.
- Sage interface, current journey, game status, summaries, and distance cards.
- Vehicle names only, with customizable labels.
- Reviewed, backed-up mileage sync on switching, plus guarded manual sync.
- Dated raw backups, stale-save checks, and recovery for interrupted changes.
