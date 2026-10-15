"""Second independent review regression tests; temporary saves only."""
import unittest
from unittest.mock import patch
import test_core as fixture
from test_core import save
from profile_core import FILES, ProfileError, encode, vehicles

class FreshReview(unittest.TestCase):
    setUp = fixture.CoreTests.setUp
    tearDown = fixture.CoreTests.tearDown
    write = fixture.CoreTests.write

    def test_backup_only_vehicle_is_not_recounted_after_restore(self):
        missing = save(100)
        missing['Profile']['Inventory']['Items'] = []
        self.write('BackupSaves/Playtest1', missing)
        folder = self.m.backups / 'Playtest1'
        (folder / FILES[1]).write_bytes(encode(save(100)))
        self.m.bind_active('Playtest2')
        self.m.sync_mileage()
        self.assertEqual(20, self.m.mileage_preview()['rows'][0]['combined_meters'])
        (folder / FILES[0]).write_bytes((folder / FILES[1]).read_bytes())
        preview = self.m.mileage_preview()
        self.assertEqual(20, preview['rows'][0]['combined_meters'])
        self.assertEqual(0, preview['rows'][0]['new_meters'])

    def test_sync_refuses_stale_review_and_accepts_fresh_review(self):
        self.m.bind_active('Playtest2')
        self.m.sync_mileage()
        self.write('Saves', save(121))
        reviewed = self.m.mileage_preview()
        self.assertEqual(121, reviewed['rows'][0]['combined_meters'])
        self.write('Saves', save(130))
        before = {path: path.read_bytes() for path in self.root.rglob('*')
                  if path.is_file() and path.name in FILES}
        state_before = self.m.state_path.read_bytes()
        with self.assertRaises(ProfileError):
            self.m.sync_mileage(expected_preview=reviewed['token'])
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob('*')
                                 if path.is_file() and path.name in FILES})
        self.assertEqual(state_before, self.m.state_path.read_bytes())
        fresh = self.m.mileage_preview()
        result = self.m.sync_mileage(expected_preview=fresh['token'])
        self.assertEqual(130, result['rows'][0]['combined_meters'])
        self.assertEqual(0, result['rows'][0]['new_meters'])

    def test_change_during_journal_archive_is_preserved_without_rollback(self):
        self.m.bind_active('Playtest2')
        before = {path: path.read_bytes() for path in self.root.rglob('*')
                  if path.is_file() and path.name in FILES}
        state_before = self.m.state_path.read_bytes()
        original_atomic = self.m._atomic
        changed = False
        live_paths = {self.m.saves / filename for filename in FILES}
        writes_after_external_change = []
        def inject(path, raw):
            nonlocal changed
            if changed and (path in before or path == self.m.state_path):
                writes_after_external_change.append(path)
            original_atomic(path, raw)
            if path.parent == self.m.meta / 'history' and not changed:
                self.write('Saves', save(999))
                changed = True
        with patch.object(self.m, '_atomic', side_effect=inject):
            with self.assertRaises(ProfileError):
                self.m.sync_mileage()
        self.assertTrue(changed)
        self.assertFalse(writes_after_external_change)
        self.assertFalse(self.m.journal.exists())
        self.assertEqual(state_before, self.m.state_path.read_bytes())
        for path, raw in before.items():
            if path in live_paths:
                self.assertEqual(999, vehicles(self.m._doc(path.read_bytes()))['1']['MetersTravelled'])
            else:
                self.assertEqual(raw, path.read_bytes())

if __name__ == '__main__':
    unittest.main()
