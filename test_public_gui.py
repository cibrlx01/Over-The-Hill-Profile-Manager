"""Public first-use and display tests; only temporary synthetic saves are used."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import profile_manager as gui
from test_core import save


class PublicGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name) / 'game'
        self.settings = Path(self.tmp.name) / 'settings'
        self.patch = patch.object(gui, 'APP_DATA', self.settings)
        self.patch.start()
        self.window = tk.Tk()
        self.window.withdraw()

    def tearDown(self):
        self.window.destroy()
        self.patch.stop()
        self.tmp.cleanup()

    def app(self, startup_backup=True):
        return gui.ProfileApp(self.window, self.root, startup_backup=startup_backup, poll_game=False, quiet=True)

    def write_save(self):
        folder = self.root / 'Saves'
        folder.mkdir(parents=True)
        for name in ('Player1.json', 'Player1.json.bak'):
            (folder / name).write_text(json.dumps(save(1200)), encoding='utf-8')

    def test_first_open_missing_folder_does_not_create_game_or_settings(self):
        app = self.app()
        self.assertFalse(self.root.exists())
        self.assertFalse(self.settings.exists())
        self.assertEqual(app.setup_name.get(), 'Main Profile')
        self.assertIsNone(app.active)

    def test_existing_live_save_untouched_until_explicit_setup(self):
        self.write_save()
        before = {p.name: p.read_bytes() for p in (self.root / 'Saves').iterdir()}
        app = self.app()
        self.assertFalse((self.root / 'BackupSaves').exists())
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'Saves').iterdir()})
        app.manager._game_check = lambda: None
        app.setup_name.set('My Journey')
        app.setup_description.set('First trip')
        app.bind_current()
        self.assertEqual(app.active, 'My Journey')
        self.assertEqual(app.profiles['My Journey']['description'], 'First trip')
        self.assertEqual(gui.saved_root(), self.root)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / 'Saves').iterdir()})

    def test_saved_saves_folder_normalized_and_invalid_settings_fall_back(self):
        gui.remember_root(self.root / 'Saves')
        self.assertEqual(gui.saved_root(), self.root)
        (self.settings / 'settings.json').write_text('not json')
        with patch.object(gui, 'detect_root', return_value=self.root):
            self.assertEqual(gui.saved_root(), self.root)

    def test_vehicle_table_and_switch_preview_show_names_only(self):
        app = self.app(startup_backup=False)
        app.names = {'1': 'Protector'}
        app.preview = {'initialized': True, 'profiles': [], 'rows': [
            {'vehicle_id': '1', 'combined_meters': 1200, 'new_meters': 1},
            {'vehicle_id': '999', 'combined_meters': 500, 'new_meters': 1}]}
        app.render_mileage()
        self.assertEqual(app.tree.item('1', 'values')[0], 'Protector')
        self.assertEqual(app.tree.item('999', 'values')[0], 'Unknown vehicle')
        app.game_state = False
        preview = dict(app.preview, active='Old', target='New', allow_empty=False)
        dialog = gui.SwitchPreviewDialog(app, preview)
        self.assertEqual(dialog.tree.item('1', 'values')[0], 'Protector')
        self.assertEqual(dialog.tree.item('999', 'values')[0], 'Unknown vehicle')
        dialog.cancel()

    def test_rename_and_description_wiring(self):
        app = self.app(startup_backup=False)
        app.selected.set('Old')
        app.manager.rename_profile = Mock()
        app.manager.set_description = Mock()
        app.refresh = Mock()
        with patch.object(gui.simpledialog, 'askstring', return_value='New'):
            app.rename_profile()
        app.manager.rename_profile.assert_called_once_with('Old', 'New')
        with patch.object(gui.simpledialog, 'askstring', return_value='My notes'):
            app.edit_description()
        app.manager.set_description.assert_called_once_with('New', 'My notes')

    def test_date_display(self):
        self.assertEqual(gui.format_last_played('2026-10-15T07:45:59.123'), '2026-10-15 - 07:45')
        self.assertEqual(gui.format_last_played('bad'), '-')


if __name__ == '__main__':
    unittest.main()
