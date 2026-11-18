"""Translation catalog extraction, import, and layout preview helpers."""

from __future__ import annotations

import json
from pathlib import Path
import re


RTL_LOCALES = {"ar", "fa", "he", "ur", "ps", "sd", "ug", "yi"}


def is_rtl_locale(locale: str) -> bool:
    return isinstance(locale, str) and locale.split("-", 1)[0].casefold() in RTL_LOCALES


def _source_value(value, default_locale):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        source = value.get(default_locale)
        return source if isinstance(source, str) else ""
    return ""


def story_strings(story: dict) -> dict[str, str]:
    localization = story.get("localization", {}) if isinstance(story, dict) else {}
    default_locale = localization.get("default_locale", "en") if isinstance(localization, dict) else "en"
    dialogues = story.get("dialogues", {}) if isinstance(story, dict) else {}
    result = {}
    for dialogue_id, dialogue in dialogues.items():
        if not isinstance(dialogue, dict):
            continue
        for field in ("text", "speaker_name"):
            value = dialogue.get(field)
            if value is None and field == "speaker_name":
                continue
            result[f"dialogues.{dialogue_id}.{field}"] = _source_value(value, default_locale)
        options = dialogue.get("options", [])
        if isinstance(options, list):
            for index, option in enumerate(options):
                if isinstance(option, dict):
                    result[f"dialogues.{dialogue_id}.options.{index}.label"] = _source_value(
                        option.get("label"), default_locale
                    )
        actions = dialogue.get("actions", [])
        if isinstance(actions, list):
            for index, action in enumerate(actions):
                if not isinstance(action, dict):
                    continue
                for field in ("label", "title", "description", "prompt"):
                    if field in action:
                        result[f"dialogues.{dialogue_id}.actions.{index}.{field}"] = _source_value(
                            action[field], default_locale
                        )
    return result


def translation_template(story: dict, locale: str, ui_sources: dict[str, str] | None = None) -> dict:
    sources = story_strings(story)
    return {
        "locale": locale,
        "source_locale": story.get("localization", {}).get("default_locale", "en"),
        "strings": {key: "" for key in sources},
        "sources": sources,
        "ui": {key: "" for key in (ui_sources or {})},
        "ui_sources": dict(ui_sources or {}),
    }


def normalize_translation_catalog(value: dict, expected_locale: str | None = None) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Translation catalog must be a JSON object.")
    locale = value.get("locale")
    if not isinstance(locale, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale):
        raise ValueError("Translation catalog needs a valid BCP-47 'locale' field.")
    if expected_locale and locale.casefold() != expected_locale.casefold():
        raise ValueError(f"Catalog locale {locale!r} does not match expected locale {expected_locale!r}.")
    strings = value.get("strings", {})
    ui = value.get("ui", {})
    if not isinstance(strings, dict) or not isinstance(ui, dict):
        raise ValueError("Catalog 'strings' and 'ui' fields must be objects.")
    normalized_sections = []
    for section in (strings, ui):
        normalized = {}
        for key, translation in section.items():
            if not isinstance(key, str) or not key:
                raise ValueError("Translation keys must be non-empty strings.")
            if isinstance(translation, dict):
                translation = translation.get("translation", "")
            if not isinstance(translation, str):
                raise ValueError(f"Translation for {key!r} must be a string.")
            normalized[key] = translation
        normalized_sections.append(normalized)
    return {
        "locale": locale,
        "strings": normalized_sections[0],
        "ui": normalized_sections[1],
        "direction": "rtl" if is_rtl_locale(locale) else "ltr",
    }


def catalog_report(story: dict, locale: str, catalog: dict | None = None) -> list[dict]:
    catalog = catalog or {}
    strings = catalog.get("strings", {}) if isinstance(catalog, dict) else {}
    sources = story_strings(story)
    rows = []
    for key, source in sources.items():
        translated = strings.get(key, "") if isinstance(strings, dict) else ""
        if isinstance(translated, dict):
            translated = translated.get("translation", "")
        translated = translated if isinstance(translated, str) else ""
        rows.append({
            "key": key,
            "source": source,
            "translation": translated,
            "missing": not translated.strip(),
            "source_chars": len(source),
            "translation_chars": len(translated),
            "expansion": round(len(translated) / max(1, len(source)), 2),
            "direction": "rtl" if is_rtl_locale(locale) else "ltr",
        })
    return rows


def load_catalog(path: Path, expected_locale: str | None = None) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read translation catalog {path}: {error}") from error
    return normalize_translation_catalog(raw, expected_locale)


def write_catalog(path: Path, value: dict, expected_locale: str | None = None) -> Path:
    normalized = normalize_translation_catalog(value, expected_locale)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
