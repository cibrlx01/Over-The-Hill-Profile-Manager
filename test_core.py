import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from profile_core import Manager, ProfileError, FILES, vehicles

def save(meters, extra='keep'):
    return {'Header': {'Version': 10}, 'Profile': {'Unknown': extra, 'Inventory': {'Items': [{'Type': 'VehicleItem, Assembly-CSharp', 'Data': {'ItemId': 1, 'MetersTravelled': meters, 'Count': 1}}, {'Type': 'InventoryItem, Assembly-CSharp', 'Data': {'ItemId': 9}}]}}}

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.m = Manager(self.root)
        self.m._game_check = lambda: None
        self.write('Saves', save(20))
        self.write('BackupSaves/Playtest1', save(100))
        self.write('BackupSaves/Playtest2', save(10))
        (self.root / 'BackupSaves/Release1').mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, folder, data):
        path = self.root / folder
        path.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            (path / name).write_text(json.dumps(data))

    def read(self, folder='Saves', filename=FILES[0]):
        return json.loads((self.root / folder / filename).read_bytes())

    def test_bind_and_switch_roundtrip(self):
        with self.assertRaises(ProfileError): self.m.switch('Playtest1')
        self.m.bind_active('Playtest2')
        self.m.switch('Playtest1')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 100)
        self.assertEqual(vehicles(self.read('BackupSaves/Playtest2'))['1']['MetersTravelled'], 20)
        self.m.switch('Playtest2')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 20)

    def test_new_profile_requires_explicit_reset(self):
        self.m.bind_active('Playtest2')
        with self.assertRaises(ProfileError): self.m.switch('Release1')
        self.m.switch('Release1', allow_empty=True)
        self.assertFalse((self.m.saves / FILES[0]).exists())
        self.assertFalse((self.m.saves / FILES[1]).exists())
        self.write('Saves', save(3))
        self.m.switch('Playtest2')
        self.assertEqual(vehicles(self.read('BackupSaves/Release1'))['1']['MetersTravelled'], 3)

    def test_mileage_once_and_incremental(self):
        self.m.bind_active('Playtest2')
        self.assertEqual(self.m.mileage_preview()['rows'][0]['combined_meters'], 120)
        self.m.sync_mileage()
        self.assertEqual(self.m.mileage_preview()['rows'][0]['combined_meters'], 120)
        self.m.sync_mileage()
        self.write('Saves', save(125))
        self.assertEqual(self.m.mileage_preview()['rows'][0]['combined_meters'], 125)
        self.m.sync_mileage()
        self.m.switch('Playtest1')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 125)
        self.assertEqual(self.read()['Profile']['Unknown'], 'keep')

    def test_missing_vehicle_is_not_unlocked(self):
        doc = save(100)
        doc['Profile']['Inventory']['Items'].append({'Type': 'VehicleItem, Assembly-CSharp', 'Data': {'ItemId': 2, 'MetersTravelled': 30}})
        self.write('BackupSaves/Playtest1', doc)
        self.m.bind_active('Playtest2')
        self.m.sync_mileage()
        self.assertNotIn('2', vehicles(self.read()))
        self.assertEqual(vehicles(self.read('BackupSaves/Playtest1'))['2']['MetersTravelled'], 30)

    def test_rollback_on_write_failure(self):
        self.m.bind_active('Playtest2')
        original = self.m._atomic
        count = [0]
        def fail_once(path, raw):
            if path == self.m.saves / FILES[1] and not count[0]:
                count[0] += 1
                raise OSError('simulated interruption')
            return original(path, raw)
        with patch.object(self.m, '_atomic', side_effect=fail_once):
            with self.assertRaises(OSError): self.m.switch('Playtest1')
        self.assertEqual(self.m.status()['active'], 'Playtest2')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 20)
        self.assertFalse(self.m.journal.exists())

    def test_stale_read_rejected(self):
        self.m.bind_active('Playtest2')
        path = self.m.saves / FILES[0]
        observed = {path: path.read_bytes()}
        path.write_text(json.dumps(save(50)))
        with self.assertRaises(ProfileError): self.m._commit({path: b'bad'}, observed)
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 50)

    def test_corrupt_target_and_orphan_backup_rejected(self):
        self.m.bind_active('Playtest2')
        (self.m.backups / 'Playtest1' / FILES[0]).write_text('bad')
        with self.assertRaises(ProfileError): self.m.switch('Playtest1')
        (self.m.backups / 'Playtest1' / FILES[0]).unlink()
        with self.assertRaises(ProfileError): self.m.switch('Playtest1', allow_empty=True)

    def test_backup_fields_preserved(self):
        self.m.bind_active('Playtest2')
        (self.m.saves / FILES[1]).write_text(json.dumps(save(9, 'backup-specific')))
        self.m.sync_mileage()
        self.assertEqual(self.read(filename=FILES[1])['Profile']['Unknown'], 'backup-specific')
        self.assertEqual(vehicles(self.read(filename=FILES[1]))['1']['MetersTravelled'], 120)

    def test_startup_snapshots_append_exact_archived_and_live_bytes(self):
        self.m.bind_active('Playtest2')
        backup = self.m.backups / 'Playtest2' / '.backup'
        before = {p: p.read_bytes() for p in backup.glob('*')}
        self.m.snapshot_all()
        self.m.snapshot_all()
        after = {p: p.read_bytes() for p in backup.glob('*')}
        added = {p: raw for p, raw in after.items() if p not in before}
        self.assertEqual(len(added), 8)
        for p, raw in before.items(): self.assertEqual(after[p], raw)
        for p, raw in added.items():
            expected = self.m.saves if '_live.' in p.name else self.m.backups / 'Playtest2'
            self.assertEqual(raw, (expected / (FILES[1] if p.name.endswith('.bak') else FILES[0])).read_bytes())

    def test_failed_snapshot_prevents_switch(self):
        self.m.bind_active('Playtest2')
        original = {p: p.read_bytes() for p in self.root.rglob('Player1*') if '.backup' not in p.parts}
        with patch.object(self.m, '_snapshot_all_locked', side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.m.switch('Playtest1')
        for p, raw in original.items(): self.assertEqual(p.read_bytes(), raw)
        self.assertEqual(self.m.status()['active'], 'Playtest2')

    def test_add_profile_validates_windows_names_and_duplicates(self):
        for name in ('', '../escape', 'name?', 'NUL', 'con.txt', 'COM1', 'LPT³.txt', 'Ends.', 'Ends ', '.hidden', 'playtest1'):
            with self.subTest(name=name), self.assertRaises(ProfileError): self.m.add_profile(name)
        status = self.m.add_profile('Road Trip 2')
        self.assertIn('Road Trip 2', [p['name'] for p in status['profiles']])
        self.assertEqual(list((self.m.backups / 'Road Trip 2').iterdir()), [])

    def test_unbound_snapshot_preserves_live_without_binding(self):
        result = self.m.snapshot_all()
        self.assertEqual(result['files'], 6)
        self.assertFalse(self.m.state_path.exists())
        self.assertEqual(len(list((self.m.backups / '.backup').glob('*live_unbound*'))), 2)

if __name__ == '__main__': unittest.main()
