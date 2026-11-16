# Project configuration reference

`data/project.json` selects the story, names the game, sets the window and save-slot count, and configures menus, credits, intro cards, and theme. It must be valid JSON: use double quotes around keys and strings, and do not add comments or a trailing comma.

The project configuration is optional. If it is missing, the engine loads its built-in defaults and looks for `data/story.yaml`. When a config value is omitted, its built-in default is used. Nested objects merge with defaults; arrays such as menu `items` replace the default array completely.

## Project folder and path rules

The project root is the folder containing `assets/` and `data/`. In the downloadable editor package, the starter project is beside the platform-specific editor app and its `templates/` folder. You can also open any other project folder from VN_Editor.

The editor package includes `templates/template-web.zip`. Keep it with the editor: it supplies the Pygbag runtime for Web and Android exports. It is an editor runtime template, not part of your project’s `assets/` or `data/`.

```text
MyVisualNovel/
  VN_Editor.exe                 # Windows; Linux uses VN_Editor, macOS uses VN_Editor.app/
  templates/
    template-windows.zip
    template-linux.zip
    template-macos.zip
    template-web.zip              # Editor package runtime for Web and Android exports
  assets/
  data/
    project.json
    story.yaml
```

`paths.data` and `paths.assets` are resolved relative to the project root unless they are absolute paths. `story` is a filename or relative path inside the configured data folder. For example, with `"data": "data"` and `"story": "chapter-one.yaml"`, the story file is `data/chapter-one.yaml`. `--story alternate.yaml` overrides that filename for a single run and is also resolved from the configured data folder.

`paths.user_data` is resolved relative to the user-data root described in [User data, settings, and saves](#user-data-settings-and-saves). An absolute path can be used to choose a specific writable location.

For temporary runs such as the editor's **Test Play**, the engine honors the `VN_ENGINE_USER_DATA_DIR` environment variable as an override. The editor sets it to a temporary folder and removes that folder when the test game closes.

## A practical `project.json`

This example changes the project name, window, credits, menu labels, intro text, and colors. Unspecified pause-menu items, settings items, slot settings, and theme values keep their defaults.

```json
{
  "name": "Moonlight at Noon",
  "story": "story.yaml",
  "icon": null,
  "android": {
    "app_name": "VN Engine",
    "app_id": "com.example.vnengine",
    "orientation": "landscape"
  },
  "save_slots": 8,
  "paths": {
    "data": "data",
    "assets": "assets",
    "user_data": "user_data"
  },
  "window": {
    "width": 1280,
    "height": 720,
    "caption": "Moonlight at Noon"
  },
  "intro": {
    "creator": "Your Name",
    "game_version": "1.0",
    "warning_message": "This story contains flashing lights.\nTake breaks when you need them.",
    "credit_image": null,
    "warning_image": "content_warning.png",
    "headphones_image": "headphones.png"
  },
  "credits": [
    "Story and art: Your Name",
    { "label": "Music: Composer Name", "url": "https://example.com" }
  ],
  "menus": {
    "main": {
      "title": "Moonlight at Noon",
      "items": [
        { "label": "Start", "action": "new_game" },
        { "label": "Continue", "action": "continue_game" },
        { "label": "Load", "action": "open_load_slots" },
        { "label": "Options", "action": "open_settings" },
        { "label": "Credits", "action": "open_credits" },
        { "label": "Quit", "action": "quit" }
      ]
    },
    "pause": { "title": "Paused" },
    "settings": { "title": "Options" }
  },
  "theme": {
    "colors": {
      "background": [18, 22, 38],
      "text": [242, 237, 222],
      "accent": [235, 126, 151],
      "panel": [8, 12, 25, 220],
      "normal": [25, 31, 54],
      "hover": [80, 47, 74],
      "selected": [45, 78, 75],
      "border": [120, 101, 126]
    },
    "game_fonts": {
      "text": "standard.ttf",
      "name": "standard.ttf",
      "button": "standard.ttf"
    },
    "fonts": {
      "menu": "Joystix.ttf",
      "title": "VCR_OSD_Mono.ttf",
      "item_size": 20,
      "detail_size": 16,
      "title_size": 30
    },
    "menu": {
      "layout": "centered",
      "background": "images/menu-background.jpg",
      "width": 860,
      "row_height": 56,
      "row_gap": 9,
      "title_y": 112,
      "top": 190,
      "border_radius": 8
    },
    "sounds": {
      "hover": "sounds/hover_button.wav",
      "click": "sounds/click_button.wav",
      "cancel": "sounds/click_button.wav",
      "load": "sounds/click_button.wav"
    }
  }
}
```

If you copy this example, add `assets/images/menu-background.jpg` or set `theme.menu.background` to `null`. A missing theme image is simply omitted. The built-in font names in the example are available even when those font files are not in the project.

## Top-level fields

| Field | Default | Description |
| --- | --- | --- |
| `name` | `Visual Novel` | Project/game display name. Used for the built game filename and the per-project user-data folder. |
| `story` | `story.yaml` | YAML story file inside `paths.data`. |
| `icon` | `null` | Optional PNG path inside project `assets/`, used for the game window and native/browser app icon where supported. |
| `android` | See [Android export](#android-export) | Android app name, application ID, and screen orientation. |
| `save_slots` | `5` | Number of save/load slots. Must be a positive integer. |
| `paths` | See [paths](#paths) | Project data, asset, and user-data locations. |
| `window` | `1920` × `1200`, caption `VN Engine` | Initial window size and operating-system window caption. Fullscreen can also be toggled in Settings. |
| `intro` | See [intro cards](#intro-cards) | Creator/version text and optional credit/warning card images. |
| `credits` | `[]` | Additional credits shown in the Credits menu. |
| `messages` | Built-in messages | Text for save/load/status messages; see [messages](#messages). |
| `menus` | Built-in menus | Main, pause, settings, and save-slot menu titles/items. |
| `theme` | Built-in theme | Colors, fonts, dialogue textbox image/color, menu layout/images, slot layout, and menu sounds. |

## Paths

```json
"paths": {
  "data": "data",
  "assets": "assets",
  "user_data": "user_data"
}
```

| Key | Default | Use |
| --- | --- | --- |
| `data` | `data` | Folder containing `project.json` and the configured story file. Relative paths start at the project root. |
| `assets` | `assets` | Folder containing project images, audio, fonts, and character art. Relative paths start at the project root. |
| `user_data` | `user_data` | Writable folder for settings and saves, relative to the user-data root. Can be absolute. |

Launch VN_Editor and open the folder containing `assets/` and `data/`. The editor's **Test Play** and **Export Game** commands package those configured folders automatically. When running a separate engine executable directly, set its working directory to the project root so it can locate the project files.

## Application icon

Set the optional top-level `icon` field to a PNG in the project's assets folder. Paths are relative to `assets/`; for example, `"icon": "images/game-icon.png"`. The default `null` uses the engine's built-in `logo.png` for the game window.

The configured PNG is used as the Windows executable icon and macOS app icon in desktop exports and direct builds, as well as the browser tab favicon and Android launcher icon. Linux executables do not have an embedded file icon, so the PNG is used for the game's window icon. To export a Windows game with a project-specific executable icon, run the editor on Windows. The opening splash always keeps the engine's built-in logo. When `icon` is `null`, Android uses the engine's built-in `logo.png`.

The default Windows game executable uses `engine/assets/images/logo.ico`; the VN_Editor executable uses `engine/assets/images/editor_logo.ico`. macOS app icons are generated from the matching PNG assets.

## Android export

Choose **Android** in the editor's **Export Game** dialog to create a new project-specific Web archive from the bundled `template-web.zip`, then build it as a Capacitor debug APK. The editor does not reuse a previously exported `web.zip` and does not require Python or Pygbag to be installed. The Pygbag runtime is the version bundled with the editor package; Node.js/npm, a Java JDK, and the Android SDK are still required, and Android build dependencies are downloaded from the internet. The temporary Web archive and Capacitor project are removed after export; the output is just the `.apk`. The standalone engine CLI also uses `template-web.zip` by default.

```json
"android": {
  "app_name": "VN Engine",
  "app_id": "com.example.vnengine",
  "orientation": "landscape"
}
```

| Key | Default | Description |
| --- | --- | --- |
| `app_name` | `VN Engine` | Name shown for the installed Android app. |
| `app_id` | `com.example.vnengine` | Lowercase reverse-DNS application ID. Choose an ID you control before distributing the app. |
| `orientation` | `landscape` | Lock the app to `landscape` or `portrait`. |

Android export requires Node.js/npm, a Java JDK, and the Android SDK (installable through Android Studio). The Android app uses the project's top-level `icon` field for its launcher icon, falling back to the engine logo.

Android APKs run immersive full-screen and fit the game display to the device viewport while preserving the aspect ratio from the configured project window dimensions. A swipe from a screen edge can temporarily reveal Android's system bars. The app requests that Android keep the display awake while the game is active.

## Intro cards

The engine displays an opening sequence before the main menu: the built-in logo, a creator credit, then a content notice. Use `intro` to change its text and replace/omit the optional images:

| Key | Default | Description |
| --- | --- | --- |
| `creator` | `Marpp` | Name shown on the credit card. Required as a string after defaults are merged. |
| `game_version` | `null` | Optional version printed on the credit card. |
| `warning_message` | Empty string | Text printed on the notice card. Use `\n` in JSON for a line break. |
| `credit_image` | `null` | Optional image shown with the creator credit. |
| `warning_image` | `content_warning.png` | Image on the notice card. Set to `null` to omit it. |
| `headphones_image` | `headphones.png` | Additional image below the notice. Set to `null` to omit it. |

The optional intro image values resolve from project `assets/` first and engine assets second. The `logo.png` and `intro.wav` splash assets are provided by the engine. The splash logo is fixed to the engine asset and cannot be hidden or replaced by a project image.

## Menus

The engine has a main menu, pause menu, settings menu, generated save/load slot screens, and a credits screen. Each normal menu contains a `title` and an ordered `items` list. An item has a visible `label` and an `action` ID. Change labels, remove items, or reorder the list; keep the action IDs supported by the engine.

### Built-in menu actions

| Action | Effect |
| --- | --- |
| `new_game` | Start the story at its `start` dialogue. |
| `continue_game` | Load the newer of the story autosave and most recently saved numbered slot, when available. |
| `open_load_slots` | Open the generated load-slot screen. |
| `open_save_slots` | Open the generated save-slot screen. |
| `open_settings` | Open the settings menu. |
| `open_credits` | Open project credits and the engine creator credit. |
| `quit` | Close the engine. |
| `resume` | Return from the pause menu to the current game. |
| `return_to_main_menu` | Leave the current game and show the main menu. |
| `back` | Return to the previous menu. |
| `adjust_setting` | Adjust a setting. Provide `setting` as `type_speed`, `music_volume`, `sfx_volume`, or `ui_scale`. |
| `toggle_setting` | Toggle a setting. Provide `setting: fullscreen`. |

The default main menu provides New Game, Continue, Load Game, Settings, Credits, and Quit. The default pause menu provides Resume, Save Game, Load Game, Settings, and Main Menu. You can replace their labels or item lists in `menus.main.items` and `menus.pause.items`.

Setting items display their current value. `Left`/`Right` changes the selected setting; clicking the left or right half of an `adjust_setting` row decreases or increases it. Type speed ranges from `0.25x` to `4x` in `0.25x` steps. Music and SFX volume range from `0%` to `100%` in `10%` steps. UI Size ranges from `80%` to `160%` in `10%` steps and scales the engine's dialogue, menus, choices, and other interface controls. The engine adds this setting automatically if a custom settings menu does not include it. Fullscreen toggles between windowed and fullscreen mode.

Slot rows are created by the engine according to `save_slots`; do not add them manually to `menus.main.items`. The `save_slot` and `load_slot` IDs are used internally for generated slot rows and require a slot number supplied by the engine. The slot screen has built-in Delete, Save/Load, and Back buttons.

### Save-slot labels

The `menus.slots` object controls slot screen titles and row text. Defaults are:

```json
"slots": {
  "title_save": "Save Game",
  "title_load": "Load Game",
  "labels": {
    "slot": "Slot {slot}",
    "saved": "Slot {slot}: {chapter}",
    "empty": "Empty",
    "corrupt": "Corrupted Save",
    "unknown_chapter": "Unknown Chapter",
    "unknown_time": "Unknown Time"
  },
  "delete": { "label": "Delete Selected Slot", "action": "delete_selected_slot" },
  "back": { "label": "Back", "action": "back" }
}
```

You may customize `title_save`, `title_load`, and labels. The `slot` label may use `{slot}`. The `saved` label may use `{slot}`, `{chapter}`, and `{dialogue}`. `empty`, `corrupt`, `unknown_chapter`, and `unknown_time` are plain strings. The `delete` and `back` objects are required by the current config schema; their `label` values do not change the captions on the slot screen’s built-in buttons.

## Credits

Credits can be plain strings or objects with a `label` and optional `url`:

```json
"credits": [
  "Writing: Your Name",
  { "label": "Music: Composer", "url": "https://example.com" }
]
```

Only `http://` and `https://` URLs are accepted. Selecting a linked entry opens it in the system browser. The engine automatically appends `Marpp: Creator of the VN Engine` to the list.

## Theme

The `theme` object is merged over a full set of engine defaults. You can set only the values you want to change. Theme asset paths resolve from project `assets/` first, then engine assets. Colors are arrays of channel values from `0` to `255`; use `[R, G, B]`, or `[R, G, B, A]` for the dialogue panel opacity. The editor’s default `project.json` includes `theme.textbox.background` and `theme.textbox.color`, both `null` initially.

### Colors

| Key | Used for |
| --- | --- |
| `background` | Game background when no background image is shown; fallback screen fill. |
| `text` | Dialogue and menu text. |
| `accent` | Speaker name and highlighted dialogue text. |
| `muted` | Defined as a default color but not currently used by the menu renderer. |
| `panel` | Dialogue textbox panel; can include alpha as a fourth value. |
| `normal` | Unselected menu rows. |
| `hover` | Selected menu row. |
| `selected` | Persistent selected slot row. |
| `border` | Menu-row border. |

### Dialogue textbox image and color

The textbox keeps its default size and position, but you can choose its panel color, add a panel image, or use both. Put image files in `assets/images/` and set the path relative to `assets/`. The image is scaled to fill the textbox; transparent parts show the configured color underneath. With no image, the color alone is used. `color: null` uses `theme.colors.panel` (default `[0, 0, 0, 128]`). An RGBA color controls its opacity.

```json
"theme": {
  "textbox": {
    "background": "images/dialogue-frame.png",
    "color": [18, 15, 28, 220]
  }
}
```

To use only a flat color, set `background` to `null` or omit it:

```json
"theme": {
  "textbox": {
    "background": null,
    "color": [25, 35, 55, 210]
  }
}
```

Both fields are optional. A project image that cannot be found is an error; use the editor’s asset suggestions or its live diagnostics to find the correct path.

### Fonts

Use `game_fonts` for dialogue text, speaker names, and choice buttons:

```json
"game_fonts": {
  "text": "standard.ttf",
  "name": "Joystix.ttf",
  "button": "standard.ttf"
}
```

Use `fonts` for menus:

```json
"fonts": {
  "menu": "Joystix.ttf",
  "title": "VCR_OSD_Mono.ttf",
  "item_size": 20,
  "detail_size": 16,
  "title_size": 30
}
```

Font names can refer to files in `assets/fonts/` or the built-in font folder. The built-in files are `standard.ttf`, `Joystix.ttf`, `MS Gothic.ttf`, `PermanentMarker.ttf`, `rpg-maker-2k.ttf`, `Toriko.ttf`, and `VCR_OSD_Mono.ttf`. Missing or unreadable fonts fall back to a system font.

Dialogue text, speaker names, and choice-button text have base sizes of 24, 28, and 20 design pixels respectively. The player's UI Size setting scales these and other interface elements together. `game_fonts` changes their font files, not their base sizes. Menu title, item, and detail base sizes can be changed with the `fonts` values above and are also scaled by UI Size.

### Standard menu layout

```json
"menu": {
  "layout": "centered",
  "background": "images/menu.jpg",
  "width": 860,
  "x": null,
  "right_margin": 48,
  "row_height": 56,
  "row_gap": 9,
  "title_y": 112,
  "top": 190,
  "border_radius": 8
}
```

| Key | Default | Description |
| --- | --- | --- |
| `layout` | `centered` | Horizontal alignment: `centered`, `left`, or `right`. |
| `background` | `null` | Optional full-window image, scaled to fit the window. |
| `width` | `860` | Menu row width, limited to fit the window. |
| `x` | `null` | Optional left coordinate for `centered` or `left` layout. For `left`, the default is `48`. |
| `right_margin` | `48` | Right offset used by `right` layout. |
| `row_height` | `56` | Height of each row. |
| `row_gap` | `9` | Vertical space between rows. |
| `title_y` | `112` | Vertical center of the menu title. |
| `top` | `190` | Minimum starting y-coordinate for the menu rows. |
| `border_radius` | `8` | Corner radius for menu rows. |

If no theme values are configured, the engine uses a simple built-in renderer with system fonts and the default colors. Setting a `theme` enables the configurable renderer while keeping defaults for omitted theme values.

### Save-slot layout and artwork

By default, save slots use the standard menu rows. Set `theme.slot.layout` to `tape` to draw tape artwork at the left of each slot row. Put both images in the project `assets/` folder; paths are relative to that folder:

```json
"slot": {
  "layout": "tape",
  "normal": "images/tape.png",
  "hovered": "images/tape-selected.png",
  "width": 900,
  "row_height": 82,
  "row_gap": 8,
  "icon_width": 30,
  "icon_height": 72,
  "text_offset": 62
}
```

| Key | Default | Use |
| --- | --- | --- |
| `layout` | `list` | Use `list` for normal rows or `tape` for artwork rows. |
| `normal`, `hovered` | `null` | Image paths for the unselected and selected tape. Both are required for tape artwork. |
| `width`, `row_height`, `row_gap` | `900`, `82`, `8` | Row dimensions and spacing. |
| `icon_width`, `icon_height` | `30`, `72` | Size of the tape artwork area. |
| `text_offset` | `62` | Horizontal offset for the slot text. |

If either tape image is missing, the engine falls back to standard rows. The UI Size setting scales these dimensions.

### Menu sounds

`theme.sounds` accepts these keys: `hover`, `click`, `cancel`, and `load`. Each value is a sound asset path. Defaults use the built-in `sounds/hover_button.wav` and `sounds/click_button.wav`; missing menu sounds are silently skipped. Project files can override these paths.

## Messages

The `messages` object changes short status messages shown by save/load actions. Values may use only the placeholders shown below:

| Message key | Placeholders |
| --- | --- |
| `unknown_menu_action` | `{action}` |
| `no_continue_save` | None |
| `no_active_game` | None |
| `save_success` | `{slot}` |
| `save_error` | `{error}` |
| `slot_empty` | `{slot}` |
| `different_story` | None |
| `load_error` | `{error}` |
| `delete_success` | `{slot}` |
| `delete_empty` | `{slot}` |
| `delete_error` | `{error}` |

Override only the messages you want; unspecified messages keep their defaults:

```json
"messages": {
  "no_continue_save": "Start a new story first.",
  "save_success": "Saved in slot {slot}."
}
```

## User data, settings, and saves

The engine writes user settings and saves outside its bundled resources. On Windows, the default location is:

```text
%LOCALAPPDATA%\Visual Novel Engine\<folder-safe project name>\user_data\
```

Settings are stored in `settings.json`; numbered saves are stored under `saves/slot_1.json`, `saves/slot_2.json`, and so on. Story `autosave` actions overwrite `saves/autosave.json` and do not take a numbered slot. The engine appends a project-specific folder and the configured `paths.user_data` value to the platform root. On macOS, the root is `~/Library/Application Support/Visual Novel Engine/`; on Linux it is `$XDG_DATA_HOME/visual-novel-engine/`, or `~/.local/share/visual-novel-engine/` when `XDG_DATA_HOME` is unset. Set `paths.user_data` to an absolute path to choose a different location. Relative `paths.user_data` values are resolved from this platform-specific root.

The settings menu controls type speed (`0.25x`–`4x`), music/SFX volume (`0`–`1`), UI size (`0.8`–`1.6`), and fullscreen mode. Numbered saves and autosaves store the current dialogue, story variables, background, music, visible character portraits, and dialogue history. Increasing `save_slots` exposes additional slots; reducing it hides higher-numbered slots but does not automatically delete their files.
