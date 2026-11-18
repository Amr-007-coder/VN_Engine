import json
import unittest
from unittest.mock import patch

from tools.release import PLATFORMS, _read_tag_options


class ReleaseOptionTests(unittest.TestCase):
    def test_every_release_builds_all_templates_and_editors(self):
        with patch("tools.release._git") as git:
            git.return_value.returncode = 0
            options = _read_tag_options("v1.2.3")

        matrix = json.loads(options["matrix"])
        self.assertEqual([item["platform"] for item in matrix["include"]], list(PLATFORMS))
        self.assertEqual(json.loads(options["platforms"]), list(PLATFORMS))
        self.assertEqual(options["build_editor"], "true")


if __name__ == "__main__":
    unittest.main()
