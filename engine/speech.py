"""Optional asynchronous text-to-speech announcements."""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading


class SpeechAnnouncer:
    """Uses pyttsx3 when installed; speaking never blocks the game loop."""

    def __init__(self):
        self._queue = queue.Queue()
        self.available = None
        self.error = ""
        self._thread = threading.Thread(target=self._run, name="vn-speech", daemon=True)
        self._thread.start()

    def speak(self, text: str, locale: str | None = None):
        if isinstance(text, str) and text.strip():
            self._queue.put((text, locale))

    def stop(self):
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(None)

    def _run(self):
        engine = None
        try:
            import pyttsx3

            engine = pyttsx3.init()
        except Exception as error:  # backend availability differs by operating system
            self.error = str(error)
        native = self._native_backend()
        self.available = engine is not None or native is not None
        if not self.available:
            return
        while True:
            item = self._queue.get()
            if item is None:
                return
            text, locale = item
            try:
                if engine is not None and locale:
                    language = locale.replace("-", "_").casefold()
                    voice = next((
                        voice for voice in engine.getProperty("voices")
                        if any(language in str(value).casefold() for value in getattr(voice, "languages", []))
                    ), None)
                    if voice is not None:
                        engine.setProperty("voice", voice.id)
                if engine is not None:
                    engine.say(text)
                    engine.runAndWait()
                else:
                    self._speak_native(native, text, locale)
            except Exception as error:
                self.error = str(error)

    @staticmethod
    def _native_backend():
        if sys.platform == "win32":
            executable = shutil.which("powershell.exe") or shutil.which("powershell")
            return ("powershell", executable) if executable else None
        if sys.platform == "darwin":
            executable = shutil.which("say")
            return ("say", executable) if executable else None
        for name in ("spd-say", "espeak-ng", "espeak"):
            executable = shutil.which(name)
            if executable:
                return (name, executable)
        return None

    @staticmethod
    def _speak_native(backend, text, locale):
        name, executable = backend
        if name == "powershell":
            command = (
                "$text=[Console]::In.ReadToEnd(); "
                "Add-Type -AssemblyName System.Speech; "
                "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$speaker.Speak($text)"
            )
            subprocess.run(
                [executable, "-NoProfile", "-NonInteractive", "-Command", command],
                input=text, text=True, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=90, check=False,
            )
        elif name == "say":
            subprocess.run([executable, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
        elif name == "spd-say":
            subprocess.run([executable, text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
        else:
            arguments = [executable]
            if locale:
                arguments.extend(["-v", locale])
            arguments.append(text)
            subprocess.run(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90, check=False)
