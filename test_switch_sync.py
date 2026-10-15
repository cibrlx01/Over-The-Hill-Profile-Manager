from unittest.mock import patch
from test_core import CoreTests, save
from profile_core import FILES, ProfileError, vehicles

class SwitchSyncTests(CoreTests):
    def test_switch_sync_counts_only_new_distance(self):
        self.m.bind_active('Playtest2')
        self.m.switch('Playtest1', sync_mileage=True)
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 120)
        self.write('Saves', save(121))
        self.m.switch('Playtest2', sync_mileage=True)
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 121)
        self.m.switch('Playtest1', sync_mileage=True)
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 121)

    def test_sync_failure_never_switches(self):
        self.m.bind_active('Playtest2')
        self.m.sync_mileage()
        self.write('Saves', save(2))
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file() and p.name != 'manager.lock'}
        with self.assertRaises(ProfileError):
            self.m.switch('Playtest1', sync_mileage=True)
        for p, raw in before.items():
            self.assertEqual(p.read_bytes(), raw)
        self.assertEqual(self.m.status()['active'], 'Playtest2')

    def test_atomic_sync_switch_rollback(self):
        self.m.bind_active('Playtest2')
        original = self.m._atomic
        failed = []
        def fail(path, raw):
            if path == self.m.saves / FILES[1] and not failed:
                failed.append(True)
                raise OSError('simulated failure')
            return original(path, raw)
        with patch.object(self.m, '_atomic', side_effect=fail):
            with self.assertRaises(OSError):
                self.m.switch('Playtest1', sync_mileage=True)
        self.assertEqual(self.m.status()['active'], 'Playtest2')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'], 20)
        self.assertEqual(vehicles(self.read('BackupSaves/Playtest1'))['1']['MetersTravelled'], 100)
        self.assertIsNone(self.m._state()['ledger'])

    def test_empty_target_stays_empty_with_tracking_retained(self):
        self.m.bind_active('Playtest2')
        self.m.switch('Release1', allow_empty=True, sync_mileage=True)
        self.assertFalse((self.m.saves / FILES[0]).exists())
        self.assertEqual(self.m._state()['ledger']['totals']['1'],120)
        self.m.switch('Playtest2', sync_mileage=True)
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'],120)

    def test_preview_reports_only_new_distance(self):
        self.m.bind_active('Playtest2')
        self.assertEqual(self.m.mileage_preview()['rows'][0]['new_meters'],120)
        self.m.sync_mileage()
        self.assertEqual(self.m.mileage_preview()['rows'][0]['new_meters'],0)
        self.write('Saves',save(121))
        row=self.m.mileage_preview()['rows'][0]
        self.assertEqual(row['new_meters'],1)
        self.assertEqual(row['combined_meters'],121)

    def test_summary_uses_live_distance_for_current_profile(self):
        self.m.bind_active('Playtest2')
        profiles={row['name']:row for row in self.m.status()['profiles']}
        self.assertEqual(profiles['Playtest2']['total_meters'],20)
        self.assertEqual(profiles['Playtest1']['total_meters'],100)
        self.assertEqual(profiles['Release1']['total_meters'],0)

    def test_change_after_sync_planning_refuses_switch(self):
        self.m.bind_active('Playtest2')
        plan=self.m._sync_plan
        def change_during_plan():
            result=plan()
            self.write('Saves',save(999))
            return result
        with patch.object(self.m,'_sync_plan',side_effect=change_during_plan):
            with self.assertRaises(ProfileError):
                self.m.switch('Playtest1',sync_mileage=True)
        self.assertEqual(self.m.status()['active'],'Playtest2')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'],999)
        self.assertEqual(vehicles(self.read('BackupSaves/Playtest1'))['1']['MetersTravelled'],100)

    def test_preview_is_read_only_and_accepts_unchanged_saves(self):
        self.m.bind_active('Playtest2')
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        preview=self.m.switch_preview('Playtest1')
        self.assertFalse(preview['initialized'])
        self.assertEqual(preview['rows'][0]['combined_meters'],120)
        self.assertEqual(preview['rows'][0]['current_meters'],0)
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.m.switch('Playtest1',sync_mileage=True,expected_preview=preview['token'])
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'],120)

    def test_stale_preview_refuses_without_losing_new_distance(self):
        self.m.bind_active('Playtest2')
        preview=self.m.switch_preview('Playtest1')
        self.write('Saves',save(999))
        with self.assertRaises(ProfileError):
            self.m.switch('Playtest1',sync_mileage=True,expected_preview=preview['token'])
        self.assertEqual(self.m.status()['active'],'Playtest2')
        self.assertEqual(vehicles(self.read())['1']['MetersTravelled'],999)

    def test_preview_empty_target_and_missing_vehicles(self):
        self.m.bind_active('Playtest2')
        preview=self.m.switch_preview('Release1')
        self.assertTrue(preview['allow_empty'])
        self.assertIsNone(preview['rows'][0]['profiles'].get('Release1'))
        self.m.switch('Release1',allow_empty=True,sync_mileage=True,expected_preview=preview['token'])
        self.assertFalse((self.m.saves/FILES[0]).exists())

    def test_reappearing_vehicle_does_not_recount_old_distance(self):
        self.m.bind_active('Playtest2')
        self.m.sync_mileage()
        missing=save(0)
        missing['Profile']['Inventory']['Items']=[item for item in missing['Profile']['Inventory']['Items'] if not item['Type'].startswith('VehicleItem,')]
        self.write('Saves',missing)
        self.m.sync_mileage()
        self.write('Saves',save(120))
        row=self.m.mileage_preview()['rows'][0]
        self.assertEqual(row['combined_meters'],120)
        self.assertEqual(row['new_meters'],0)
