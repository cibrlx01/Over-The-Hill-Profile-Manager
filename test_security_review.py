"""Independent security and data-integrity regression cases; temporary fixtures only."""
import base64
import json
import unittest
from pathlib import Path
import test_core as fixture
from test_core import save
from profile_core import FILES, ProfileError, encode, vehicles

class SecurityReviewTests(unittest.TestCase):
    setUp=fixture.CoreTests.setUp
    tearDown=fixture.CoreTests.tearDown
    write=fixture.CoreTests.write
    read=fixture.CoreTests.read

    def bind(self):
        self.m.bind_active('Playtest2')
    def originals(self):
        return {p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name in FILES}
    def assert_originals(self,before):
        self.assertEqual(before,self.originals())
    def journal(self,entries):
        self.m.journal.write_bytes(encode({'version':1,'before':entries}))
    def test_negative_or_inconsistent_ledger_never_changes_saves(self):
        self.bind()
        initial=self.m._state()
        ledgers=[
            {'totals':{'1':-1000},'baselines':{'Playtest2':{'1':20},'Playtest1':{'1':100}}},
            {'totals':{'1':0},'baselines':{'Playtest2':{'1':20}}},
            {'totals':{},'baselines':{'Playtest2':{'1':20}}},
            {'totals':{'1':True},'baselines':{}},
            {'totals':{'1':'100'},'baselines':{}},
            {'totals':{'1':100},'baselines':{'../bad':{'1':20}}},
        ]
        for ledger in ledgers:
            with self.subTest(ledger=ledger):
                state=dict(initial,ledger=ledger)
                self.m.state_path.write_bytes(encode(state))
                before=self.originals()
                with self.assertRaises(ProfileError):self.m.sync_mileage()
                self.assert_originals(before)
    def test_nonfinite_state_rejected_before_changes(self):
        self.bind()
        state=self.m._state()
        for value in [float('nan'),float('inf')]:
            state['ledger']={'totals':{'1':value},'baselines':{}}
            self.m.state_path.write_text(json.dumps(state),encoding='utf-8')
            before=self.originals()
            with self.assertRaises(ProfileError):self.m.sync_mileage()
            self.assert_originals(before)
    def test_disappearing_reappearing_vehicle_does_not_recount(self):
        self.bind();self.m.sync_mileage()
        missing=save(120);missing['Profile']['Inventory']['Items']=[]
        self.write('Saves',missing);self.m.sync_mileage()
        self.write('Saves',save(120))
        row=self.m.mileage_preview()['rows'][0]
        self.assertEqual(120,row['combined_meters'])
        self.assertEqual(0,row['new_meters'])
    def test_recovery_unrelated_file_rejected(self):
        self.bind()
        unrelated=self.root/'unrelated.txt';unrelated.write_bytes(b'important')
        self.journal({'unrelated.txt':base64.b64encode(b'changed').decode()})
        before=self.originals()
        with self.assertRaises(ProfileError):self.m.recover()
        self.assertEqual(b'important',unrelated.read_bytes())
        self.assert_originals(before)
    def test_recovery_valid_first_then_unsafe_entry_does_not_partial_write(self):
        self.bind();before=self.originals()
        self.journal({'Saves/Player1.json':base64.b64encode(encode(save(999))).decode(),'../outside':None})
        with self.assertRaises(ProfileError):self.m.recover()
        self.assert_originals(before)
    def test_recovery_valid_first_then_bad_base64_does_not_partial_write(self):
        self.bind();before=self.originals()
        self.journal({'Saves/Player1.json':base64.b64encode(encode(save(999))).decode(),'Saves/Player1.json.bak':'!!!bad-base64!!!'})
        with self.assertRaises(ProfileError):self.m.recover()
        self.assert_originals(before)
    def test_recovery_duplicate_alias_rejected_before_changes(self):
        self.bind();before=self.originals()
        self.journal({'Saves/Player1.json':base64.b64encode(encode(save(999))).decode(),'Saves/../Saves/Player1.json':None})
        with self.assertRaises(ProfileError):self.m.recover()
        self.assert_originals(before)
    def test_valid_pair_and_state_recovery_succeeds(self):
        self.bind()
        state=self.m.state_path.read_bytes()
        primary=encode(save(777));backup=encode(save(776))
        self.journal({'Saves/Player1.json':base64.b64encode(primary).decode(),'Saves/Player1.json.bak':base64.b64encode(backup).decode(),str(self.m.state_path.relative_to(self.root)):base64.b64encode(state).decode()})
        self.m.recover()
        self.assertEqual(primary,(self.m.saves/FILES[0]).read_bytes())
        self.assertEqual(backup,(self.m.saves/FILES[1]).read_bytes())
        self.assertFalse(self.m.journal.exists())

    def test_missing_custom_active_folder_still_counts_live_save(self):
        self.m.state_path.parent.mkdir(parents=True,exist_ok=True)
        self.m.state_path.write_bytes(encode({'version':1,'active':'CustomActive','ledger':None}))
        self.assertFalse((self.m.backups/'CustomActive').exists())
        preview=self.m.switch_preview('Playtest1')
        self.assertEqual(20,preview['rows'][0]['profiles']['CustomActive'])
        self.assertEqual(130,preview['rows'][0]['combined_meters'])
        self.assertIn('CustomActive',[p['name'] for p in self.m.status()['profiles']])

if __name__=='__main__':unittest.main()

