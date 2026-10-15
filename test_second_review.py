"""Second adversarial review: profile identity and external-writer races."""
import unittest
import test_core as fixture
from test_core import save
from profile_core import ProfileError, encode

class SecondReviewTests(unittest.TestCase):
    setUp=fixture.CoreTests.setUp
    tearDown=fixture.CoreTests.tearDown
    write=fixture.CoreTests.write
    read=fixture.CoreTests.read

    def test_case_only_builtin_folder_rename_has_one_identity_and_safe_snapshot(self):
        (self.m.backups/'Playtest1').rename(self.m.backups/'playtest1')
        self.m.bind_active('Playtest2')
        names=self.m._names()
        self.assertEqual(1,sum(n.casefold()=='playtest1' for n in names))
        self.assertEqual(120,self.m.mileage_preview()['rows'][0]['combined_meters'])
        self.m.snapshot_all()

    def test_case_only_custom_folder_rename_preserves_ledger_baseline(self):
        self.m.bind_active('Playtest2')
        self.m.add_profile('Family')
        self.write('BackupSaves/Family',save(7))
        self.m.sync_mileage()
        (self.m.backups/'Family').rename(self.m.backups/'family')
        self.assertIn('Family',self.m._names())
        self.assertNotIn('family',self.m._names())
        row=self.m.mileage_preview()['rows'][0]
        self.assertEqual(127,row['combined_meters'])
        self.assertEqual(0,row['new_meters'])
        self.m.snapshot_all()

    def test_active_name_case_alias_uses_existing_baseline_identity(self):
        self.m.bind_active('Playtest2');self.m.sync_mileage()
        state=self.m._state();state['active']='playtest2'
        self.m.state_path.write_bytes(encode(state))
        self.assertEqual('Playtest2',self.m._state()['active'])
        row=self.m.mileage_preview()['rows'][0]
        self.assertEqual(120,row['combined_meters'])
        self.assertEqual(0,row['new_meters'])

    def test_case_aliased_duplicate_baseline_rejected_without_save_changes(self):
        self.m.bind_active('Playtest2');self.m.sync_mileage()
        state=self.m._state()
        state['ledger']['baselines']['playtest2']={'1':120}
        self.m.state_path.write_bytes(encode(state))
        before=(self.m.saves/'Player1.json').read_bytes()
        with self.assertRaises(ProfileError):self.m.sync_mileage()
        self.assertEqual(before,(self.m.saves/'Player1.json').read_bytes())

if __name__=='__main__':unittest.main()
