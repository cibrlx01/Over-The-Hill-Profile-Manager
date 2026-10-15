import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from profile_core import Manager, ProfileError, FILES, encode
from test_core import save

class PublicCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root=Path(self.tmp.name);self.m=Manager(self.root);self.m._game_check=lambda:None
        self.m.saves.mkdir()
        for i,f in enumerate(FILES): (self.m.saves/f).write_bytes(encode(save(20+i)))
    def tearDown(self): self.tmp.cleanup()
    def test_neutral_initialize(self):
        self.assertEqual(self.m._names(),[])
        original=[(self.m.saves/f).read_bytes() for f in FILES]
        self.m.initialize_profile('My Journey')
        self.assertEqual(self.m._state()['active'],'My Journey')
        for f,b in zip(FILES,original):
            self.assertEqual((self.m.saves/f).read_bytes(),b)
            self.assertEqual((self.m.backups/'My Journey'/f).read_bytes(),b)
        self.assertTrue(list(self.m.backups.glob('.backup/*opened*')) or list(self.m.backups.glob('.backup/*before_change*')))
        with self.assertRaises(ProfileError):self.m.initialize_profile('Other')
    def test_rename_preserves_tracking_and_history(self):
        self.m.initialize_profile('First');self.m.set_description('First','Original');self.m.sync_mileage()
        marker=self.m.backups/'First'/'.backup'/'keep.txt';marker.write_text('history')
        baseline=self.m._state()['ledger']['baselines']['First']
        self.m.rename_profile('first','Renamed')
        state=self.m._state()
        self.assertEqual(state['active'],'Renamed');self.assertEqual(state['descriptions']['Renamed'],'Original')
        self.assertEqual(state['ledger']['baselines']['Renamed'],baseline)
        self.assertEqual((self.m.backups/'Renamed'/'.backup'/'keep.txt').read_text(),'history')
        self.assertFalse((self.m.backups/'First').exists())
        self.m.add_profile('Empty');self.m.set_description('Empty','Future');self.m.rename_profile('Empty','Future')
        self.assertEqual(self.m._state()['descriptions']['Future'],'Future')
    def test_invalid_names_and_collision(self):
        self.m.initialize_profile('First');self.m.add_profile('Other')
        for name in ['first','OTHER','../outside','CON','bad.','x/y','']:
            with self.subTest(name=name),self.assertRaises(ProfileError):self.m.rename_profile('First',name)
        self.assertEqual(self.m._state()['active'],'First')
    def journal(self,moved):
        self.m.initialize_profile('First');raw=self.m.state_path.read_bytes()
        record={'version':1,'before':{str(self.m.state_path.relative_to(self.root)):base64.b64encode(raw).decode()},'directory_rename':{'old':'First','new':'Second'}}
        if moved:
            (self.m.backups/'First').rename(self.m.backups/'Second')
        self.m._atomic(self.m.journal,encode(record))
    def test_recover_before_rename(self):
        self.journal(False);self.m.recover();self.assertTrue((self.m.backups/'First').is_dir());self.assertFalse(self.m.journal.exists())
    def test_recover_after_rename_before_state_write(self):
        self.journal(True);self.m.recover();self.assertTrue((self.m.backups/'First').is_dir());self.assertFalse((self.m.backups/'Second').exists())
    def test_recover_after_state_write(self):
        self.journal(True);state=self.m._state();state['active']='Second';self.m._atomic(self.m.state_path,encode(state))
        self.m.recover();self.assertEqual(self.m._state()['active'],'First')
    def test_reject_invalid_rename_recovery(self):
        self.journal(True);record=json.loads(self.m.journal.read_bytes());record['directory_rename']['new']='../escape';self.m._atomic(self.m.journal,encode(record))
        with self.assertRaises(ProfileError):self.m.recover()
        self.assertTrue((self.m.backups/'Second').is_dir());self.assertFalse((self.m.backups/'First').exists())
    def test_rename_state_failure_rolls_back(self):
        self.m.initialize_profile('First');raw=self.m.state_path.read_bytes();atomic=self.m._atomic;once=[False]
        def fail(path,data):
            if path==self.m.state_path and not once[0]:once[0]=True;raise OSError('injected')
            return atomic(path,data)
        with patch.object(self.m,'_atomic',side_effect=fail),self.assertRaises(OSError):self.m.rename_profile('First','Second')
        self.assertEqual(self.m.state_path.read_bytes(),raw);self.assertTrue((self.m.backups/'First').exists());self.assertFalse((self.m.backups/'Second').exists())
    def test_rename_preflight_preserves_external_state(self):
        self.m.initialize_profile('First')
        state=self.m._state();state['descriptions']={'First':'External newer note'}
        external=encode(state);atomic=self.m._atomic
        def inject(path,data):
            atomic(path,data)
            if path.parent.name=='history' and self.m.journal.exists():
                self.m.state_path.write_bytes(external)
        with patch.object(self.m,'_atomic',side_effect=inject),self.assertRaises(ProfileError):
            self.m.rename_profile('First','Second')
        self.assertEqual(self.m.state_path.read_bytes(),external)
        self.assertTrue((self.m.backups/'First').is_dir())
        self.assertFalse((self.m.backups/'Second').exists())
        self.assertFalse(self.m.journal.exists())
    def test_initialize_failure_leaves_no_profile(self):
        original=[(self.m.saves/f).read_bytes() for f in FILES]
        atomic=self.m._atomic;once=[False]
        def fail(path,data):
            if path==self.m.state_path and not once[0]:once[0]=True;raise OSError('injected')
            return atomic(path,data)
        with patch.object(self.m,'_atomic',side_effect=fail),self.assertRaises(OSError):self.m.initialize_profile('First')
        self.assertFalse((self.m.backups/'First').exists())
        self.assertFalse(self.m.state_path.exists())
        for f,b in zip(FILES,original):self.assertEqual((self.m.saves/f).read_bytes(),b)
        self.m.initialize_profile('First')
    def test_recovered_initialize_reuses_backup_only_folder(self):
        atomic=self.m._atomic
        def crash(path,data):
            if path==self.m.backups/'First'/FILES[1]:raise SystemExit('simulated crash')
            if path==self.m.backups/'First'/FILES[0] and data is None:raise SystemExit('rollback interrupted')
            return atomic(path,data)
        with patch.object(self.m,'_atomic',side_effect=crash),self.assertRaises(SystemExit):self.m.initialize_profile('First')
        self.assertTrue(self.m.journal.exists())
        self.m.recover()
        folder=self.m.backups/'First'
        saved_backups=list((folder/'.backup').iterdir())
        self.assertTrue(saved_backups)
        self.m.initialize_profile('first')
        self.assertEqual(self.m._state()['active'],'First')
        self.assertTrue(all(p.exists() for p in saved_backups))
    def test_empty_created_slot_initializes(self):
        self.m.add_profile('First');self.m.initialize_profile('First')
        self.assertEqual(self.m._state()['active'],'First')
    def test_existing_personal_state(self):
        self.m.initialize_profile('Playtest2');self.m.sync_mileage();self.m.rename_profile('Playtest2','Main')
        self.assertEqual(self.m._state()['active'],'Main');self.assertEqual(self.m.mileage_preview()['rows'][0]['combined_meters'],20)
if __name__=='__main__':unittest.main()
