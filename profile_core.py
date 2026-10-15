"""Transactional save switching and cumulative vehicle mileage. Python standard library only."""
from __future__ import annotations
import base64
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import uuid

FILES = ('Player1.json', 'Player1.json.bak')
DEFAULT_ROOT = Path.home() / 'OneDrive/Documents/My games/over the hill'

class ProfileError(RuntimeError):
    pass

def vehicles(doc):
    try:
        items = doc['Profile']['Inventory']['Items']
    except (KeyError, TypeError):
        raise ProfileError('Save does not contain Profile.Inventory.Items.')
    if not isinstance(items, list):
        raise ProfileError('Invalid inventory list.')
    result = {}
    for item in items:
        if str(item.get('Type', '')).split(',')[0] != 'VehicleItem':
            continue
        data = item.get('Data', {})
        key = str(data.get('ItemId', ''))
        value = data.get('MetersTravelled', 0)
        if not key or key in result or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ProfileError('Invalid or duplicate vehicle mileage in save.')
        result[key] = data
    return result

def encode(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')

class Manager:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = Path(root).resolve()
        self.saves = self.root / 'Saves'
        self.backups = self.root / 'BackupSaves'
        self.meta = self.backups / '.profile-manager'
        self.state_path = self.meta / 'state.json'
        self.journal = self.meta / 'transaction.json'

    def _profile(self, name):
        if (not isinstance(name, str) or not name or len(name) > 80 or name.startswith('.')
                or name[-1:] in (' ', '.') or any(c in name for c in '<>:"/\\|?*')
                or any(ord(c) < 32 for c in name)
                or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$',
                    *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10)),
                    'COM¹', 'COM²', 'COM³', 'LPT¹', 'LPT²', 'LPT³'}):
            raise ProfileError('Invalid profile name.')
        path = self.backups / name
        if path.is_symlink() or path.resolve().parent != self.backups.resolve():
            raise ProfileError('Profile must be a direct, ordinary folder in BackupSaves.')
        return path

    def _names(self):
        # Windows folders have case-insensitive identities. Preserve ledger spelling
        # across case-only folder renames so their mileage is never counted twice.
        names = {}
        if self.backups.exists():
            for path in self.backups.iterdir():
                if path.is_dir() and not path.name.startswith('.') and not path.is_symlink():
                    names.setdefault(path.name.casefold(), path.name)
        try:
            state = self._state()
        except ProfileError:
            # Raw startup backups remain possible when state needs recovery.
            state = {'active': None, 'ledger': None}
        for name in (state.get('ledger') or {}).get('baselines', {}):
            names[name.casefold()] = name
        active = state['active']
        if active:
            names[active.casefold()] = active
        return sorted(names.values())

    def _bytes(self, path):
        if path.is_symlink():
            raise ProfileError(f'Refusing symbolic link: {path}')
        return path.read_bytes() if path.exists() else None

    def _doc(self, raw):
        if raw is None:
            return None
        try:
            doc = json.loads(raw.decode('utf-8-sig'))
            vehicles(doc)
            return doc
        except (ValueError, UnicodeError, TypeError, AttributeError) as exc:
            raise ProfileError(f'Cannot read save JSON: {exc}') from exc

    def _state(self):
        raw = self._bytes(self.state_path)
        if raw is None:
            return {'version': 1, 'active': None, 'ledger': None}
        try:
            state = json.loads(raw)
            if state.get('version') != 1 or 'active' not in state:
                raise ValueError('Unsupported state version')
            if state['active'] is not None:
                self._profile(state['active'])
            descriptions = state.get('descriptions', {})
            if not isinstance(descriptions, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in descriptions.items()):
                raise ValueError('Invalid profile descriptions')
            ledger = state.get('ledger')
            if ledger is not None:
                if not isinstance(ledger, dict) or not isinstance(ledger.get('totals'), dict) or not isinstance(ledger.get('baselines'), dict):
                    raise ValueError('Invalid mileage tracking structure')
                def valid_distance(value):
                    return not isinstance(value, bool) and isinstance(value, (int, float)) and value >= 0 and math.isfinite(value)
                for key, value in ledger['totals'].items():
                    if not isinstance(key, str) or not key or not valid_distance(value):
                        raise ValueError('Invalid total distance')
                profile_identities = {}
                for name, items in ledger['baselines'].items():
                    self._profile(name)
                    identity = name.casefold()
                    if identity in profile_identities:
                        raise ValueError('Duplicate profile mileage tracking identity')
                    profile_identities[identity] = name
                    if not isinstance(items, dict):
                        raise ValueError('Invalid profile mileage tracking')
                    for key, value in items.items():
                        if key not in ledger['totals'] or not valid_distance(value) or value > ledger['totals'][key]:
                            raise ValueError('Inconsistent mileage baseline')
                if state['active']:
                    state['active'] = profile_identities.get(state['active'].casefold(), state['active'])
            return state
        except (ValueError, TypeError, AttributeError, OverflowError, ProfileError) as exc:
            raise ProfileError('Manager state is invalid; restore it from a transaction backup.') from exc

    def _game_check(self):
        if self.game_running():
            raise ProfileError('Close Over the Hill before changing saves or mileage.')

    def _state_snapshot(self):
        raw = self._bytes(self.state_path)
        state = self._state()
        if self._bytes(self.state_path) != raw:
            raise ProfileError('Profile tracking changed while reading. Refresh and retry.')
        return state, raw

    def game_running(self):
        if os.name != 'nt':
            return False
        try:
            tasklist = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'tasklist.exe'
            result = subprocess.run([str(tasklist), '/FO', 'CSV', '/NH'], capture_output=True, text=True, creationflags=0x08000000, timeout=8)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProfileError('Could not check whether the game is running.') from exc
        if result.returncode:
            raise ProfileError('Could not check running games. Close the game and retry.')
        for line in result.stdout.splitlines():
            image = line.split(',')[0].strip('"').lower().replace(' ', '').replace('_', '').replace('-', '')
            # Exact executable identities: the public launcher itself contains
            # OverTheHill in its name and must never count as the game.
            if image in {'overthehill.exe', 'oth.exe'}:
                return True
        return False

    @contextlib.contextmanager
    def _lock(self, recovery=False, check_game=True):
        self.meta.mkdir(parents=True, exist_ok=True)
        with (self.meta / 'manager.lock').open('a+b') as handle:
            handle.seek(0)
            handle.write(b'0')
            handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ProfileError('Another profile manager operation is running.') from exc
            try:
                if self.journal.exists() and not recovery:
                    raise ProfileError('An interrupted transaction needs recovery before any changes.')
                if check_game:
                    self._game_check()
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _atomic(self, path, raw):
        if raw is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('xb') as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def _commit(self, changes, observed):
        for path, raw in observed.items():
            if self._bytes(path) != raw:
                raise ProfileError('A save changed while preparing the operation. Refresh and retry.')
        self._game_check()
        self._snapshot_all_locked('before_change')
        for path, raw in observed.items():
            if self._bytes(path) != raw:
                raise ProfileError('A save changed during backup. Refresh and retry.')
        self._game_check()
        before = {str(p.relative_to(self.root)): (None if self._bytes(p) is None else base64.b64encode(self._bytes(p)).decode()) for p in changes}
        record = {'version': 1, 'created': time.time(), 'before': before}
        self._atomic(self.journal, encode(record))
        archive = self.meta / 'history' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex + '.json')
        self._atomic(archive, encode(record))
        try:
            self._game_check()
            for path, raw in observed.items():
                if self._bytes(path) != raw:
                    raise ProfileError('A save changed just before writing. Refresh and retry.')
        except BaseException:
            self.journal.unlink()
            raise
        try:
            for path, raw in changes.items():
                self._atomic(path, raw)
        except BaseException:
            # Keep journal if rollback itself fails; no further writes are permitted.
            for rel, raw in before.items():
                self._atomic(self.root / rel, None if raw is None else base64.b64decode(raw))
            self.journal.unlink()
            raise
        self.journal.unlink()

    def _snapshot_all_locked(self, reason, active_override=None, excluded_names=()):
        """Append raw copies; never rewrite or parse the saves being backed up."""
        if reason not in ('opened', 'before_change', 'before_recovery', 'before_add_profile'):
            raise ProfileError('Invalid backup reason.')
        try:
            state = self._state()
        except ProfileError:
            # Raw backups must remain available even if manager state needs recovery.
            state = {'active': None}
        sources = []
        for name in self._names():
            if name.casefold() in {n.casefold() for n in excluded_names}:
                continue
            folder = self._profile(name)
            for filename in FILES:
                sources.append((folder / filename, folder / '.backup', 'archived'))
        active = active_override if active_override is not None else state['active']
        live_folder = self._profile(active) if active else self.backups
        for filename in FILES:
            sources.append((self.saves / filename, live_folder / '.backup', 'live' if state['active'] else 'live_unbound'))
        sources.append((self.state_path, self.meta / '.backup', 'manager_state'))
        original = {path: self._bytes(path) for path, _, _ in sources}
        # A second full read detects saves changing while the game or OneDrive writes.
        if any(self._bytes(path) != raw for path, raw in original.items()):
            raise ProfileError('Saves changed while reading the backup. Retry after saving has finished.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '_' + uuid.uuid4().hex
        count = 0
        for source, destination, label in sources:
            raw = original[source]
            if raw is None:
                continue
            if destination.is_symlink() or destination.resolve().parent != destination.parent.resolve():
                raise ProfileError('Backup folders must be ordinary directories, not redirected links.')
            destination.mkdir(parents=True, exist_ok=True)
            suffix = '.json.bak' if source.name.endswith('.json.bak') else '.json'
            stem = 'state' if source == self.state_path else 'Player1'
            target = destination / f'{stem}_{stamp}_{reason}_{label}{suffix}'
            # Exclusive creation makes overwriting a prior backup impossible.
            with target.open('xb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            count += 1
        if any(self._bytes(path) != raw for path, raw in original.items()):
            raise ProfileError('Saves changed during backup. No changes were applied; retry after saving has finished.')
        return {'files': count, 'reason': reason}

    def snapshot_all(self, reason='opened'):
        """Back up every archived pair plus the distinct live pair on startup."""
        with self._lock(check_game=False):
            return self._snapshot_all_locked(reason)

    def add_profile(self, name):
        with self._lock():
            folder = self._profile(name)
            if any(existing.casefold() == name.casefold() for existing in self._names()) or folder.exists():
                raise ProfileError('A profile with that name already exists.')
            self._snapshot_all_locked('before_add_profile')
            folder.mkdir(exist_ok=False)
        return self.status()

    def initialize_profile(self, name):
        """Explicit first use: copy the live pair and bind its new profile name."""
        with self._lock():
            folder = self._profile(name)
            state, state_raw = self._state_snapshot()
            if state['active']:
                raise ProfileError('A current profile is already configured.')
            # An empty Add Profile slot or recovered first-setup directory may
            # contain backups but no archived save yet. Reuse it without touching
            # those backups; never adopt a previously tracked mileage identity.
            identities = (state.get('ledger') or {}).get('baselines', {})
            matching = [n for n in self._names() if n.casefold() == name.casefold()]
            if matching:
                name = matching[0]
                folder = self._profile(name)
            if (any(n.casefold() == name.casefold() for n in identities)
                    or (folder.exists() and not folder.is_dir())
                    or any((folder / filename).exists() for filename in FILES)):
                raise ProfileError('That profile already has saved or tracked data. Choose a new name to preserve it.')
            observed = {self.state_path: state_raw}
            changes = {}
            for filename in FILES:
                source = self.saves / filename
                raw = self._bytes(source)
                self._doc(raw)
                if filename == FILES[0] and raw is None:
                    raise ProfileError('No live save was found. Play and save a journey first.')
                observed[source] = raw
                observed[folder / filename] = None
                changes[folder / filename] = raw
            state['active'] = name
            changes[self.state_path] = encode(state)
            try:
                self._commit(changes, observed)
            except BaseException:
                # A rolled-back first setup must not leave an empty profile that
                # blocks retry. Preserve any directory containing recovery data.
                if folder.is_dir() and not any(folder.iterdir()):
                    folder.rmdir()
                raise
        return self.status()

    def _canonical_name(self, name):
        self._profile(name)
        for existing in self._names():
            if existing.casefold() == name.casefold():
                return existing
        raise ProfileError('Profile does not exist.')

    def set_description(self, profile, text):
        if not isinstance(text, str) or len(text) > 4000:
            raise ProfileError('Description must be text with at most 4000 characters.')
        with self._lock():
            name = self._canonical_name(profile)
            state, raw = self._state_snapshot()
            state.setdefault('descriptions', {})[name] = text
            self._commit({self.state_path: encode(state)}, {self.state_path: raw})
        return self.status()

    def _rename_back(self, old, new):
        old_exists, new_exists = old.exists(), new.exists()
        if old_exists == new_exists or (old_exists and not old.is_dir()) or (new_exists and not new.is_dir()):
            raise ProfileError('Cannot recover profile rename: expected exactly one original or renamed folder. No files were restored.')
        if new_exists:
            new.rename(old)

    def rename_profile(self, old, new):
        """Journal an entire-folder rename and the corresponding tracking changes."""
        with self._lock():
            old = self._canonical_name(old)
            source, destination = self._profile(old), self._profile(new)
            if old.casefold() == new.casefold():
                raise ProfileError('Choose a different name; capitalization alone is the same Windows folder name.')
            if not source.is_dir():
                raise ProfileError('The profile folder is missing.')
            if destination.exists() or any(n.casefold() == new.casefold() for n in self._names()):
                raise ProfileError('A profile with that name already exists.')
            state, raw = self._state_snapshot()
            if state['active'] and state['active'].casefold() == old.casefold():
                state['active'] = new
            if state.get('ledger'):
                baselines = state['ledger']['baselines']
                for name in list(baselines):
                    if name.casefold() == old.casefold():
                        baselines[new] = baselines.pop(name)
            descriptions = state.setdefault('descriptions', {})
            for name in list(descriptions):
                if name.casefold() == old.casefold():
                    descriptions[new] = descriptions.pop(name)
            self._snapshot_all_locked('before_change')
            self._game_check()
            if self._bytes(self.state_path) != raw or destination.exists():
                raise ProfileError('Profile tracking changed before renaming. Refresh and retry.')
            record = {'version': 1, 'created': time.time(), 'before': {str(self.state_path.relative_to(self.root)): None if raw is None else base64.b64encode(raw).decode()},
                      'directory_rename': {'old': old, 'new': new}}
            self._atomic(self.journal, encode(record))
            self._atomic(self.meta / 'history' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex + '.json'), encode(record))
            try:
                if self._bytes(self.state_path) != raw:
                    raise ProfileError('Profile tracking changed before renaming. Refresh and retry.')
                self._game_check()
            except BaseException:
                # No directory or state mutation has started. Preserve any
                # external update instead of rolling stale state back over it.
                self.journal.unlink()
                raise
            moved = False
            state_write_started = False
            try:
                source.rename(destination)
                moved = True
                state_write_started = True
                self._atomic(self.state_path, encode(state))
            except BaseException:
                if moved:
                    self._rename_back(source, destination)
                if state_write_started:
                    self._atomic(self.state_path, raw)
                self.journal.unlink()
                raise
            self.journal.unlink()
        return self.status()

    def recover(self):
        """Explicit rollback of an interrupted transaction; refuses running game."""
        with self._lock(recovery=True):
            if not self.journal.exists():
                return self.status()
            try:
                record = json.loads(self._bytes(self.journal))
                if record.get('version') != 1 or not isinstance(record.get('before'), dict) or not record['before']:
                    raise ValueError('Invalid recovery structure')
                entries, seen = [], set()
                for rel, raw in record['before'].items():
                    if not isinstance(rel, str) or Path(rel).is_absolute():
                        raise ValueError('Unsafe recovery path')
                    path = (self.root / rel).resolve()
                    allowed = path == self.state_path.resolve()
                    if path.name in FILES:
                        allowed = path.parent == self.saves.resolve()
                        if path.parent.parent == self.backups.resolve():
                            allowed = path.parent == self._profile(path.parent.name).resolve()
                    identity = os.path.normcase(str(path))
                    if not path.is_relative_to(self.root) or not allowed or identity in seen:
                        raise ValueError('Unsafe or duplicate recovery path')
                    if raw is not None and not isinstance(raw, str):
                        raise ValueError('Invalid recovery bytes')
                    entries.append((path, None if raw is None else base64.b64decode(raw, validate=True)))
                    seen.add(identity)
            except (ValueError, TypeError, AttributeError, ProfileError) as exc:
                raise ProfileError('Invalid recovery journal; no files were restored.') from exc
            rename = record.get('directory_rename')
            if rename is not None:
                try:
                    if not isinstance(rename, dict) or set(rename) != {'old', 'new'} or len(entries) != 1 or entries[0][0] != self.state_path.resolve():
                        raise ValueError('Invalid rename journal')
                    old, new = self._profile(rename['old']), self._profile(rename['new'])
                    if rename['old'].casefold() == rename['new'].casefold() or old.exists() == new.exists():
                        raise ValueError('Ambiguous rename recovery')
                    if not (old if old.exists() else new).is_dir():
                        raise ValueError('Missing rename directory')
                except (ValueError, TypeError, AttributeError, ProfileError) as exc:
                    raise ProfileError('Invalid rename recovery journal; no files were restored.') from exc
            self._snapshot_all_locked('before_recovery',
                active_override=new.name if rename is not None and new.exists() else None,
                excluded_names=(old.name,) if rename is not None and new.exists() else ())
            self._game_check()
            if rename is not None:
                self._rename_back(old, new)
            for path, raw in entries:
                self._atomic(path, raw)
            self.journal.unlink()
        return self.status()

    def status(self):
        state = self._state()
        profiles = []
        for name in sorted(set(self._names()) | ({state['active']} if state['active'] else set())):
            path = self._profile(name) / FILES[0]
            raw = self._bytes(path)
            info = {'name': name, 'description': next((v for k, v in state.get('descriptions', {}).items() if k.casefold() == name.casefold()), ''), 'exists': raw is not None, 'vehicles': 0, 'last_played': '', 'total_meters': 0, 'error': None}
            try:
                if name == state['active']:
                    raw = self._bytes(self.saves / FILES[0])
                doc = self._doc(raw)
                if doc:
                    info.update(vehicles=len(vehicles(doc)), last_played=doc.get('Header', {}).get('LastPlayed', ''), total_meters=sum(d.get('MetersTravelled', 0) for d in vehicles(doc).values()))
            except ProfileError as exc:
                info['error'] = str(exc)
            profiles.append(info)
        return {'active': state['active'], 'bound': bool(state['active']), 'profiles': profiles, 'live_exists': (self.saves / FILES[0]).exists(), 'recovery_required': self.journal.exists(), 'root': str(self.root)}

    def bind_active(self, name):
        with self._lock():
            self._profile(name)
            state, state_raw = self._state_snapshot()
            if state['active']:
                raise ProfileError('An active profile is already bound; use Switch instead.')
            live = self._bytes(self.saves / FILES[0])
            self._doc(live)
            if live is None:
                raise ProfileError('No live save to bind.')
            observed = {self.state_path: state_raw, self.saves / FILES[0]: live}
            state['active'] = name
            self._commit({self.state_path: encode(state)}, observed)
        return self.status()

    def switch(self, target, allow_empty=False, sync_mileage=False, expected_preview=None):
        with self._lock():
            target_dir = self._profile(target)
            state, state_raw = self._state_snapshot()
            if not state['active']:
                raise ProfileError('First identify the live profile using Bind current profile.')
            if state['active'].casefold() == target.casefold():
                raise ProfileError('That profile is already active.')
            source_dir = self._profile(state['active'])
            observed = {self.state_path: state_raw}
            changes = {}
            if sync_mileage:
                state, observed, changes = self._sync_plan()
                if state['active'].casefold() == target.casefold():
                    raise ProfileError('Active profile changed while preparing the switch. Refresh and retry.')
                source_dir = self._profile(state['active'])
            for filename in FILES:
                livepath, targetpath = self.saves / filename, target_dir / filename
                live, incoming = self._bytes(livepath), self._bytes(targetpath)
                for path, raw in ((livepath, live), (targetpath, incoming)):
                    if path in observed and observed[path] != raw:
                        raise ProfileError('A save changed while preparing the switch. Refresh and retry.')
                    observed.setdefault(path, raw)
                if live is not None:
                    self._doc(live)
                if incoming is not None:
                    self._doc(incoming)
                if filename == FILES[0] and incoming is None and not allow_empty:
                    raise ProfileError('Target is empty. Confirm starting a new profile to clear the live save pair.')
                sourcepath = source_dir / filename
                source_raw = self._bytes(sourcepath)
                if sourcepath in observed and observed[sourcepath] != source_raw:
                    raise ProfileError('A profile changed while preparing the switch. Refresh and retry.')
                observed.setdefault(sourcepath, source_raw)
                changes[source_dir / filename] = changes.get(livepath, live)
                changes[livepath] = changes.get(targetpath, incoming)
            # An orphan backup is not a new profile and can be auto-restored by the game.
            if observed[target_dir / FILES[0]] is None:
                if observed[target_dir / FILES[1]] is not None:
                    raise ProfileError('Target has only a .bak save. Restore or remove it before switching.')
            if observed[self.saves / FILES[0]] is None and observed[self.saves / FILES[1]] is not None:
                raise ProfileError('Live folder has only a .bak save. Restore the primary before switching.')
            if expected_preview is not None:
                if not sync_mileage:
                    raise ProfileError('A switch preview requires mileage synchronization.')
                self._observe_switch_files(observed)
                if self._preview_token(observed, target) != expected_preview:
                    raise ProfileError('Saves changed since the switch preview. Review a fresh preview and try again.')
            state['active'] = target
            changes[self.state_path] = encode(state)
            self._commit(changes, observed)
        return self.status()

    def capture(self, profile=None):
        with self._lock():
            state, state_raw = self._state_snapshot()
            if not state['active'] or (profile is not None and profile != state['active']):
                raise ProfileError('Capture is only allowed for the known active profile.')
            observed = {self.state_path: state_raw}
            changes = {}
            for filename in FILES:
                path = self.saves / filename
                raw = self._bytes(path)
                self._doc(raw)
                observed[path] = raw
                destination = self._profile(state['active']) / filename
                observed[destination] = self._bytes(destination)
                changes[destination] = raw
            if observed[self.saves / FILES[0]] is None:
                raise ProfileError('No live save to capture yet. Start and exit the game first.')
            self._commit(changes, observed)
        return self.status()

    def _mileage(self):
        state_raw = self._bytes(self.state_path)
        state = self._state()
        if self._bytes(self.state_path) != state_raw:
            raise ProfileError('Mileage tracking changed while reading. Refresh and retry.')
        if not state['active']:
            raise ProfileError('Bind the current live profile before combining mileage.')
        observed = {self.state_path: state_raw}
        docs, values = {}, {}
        for name in sorted(set(self._names()) | {state['active']}):
            path = (self.saves if name == state['active'] else self._profile(name)) / FILES[0]
            raw = self._bytes(path)
            observed[path] = raw
            doc = self._doc(raw)
            if doc is not None:
                docs[name] = doc
                values[name] = {k: d.get('MetersTravelled', 0) for k, d in vehicles(doc).items()}
        ledger = state.get('ledger')
        totals = copy.deepcopy(ledger.get('totals', {})) if ledger else {}
        baselines = ledger.get('baselines', {}) if ledger else {}
        for name, items in values.items():
            for key, value in items.items():
                previous = baselines.get(name, {}).get(key, 0)
                if value < previous:
                    raise ProfileError(f'{name}, vehicle {key}: mileage fell below its last synchronized value ({value:g} < {previous:g} meters). This may be a restored or reset save. Use a new profile slot for a fresh reset; do not combine until the lower mileage is resolved.')
                totals[key] = totals.get(key, 0) + max(0, value - previous)
        rows = [{'vehicle_id': key, 'profiles': {n: v.get(key) for n, v in values.items()}, 'combined_meters': totals[key], 'new_meters': totals[key] - ((ledger or {}).get('totals', {}).get(key, 0))} for key in sorted(totals)]
        return state, observed, docs, values, totals, rows

    def mileage_preview(self):
        state, observed, _, values, _, rows = self._mileage()
        self._observe_switch_files(observed)
        return {'initialized': state.get('ledger') is not None, 'profiles': list(values), 'rows': rows,
                'token': self._preview_token(observed, '__sync__')}

    def _observe_switch_files(self, observed):
        names = set(self._names())
        raw_state = observed.get(self.state_path)
        if raw_state:
            active = json.loads(raw_state).get('active')
            if active:
                names.add(active)
        folders = [self.saves] + [self._profile(name) for name in sorted(names)]
        for folder in folders:
            for filename in FILES:
                path = folder / filename
                raw = self._bytes(path)
                if path in observed and observed[path] != raw:
                    raise ProfileError('A save changed while preparing the preview. Refresh and retry.')
                observed.setdefault(path, raw)
        for path, raw in observed.items():
            if self._bytes(path) != raw:
                raise ProfileError('A save changed while preparing the preview. Refresh and retry.')

    def _preview_token(self, observed, target):
        entries = [(str(path.relative_to(self.root)), None if raw is None else hashlib.sha256(raw).hexdigest()) for path, raw in observed.items()]
        return hashlib.sha256(encode({'target': target, 'files': sorted(entries)})).hexdigest()

    def switch_preview(self, target):
        """Read-only preview bound to the exact save bytes reviewed by the user."""
        folder = self._profile(target)
        if self.journal.exists():
            raise ProfileError('Recover the interrupted operation before switching.')
        state, observed, docs, values, totals, rows = self._mileage()
        if target.casefold() == state['active'].casefold():
            raise ProfileError('That profile is already active.')
        self._observe_switch_files(observed)
        primary, backup = (observed[folder / filename] for filename in FILES)
        if primary is None and backup is not None:
            raise ProfileError('Target has only a .bak save. Restore the primary before switching.')
        if observed[self.saves / FILES[0]] is None and observed[self.saves / FILES[1]] is not None:
            raise ProfileError('Live folder has only a .bak save. Restore the primary before switching.')
        for name in docs:
            self._doc(observed[self._profile(name) / FILES[1]])
        self._doc(observed[self.saves / FILES[1]])
        for row in rows:
            row['current_meters'] = row['combined_meters'] - row['new_meters']
        return {'active': state['active'], 'target': target, 'allow_empty': primary is None,
                'initialized': state.get('ledger') is not None, 'profiles': list(values),
                'rows': rows, 'token': self._preview_token(observed, target)}

    def _sync_plan(self):
        """Prepare mileage changes without writing; caller owns the operation lock."""
        state, observed, docs, values, totals, rows = self._mileage()
        changes, baselines = {}, copy.deepcopy((state.get('ledger') or {}).get('baselines', {}))
        for name, doc in docs.items():
            for key, data in vehicles(doc).items():
                data['MetersTravelled'] = totals[key]
            raw = encode(doc)
            folder = self._profile(name)
            for filename in FILES:
                path = folder / filename
                observed.setdefault(path, self._bytes(path))
                backup_raw = observed[path]
                if name == state['active']:
                    backup_path = self.saves / filename
                    observed.setdefault(backup_path, self._bytes(backup_path))
                    backup_raw = observed[backup_path]
                changed_raw = raw
                if filename == FILES[1] and backup_raw is not None:
                    backup_doc = self._doc(backup_raw)
                    for key, data in vehicles(backup_doc).items():
                        if key in totals:
                            data['MetersTravelled'] = totals[key]
                            baselines.setdefault(name, {})[key] = totals[key]
                    changed_raw = encode(backup_doc)
                changes[path] = changed_raw
                if name == state['active']:
                    path = self.saves / filename
                    observed.setdefault(path, self._bytes(path))
                    changes[path] = changed_raw
            # Keep remembered odometers for temporarily absent or sold vehicles.
            # Otherwise reappearance would count previously synchronized distance again.
            baselines.setdefault(name, {}).update({key: totals[key] for key in values[name]})
        state['ledger'] = {'totals': totals, 'baselines': baselines}
        changes[self.state_path] = encode(state)
        return state, observed, changes

    def sync_mileage(self, expected_preview=None):
        with self._lock():
            state, observed, changes = self._sync_plan()
            if expected_preview is not None:
                self._observe_switch_files(observed)
                if self._preview_token(observed, '__sync__') != expected_preview:
                    raise ProfileError('Saves changed since the mileage preview. Review a fresh preview and try again.')
            self._commit(changes, observed)
        return self.mileage_preview()
