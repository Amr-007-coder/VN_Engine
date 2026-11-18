"""Built-in engine UI strings with project catalog overrides."""

UI_LABEL_KEYS = {
    "New Game": "menu.new_game", "Continue": "menu.continue", "Load": "menu.load",
    "Save": "menu.save", "Load Game": "menu.load_game", "Save Game": "menu.save_game",
    "Settings": "menu.settings", "Credits": "menu.credits",
    "Extras": "menu.extras", "Quit": "menu.quit", "Resume": "menu.resume",
    "Back": "common.back", "Main Menu": "menu.main_menu", "Paused": "menu.paused",
    "CG Gallery": "extras.cg_gallery", "Music Room": "extras.music_room",
    "Achievements": "extras.achievements", "Routes": "extras.routes", "Mods": "extras.mods",
    "Language": "settings.language", "Text Speed": "settings.type_speed", "Auto Wait": "settings.auto_wait",
    "Type Speed": "settings.type_speed",
    "Music Volume": "settings.music_volume", "Sound Volume": "settings.sound_volume",
    "Fullscreen": "settings.fullscreen", "UI Size": "settings.ui_size",
    "Reduced Motion": "settings.reduced_motion", "High Contrast": "settings.high_contrast",
    "Animated Text": "settings.animated_text", "Voice": "settings.voice",
    "Speech Announcements": "settings.speech", "On": "common.on", "Off": "common.off",
    "Sound Effects Volume": "settings.sound_volume", "Dialogue Text Size": "settings.dialogue_size",
    "Speaker Name Size": "settings.speaker_size", "High Contrast Text": "settings.high_contrast",
    "Voice Playback": "settings.voice", "Dialogue Subtitles": "settings.subtitles",
    "Animated Text Reveal": "settings.animated_text", "Touch Advance Area": "settings.touch_area",
    "Display Mode": "settings.display_mode", "Q. Save": "controls.quick_save",
    "Q. Load": "controls.quick_load", "History": "controls.history", "Auto": "controls.auto",
    "Mute": "controls.mute", "Dialogue History": "controls.history_title",
    "Windowed": "settings.windowed", "Whole Screen": "settings.whole_screen",
    "Textbox Only": "settings.textbox_only", "Are you sure?": "common.confirm_title",
    "Yes": "common.yes", "Cancel": "common.cancel", "Delete": "common.delete",
    "Cancel Copy": "slots.cancel_copy", "Copy Here": "slots.copy_here",
    "Recovered backup": "slots.recovered_backup",
    "Enable": "mods.enable", "Disable": "mods.disable", "Remove": "mods.remove",
    "Install Package...": "mods.install", "Installed Mods": "mods.installed", "Mod Details": "mods.details",
    "Enabled": "mods.enabled", "Disabled": "mods.disabled",
    "No packages installed": "mods.empty", "Source": "mods.source", "State": "mods.state",
    "Assets": "mods.assets", "Asset": "mods.asset", "Conflict": "mods.conflict",
    "uses": "mods.winner", "Load issue": "mods.load_issue",
    "No package errors or asset conflicts.": "mods.clean", "Conflicts": "mods.conflicts",
    "Import": "slots.import", "Export": "slots.export", "Copy": "slots.copy",
    "Nothing unlocked yet": "extras.empty", "Completed": "routes.completed",
    "Choices": "speech.choices", "Choices.": "speech.choices",
    "Speech announcements enabled": "speech.enabled",
    "Speech output is unavailable. Install pyttsx3 or enable a system speech service.": "speech.unavailable",
    "Install .vnmod files here. Mod changes take effect after restarting the game.": "mods.install_note",
    "Mod state saved. Restart the game for asset changes to take effect.": "mods.restart_note",
}

BUILTIN = {
    "en": {},
    "de": {
        "menu.new_game": "Neues Spiel", "menu.continue": "Fortsetzen", "menu.load": "Laden",
        "menu.save": "Speichern", "menu.load_game": "Spiel laden", "menu.save_game": "Spiel speichern",
        "menu.settings": "Einstellungen", "menu.credits": "Mitwirkende", "menu.main_menu": "Hauptmenü",
        "menu.paused": "Pausiert",
        "menu.extras": "Extras", "menu.quit": "Beenden", "menu.resume": "Weiter",
        "common.back": "Zurück", "extras.cg_gallery": "CG-Galerie", "extras.music_room": "Musikzimmer",
        "extras.achievements": "Erfolge", "extras.routes": "Routen", "extras.mods": "Mods",
        "settings.language": "Sprache", "settings.type_speed": "Texttempo", "settings.auto_wait": "Wartezeit",
        "settings.music_volume": "Musiklautstärke", "settings.sound_volume": "Effektlautstärke",
        "settings.fullscreen": "Vollbild", "settings.ui_size": "Oberflächengröße",
        "settings.reduced_motion": "Weniger Bewegung", "settings.high_contrast": "Hoher Kontrast",
        "settings.animated_text": "Animierter Text", "settings.voice": "Stimme",
        "settings.speech": "Sprachausgabe", "common.on": "An", "common.off": "Aus",
        "settings.dialogue_size": "Dialogtextgröße", "settings.speaker_size": "Namenstextgröße",
        "settings.subtitles": "Dialoguntertitel", "settings.touch_area": "Touch-Bereich",
        "settings.display_mode": "Anzeigemodus", "controls.quick_save": "Q. Speichern",
        "controls.quick_load": "Q. Laden", "controls.history": "Verlauf",
        "controls.auto": "Auto", "controls.mute": "Stumm", "controls.history_title": "Dialogverlauf",
        "settings.windowed": "Fenster", "settings.whole_screen": "Ganzer Bildschirm",
        "settings.textbox_only": "Nur Textfeld", "common.confirm_title": "Bist du sicher?",
        "common.yes": "Ja", "common.cancel": "Abbrechen", "common.delete": "Löschen",
        "mods.enable": "Aktivieren", "mods.disable": "Deaktivieren", "mods.remove": "Entfernen",
        "mods.install": "Paket installieren...", "mods.installed": "Installierte Mods", "mods.details": "Mod-Details",
        "mods.enabled": "Aktiviert", "mods.disabled": "Deaktiviert",
        "mods.empty": "Keine Pakete installiert", "mods.source": "Quelle", "mods.state": "Status",
        "mods.assets": "Ressourcen", "mods.asset": "Datei", "mods.conflict": "Konflikt",
        "mods.winner": "verwendet", "mods.load_issue": "Ladeproblem",
        "mods.clean": "Keine Paketfehler oder Ressourcenkonflikte.", "mods.conflicts": "Konflikte",
        "slots.import": "Importieren", "slots.export": "Exportieren", "slots.copy": "Kopieren",
        "slots.cancel_copy": "Kopieren abbrechen", "slots.copy_here": "Hierher kopieren",
        "slots.recovered_backup": "Sicherung wiederhergestellt",
        "extras.empty": "Noch nichts freigeschaltet", "routes.completed": "Abgeschlossen",
        "speech.choices": "Auswahlmöglichkeiten", "speech.enabled": "Sprachausgabe aktiviert",
        "speech.unavailable": "Sprachausgabe ist nicht verfügbar. Installiere pyttsx3 oder aktiviere einen System-Sprachdienst.",
        "mods.install_note": "Installiere .vnmod-Dateien hier. Änderungen werden nach einem Neustart wirksam.",
        "mods.restart_note": "Mod-Status gespeichert. Starte das Spiel neu, damit die Änderungen wirksam werden.",
        "message.unknown_menu_action": "Unbekannte Menüaktion: {action}",
        "message.no_continue_save": "Es gibt keinen Spielstand zum Fortsetzen.",
        "message.no_active_game": "Es gibt kein aktives Spiel zum Speichern.",
        "message.save_success": "Spielstand in Slot {slot} gespeichert.",
        "message.save_error": "Speichern fehlgeschlagen: {error}",
        "message.slot_empty": "Slot {slot} ist leer.",
        "message.different_story": "Dieser Spielstand gehört zu einer anderen Geschichte.",
        "message.load_error": "Laden fehlgeschlagen: {error}",
        "message.delete_success": "Spielstand in Slot {slot} gelöscht.",
        "message.delete_empty": "Slot {slot} ist bereits leer.",
        "message.delete_error": "Löschen fehlgeschlagen: {error}",
        "message.copy_success": "Spielstand aus Slot {source} nach Slot {slot} kopiert.",
        "message.copy_error": "Spielstand konnte nicht kopiert werden: {error}",
    },
}


def translate_ui(locale: str, key: str, fallback: str, table: dict | None = None) -> str:
    if isinstance(table, dict):
        value = table.get(key, table.get(f"ui.{key}"))
        if isinstance(value, str) and value:
            return value
    language = (locale or "en").split("-", 1)[0].casefold()
    return BUILTIN.get(language, {}).get(key, fallback)


def translate_label(locale: str, text: str, table: dict | None = None) -> str:
    key = UI_LABEL_KEYS.get(text)
    return translate_ui(locale, key, text, table) if key else text
