import queue
import unittest
from unittest.mock import patch

from engine.speech import SpeechAnnouncer


class SpeechTests(unittest.TestCase):
    def test_speak_queues_only_nonempty_text_and_stop_adds_sentinel(self):
        announcer = SpeechAnnouncer.__new__(SpeechAnnouncer)
        announcer._queue = queue.Queue()

        announcer.speak("  ", "en")
        announcer.speak("Hello", "en-US")
        self.assertEqual(announcer._queue.get_nowait(), ("Hello", "en-US"))

        announcer._queue.put(("queued", "en"))
        announcer.stop()
        self.assertIsNone(announcer._queue.get_nowait())

    def test_native_backend_passes_text_as_an_argument(self):
        with patch("engine.speech.subprocess.run") as run:
            SpeechAnnouncer._speak_native(("say", "/usr/bin/say"), "Hello world", "en")

        command = run.call_args.args[0]
        self.assertEqual(command, ["/usr/bin/say", "Hello world"])
        self.assertEqual(run.call_args.kwargs["timeout"], 90)


if __name__ == "__main__":
    unittest.main()
