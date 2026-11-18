import unittest
from unittest.mock import Mock, patch

import pygame

from engine.engine import Engine


class EngineAssetTests(unittest.TestCase):
    def test_intro_logo_uses_engine_loader(self):
        engine = Engine.__new__(Engine)
        engine.assets = Mock()

        with patch("engine.engine.loader.load_image", side_effect=pygame.error("missing")) as load_image:
            engine._play_intro()

        load_image.assert_called_once_with("logo.png")
        engine.assets.load_image.assert_not_called()


if __name__ == "__main__":
    unittest.main()
