import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from profile_core import Manager, ProfileError


class GameDetectionTests(unittest.TestCase):
    def check(self, names):
        output='\n'.join(f'"{name}","123","Console","1","123 K"' for name in names)
        result=subprocess.CompletedProcess([],0,stdout=output,stderr='')
        with patch('profile_core.subprocess.run',return_value=result):
            return Manager(Path(__file__).parent).game_running()

    def test_manager_is_not_the_game(self):
        self.assertFalse(self.check(['OverTheHill.ProfileManager.exe','pythonw.exe']))

    def test_actual_game_is_detected(self):
        self.assertTrue(self.check(['OverTheHill.ProfileManager.exe','over the hill.exe']))

    def test_similarly_named_processes_are_not_the_game(self):
        self.assertFalse(self.check(['OverTheHill.Backup.exe','oth.exe.helper.exe','UnityCrashHandler64.exe']))

    def test_empty_process_list_is_closed(self):
        self.assertFalse(self.check([]))
