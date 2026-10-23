import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import toolbox_config as config


class LocalConfigTests(unittest.TestCase):
    def test_first_machine_without_config_preserves_legacy_default(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'CONFIG_PATH',Path(folder)/'none.json'),patch.dict(os.environ,{},clear=True):
            self.assertEqual(config.game_directory(),config.LEGACY_GAME_DIRECTORY)

    def test_configured_directory_round_trip_and_environment_override(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'CONFIG_PATH',Path(folder)/'config'/'toolbox.local.json'),patch.dict(os.environ,{},clear=True):
            game=Path(folder)/'game';(game/'map').mkdir(parents=True)
            config.save_game_directory(game)
            self.assertEqual(config.game_directory(),game.resolve())
            with patch.dict(os.environ,{'MIR_GAME_DIR':str(Path(folder)/'other')}):
                self.assertEqual(config.game_directory(),(Path(folder)/'other').resolve())

    def test_invalid_directory_is_not_saved(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'CONFIG_PATH',Path(folder)/'toolbox.local.json'):
            with self.assertRaises(ValueError):config.save_game_directory(folder)
            self.assertFalse(config.CONFIG_PATH.exists())


if __name__=='__main__':unittest.main()
