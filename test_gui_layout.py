"""Synthetic GUI checks; never reads or changes the real game folder."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from profile_manager import ProfileApp


class GuiLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.window = tk.Tk()
        self.app = ProfileApp(self.window, Path(self.tmp.name), startup_backup=False, poll_game=False)
        self.app.manager.status = Mock(return_value={'active': 'Playtest2', 'profiles': [
            {'name': f'Journey{i}', 'exists': True, 'vehicles': 4, 'total_meters': 1000}
            for i in range(40)] + [{'name': 'Playtest2', 'exists': True, 'vehicles': 4, 'total_meters': 3000}]})
        self.preview = {'initialized': True, 'profiles': ['Playtest2'], 'token': 'mileage-token', 'rows': [
            {'vehicle_id': 'x', 'profiles': {'Playtest2': 3000}, 'combined_meters': 6000, 'new_meters': 2000}]}
        self.app.manager.mileage_preview = Mock(return_value=self.preview)
        self.app.refresh()
        self.app.game_state = False
        self.app.update_controls()

    def tearDown(self):
        self.window.destroy()
        self.tmp.cleanup()

    def test_summary_and_bounds(self):
        self.assertEqual(self.app.combined_card_text.get(), '6.00 km')
        self.assertEqual(self.app.new_card_text.get(), '2.00 km')
        self.assertEqual(len(self.app.profile_tree.get_children()), 41)
        checked = 0
        for width, height in [(1320, 900), (880, 820)]:
            self.window.geometry(f'{width}x{height}')
            self.window.update()
            for tab in range(2):
                self.app.tabs.select(tab)
                self.window.update()
                for control in (self.app.switch_button, self.app.capture_button, self.app.add_button,
                                self.app.sync_button, self.app.play_button, self.app.profile_tree,
                                self.app.tree, self.app.game_badge):
                    if not control.winfo_ismapped():
                        continue
                    x = control.winfo_rootx() - self.window.winfo_rootx()
                    y = control.winfo_rooty() - self.window.winfo_rooty()
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x + control.winfo_width(), self.window.winfo_width())
                    self.assertLessEqual(y + control.winfo_height(), self.window.winfo_height())
                    if control is self.app.profile_tree:
                        self.assertGreaterEqual(control.winfo_height(), 96)
                    checked += 1
        self.assertGreaterEqual(checked, 16)

    def test_switch_and_sync_wiring(self):
        preview = dict(self.preview, active='Playtest2', target='Journey0', allow_empty=False, token='review-token')
        self.app.selected.set('Journey0')
        self.app.manager.switch_preview = Mock(return_value=preview)
        self.app.manager.switch = Mock()
        with patch('profile_manager.SwitchPreviewDialog') as dialog:
            dialog.return_value.show.return_value = True
            self.app.switch()
        self.app.manager.switch.assert_called_once_with('Journey0', allow_empty=False, sync_mileage=True, expected_preview='review-token')
        self.app.manager.sync_mileage = Mock()
        with patch('profile_manager.messagebox.askyesno', return_value=True):
            self.app.sync()
        self.app.manager.sync_mileage.assert_called_once_with(expected_preview='mileage-token')


if __name__ == '__main__':
    unittest.main()
