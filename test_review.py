import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from profile_core import Manager, ProfileError, FILES

def doc(miles, extra=None):
    return json.dumps({'Profile':{'Inventory':{'Items':[{'Type':'VehicleItem, Assembly','Data':{'ItemId':k,'MetersTravelled':v,'Unrelated':'keep'}} for k,v in miles.items()]}}, 'Unrelated':extra}).encode()

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.m=Manager(self.root)
        self.m._game_check=lambda:None
        self.put('Saves',{'car':10})
        self.put('BackupSaves/Playtest1',{'car':20})
        self.m.bind_active('Playtest2')
    def put(self, folder, miles, both=True):
        path=self.root/folder
        path.mkdir(parents=True,exist_ok=True)
        (path/FILES[0]).write_bytes(doc(miles,'preserve'))
        if both:(path/FILES[1]).write_bytes(doc(miles,'backup-preserve'))
    def read(self,folder):
        return json.loads((self.root/folder/FILES[0]).read_bytes())
    def test_switch_preserves_pair_exactly(self):
        before=[(self.root/'Saves'/f).read_bytes() for f in FILES]
        incoming=[(self.root/'BackupSaves/Playtest1'/f).read_bytes() for f in FILES]
        self.m.switch('Playtest1')
        self.assertEqual(before,[(self.root/'BackupSaves/Playtest2'/f).read_bytes() for f in FILES])
        self.assertEqual(incoming,[(self.root/'Saves'/f).read_bytes() for f in FILES])
    def test_blank_requires_confirmation_and_clears_both(self):
        with self.assertRaises(ProfileError):self.m.switch('Release1')
        self.m.switch('Release1',allow_empty=True)
        self.assertFalse(any((self.root/'Saves'/f).exists() for f in FILES))
        self.m.switch('Playtest2')
        self.assertTrue(all((self.root/'Saves'/f).exists() for f in FILES))
    def test_repeated_sync_then_switch_is_idempotent(self):
        self.assertEqual(30,self.m.sync_mileage()['rows'][0]['combined_meters'])
        self.assertEqual(30,self.m.sync_mileage()['rows'][0]['combined_meters'])
        self.m.switch('Playtest1')
        self.assertEqual(30,self.m.sync_mileage()['rows'][0]['combined_meters'])
        self.put('Saves',{'car':34})
        self.assertEqual(34,self.m.sync_mileage()['rows'][0]['combined_meters'])
        self.assertEqual('preserve',self.read('Saves')['Unrelated'])
    def test_failure_mid_pair_rolls_back_every_file_and_state(self):
        paths=[self.root/'Saves'/f for f in FILES]+[self.m.state_path]
        before={p:p.read_bytes() for p in paths}
        atomic=self.m._atomic
        failed=False
        def fail(path,raw):
            nonlocal failed
            if path==self.root/'Saves'/FILES[1] and not failed:
                failed=True
                raise OSError('simulated write failure')
            return atomic(path,raw)
        with patch.object(self.m,'_atomic',side_effect=fail):
            with self.assertRaises(OSError):self.m.switch('Playtest1')
        self.assertEqual(before,{p:p.read_bytes() for p in paths})
        self.assertFalse(self.m.journal.exists())
    def test_orphan_backup_cannot_be_started_as_blank(self):
        p=self.root/'BackupSaves/Release1'
        p.mkdir(parents=True)
        (p/FILES[1]).write_bytes(doc({'car':1}))
        with self.assertRaises(ProfileError):self.m.switch('Release1',allow_empty=True)
        self.assertEqual('Playtest2',self.m.status()['active'])
    def test_corrupt_incoming_never_changes_live(self):
        before=(self.root/'Saves'/FILES[0]).read_bytes()
        (self.root/'BackupSaves/Playtest1'/FILES[1]).write_bytes(b'broken')
        with self.assertRaises(ProfileError):self.m.switch('Playtest1')
        self.assertEqual(before,(self.root/'Saves'/FILES[0]).read_bytes())




class LedgerReviewTests(unittest.TestCase):
    setUp=ReviewTests.setUp
    put=ReviewTests.put
    read=ReviewTests.read
    def test_decreased_mileage_refuses_without_writes(self):
        self.m.sync_mileage()
        self.put('Saves',{'car':1})
        before=(self.root/'Saves'/FILES[0]).read_bytes()
        with self.assertRaises(ProfileError):self.m.sync_mileage()
        self.assertEqual(before,(self.root/'Saves'/FILES[0]).read_bytes())
    def test_missing_vehicle_does_not_create_or_unlock_vehicle(self):
        self.put('Saves',{'other':5})
        result=self.m.sync_mileage()
        rows={r['vehicle_id']:r['combined_meters'] for r in result['rows']}
        self.assertEqual({'car':20,'other':5},rows)
        items=self.read('Saves')['Profile']['Inventory']['Items']
        self.assertEqual(['other'],[i['Data']['ItemId'] for i in items])
    def test_backup_retains_its_own_unrelated_progress(self):
        self.m.sync_mileage()
        backup=json.loads((self.root/'Saves'/FILES[1]).read_bytes())
        self.assertEqual('backup-preserve',backup['Unrelated'])
        self.assertEqual(30,backup['Profile']['Inventory']['Items'][0]['Data']['MetersTravelled'])

if __name__=='__main__':unittest.main()

