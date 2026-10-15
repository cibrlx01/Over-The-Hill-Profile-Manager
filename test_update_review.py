import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from profile_core import Manager, ProfileError, FILES, encode

class UpdateReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.m=Manager(self.root)
        self.m._game_check=lambda:None
        self.pair('Saves',b'live primary',b'live bak')
        self.pair('BackupSaves/Playtest2',b'archive primary',b'archive bak')
        self.pair('BackupSaves/Playtest1',b'old primary',b'old bak')
        self.m.meta.mkdir(parents=True)
        self.m.state_path.write_bytes(encode({'version':1,'active':'Playtest2','ledger':None}))
    def pair(self,folder,primary,backup):
        p=self.root/folder
        p.mkdir(parents=True,exist_ok=True)
        (p/FILES[0]).write_bytes(primary)
        (p/FILES[1]).write_bytes(backup)
    def snapshots(self):
        return {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and '.backup' in p.parts}
    def test_raw_corrupt_files_and_distinct_live_archive_retained(self):
        self.assertEqual(7,self.m.snapshot_all()['files'])
        snapshots=self.snapshots()
        self.assertEqual(7,len(snapshots))
        for folder,expected in [('Playtest2',{b'live primary',b'live bak',b'archive primary',b'archive bak'}),('Playtest1',{b'old primary',b'old bak'})]:
            self.assertEqual(expected,{raw for p,raw in snapshots.items() if folder in p.parts})
        self.assertEqual(b'live primary',(self.root/'Saves'/FILES[0]).read_bytes())
    def test_each_start_appends_never_overwrites(self):
        self.m.snapshot_all()
        before=self.snapshots()
        self.m.snapshot_all()
        after=self.snapshots()
        self.assertEqual(14,len(after))
        self.assertTrue(all(after[p]==raw for p,raw in before.items()))
    def test_backup_failure_prevents_profile_creation(self):
        with patch.object(self.m,'_snapshot_all_locked',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.m.add_profile('Release2')
        self.assertFalse((self.root/'BackupSaves/Release2').exists())
    def test_actual_backup_write_failure_prevents_commit(self):
        before=(self.root/'Saves'/FILES[0]).read_bytes()
        change=self.root/'Saves'/FILES[0]
        real_open=Path.open
        def fail_backup(path,*args,**kwargs):
            if '.backup' in path.parts and args and args[0]=='xb':raise OSError('disk full')
            return real_open(path,*args,**kwargs)
        with patch.object(Path,'open',fail_backup):
            with self.assertRaises(OSError):self.m._commit({change:b'changed'},{change:before})
        self.assertEqual(before,change.read_bytes())
        self.assertFalse(self.m.journal.exists())
    def test_new_slot_discovered_without_any_save_files(self):
        status=self.m.add_profile('Family Profile')
        profile=next(p for p in status['profiles'] if p['name']=='Family Profile')
        self.assertFalse(profile['exists'])
        self.assertEqual([],list((self.root/'BackupSaves/Family Profile').iterdir()))
        self.assertEqual(7,len(self.snapshots()))
    def test_unsafe_and_case_duplicate_names_rejected(self):
        names=['../outside','bad/name','bad\\name','.hidden','CON','aux.txt','NUL','LPT1','COM9','abc.','abc ','bad:name','playTEST2','', 'x'*81]
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(ProfileError):self.m.add_profile(name)
        self.assertEqual(0,len(self.snapshots()))

if __name__=='__main__':unittest.main()
