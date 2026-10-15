from pathlib import Path
import unittest
from unittest.mock import patch

from wq_panel.__main__ import main


class LauncherTests(unittest.TestCase):
    def test_shortcut_pins_the_installed_config_without_launching_gui(self):
        expected = Path("installed-private") / "deployment.json"
        with patch("wq_panel.__main__.run") as run:
            main(["--access-config", str(expected)])
        run.assert_called_once_with(config_path=expected)

    def test_legacy_no_arguments_still_uses_automatic_discovery(self):
        with patch("wq_panel.__main__.run") as run:
            main([])
        run.assert_called_once_with(config_path=None)
