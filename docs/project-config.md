# Project configuration reference

`data/project.json` selects the story, names the game, sets the window and save-slot count, and configures menus, credits, intro cards, and theme. It must be valid JSON: use double quotes around keys and strings, and do not add comments or a trailing comma.

The project configuration is optional. If it is missing, the engine loads its built-in defaults and looks for `data/story.yaml`. When a config value is omitted, its built-in default is used. Nested objects merge with defaults; arrays such as menu `items` replace the default array completely.

The starter-project template includes the full default theme, including the menu-screen, textbox, choice-button, and pause-button settings described below. VN_Editor shows this template for a missing or empty `data/project.json` and marks it unsaved; the file is written only when you save. A non-empty project file is loaded as written and is not replaced or filled with template keys. Its omitted settings still use engine defaults at runtime.

## Project folder and path rules

The project root is the folder containing `assets/` and `data/`. If `Documents/VN Engine Projects/My Visual Novel` does not exist when VN_Editor starts without another project selected, the editor installs the starter project from its GitHub Release archive there. It leaves an existing folder and its `data/project.json` untouched. You can also open any other project folder from VN_Editor.

Runtime templates are downloaded from the public GitHub Releases on demand and cached in the user's local cache. They are editor runtime files, not part of your project's `assets/` or `data/`.

```text
My Visual Novel/
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
| `theme` | Built-in theme | Colors, fonts, textbox, menus, button art, pause icon, and menu sounds. |

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

Choose **Android** in the editor's **Export Game** dialog to create a new project-specific Web archive, then build it as a Capacitor debug APK. The editor offers published runtime releases and recommends the release matching its own version. It downloads that release's Web template and temporarily fetches the matching engine source from GitHub; it does not reuse a previously exported `web.zip` or require Python or Pygbag to be installed. Node.js/npm, a Java JDK, the Android SDK, and an internet connection are required. The temporary Web archive, downloaded source, and Capacitor project are removed after export; the output is just the `.apk`. The standalone engine CLI uses the latest published runtime release by default.

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

The engine displays an opening sequence before the main menu: the built-in logo, a creator credit, then an optional content notice. Use `intro` to change its text and replace/omit the optional images:

| Key | Default | Description |
| --- | --- | --- |
| `creator` | `Marpp` | Name shown on the credit card. Required as a string after defaults are merged. |
| `game_version` | `null` | Optional version printed on the credit card. |
| `warning_message` | Empty string | Text printed on the notice card. Use `\n` in JSON for a line break. |
| `credit_image` | `null` | Optional image shown with the creator credit. |
| `warning_image` | `content_warning.png` | Image on the notice card. Set to `null` to omit it. |
| `headphones_image` | `headphones.png` | Additional image below the notice. Set to `null` to omit it. |

The optional intro image values resolve from project `assets/` first and engine assets second. The `logo.png` and `intro.wav` splash assets are provided by the engine. The splash logo is fixed to the engine asset and cannot be hidden or replaced by a project image.

The notice card is skipped when `warning_message` is empty and both `warning_image` and `headphones_image` are `null`.

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

The `theme` object is merged over a full set of engine defaults. The starter `project.json` spells these defaults out so every available setting is visible and editable; existing project files are not rewritten to add them. You can still omit values in a hand-edited project. Theme asset paths resolve from project `assets/` first, then engine assets. Colors are arrays of channel values from `0` to `255`; use `[R, G, B]`, or `[R, G, B, A]` for color alpha. The textbox also has an overall opacity setting from `0.0` to `1.0`.

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

The textbox defaults to a 96%-width panel aligned with the bottom edge of the window. Set its `x`, `bottom`, `width`, and `height` as fractions of the window dimensions from `0.0` to `1.0`. Put image files in `assets/images/` and set the path relative to `assets/`. The image is scaled to fill the textbox; transparent parts show the configured color underneath. `opacity` multiplies the opacity of the entire panel, including its image. With no image, the color alone is used. `color: null` uses `theme.colors.panel` (default `[0, 0, 0, 128]`).

```json
"theme": {
  "textbox": {
    "background": "images/dialogue-frame.png",
    "color": [18, 15, 28, 220],
    "x": 0.02,
    "bottom": 0.0,
    "width": 0.96,
    "height": 0.24,
    "opacity": 0.8
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

All geometry values are window fractions; `x + width` and `bottom + height` must each be at most `1.0`. Width and height must be greater than zero. A project image that cannot be found is an error; use the editor’s asset suggestions or its live diagnostics to find the correct path.

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

### Per-screen menus, grids, and button images

Menu screens can have independent backgrounds, row alignment and spacing, button sizes, button images, and grid layouts. The supported screen names are `main`, `pause`, `settings`, and `slots`; each applies only to that screen. Credits remains a scrolling list but supports its own button images and background. A screen-specific background overrides the shared `theme.menu.background`.

Normal and hovered button images are optional PNGs. If only one is provided, it is used for both states. The label and any detail text are drawn over the image. With no button images, the engine draws its normal colored rows.

```json
"menu": {
  "screens": {
    "main": {
      "background": "images/title-screen.png",
      "buttons": {
        "normal": "images/title-button.png",
        "hovered": "images/title-button-hover.png"
      },
      "grid": [
        [0, 1, 0],
        [2, 0, 3]
      ],
      "button_width": 260,
      "button_height": 72
    },
    "pause": {
      "buttons": {
        "normal": "images/pause-button.png"
      }
    },
    "slots": {
      "buttons": {
        "normal": "images/slot-button.png",
        "hovered": "images/slot-button-hover.png"
      }
    }
  }
}
```

In a grid, each positive number refers to that menu's item in one-based order. Use `0` or `null` for an empty cell. Every item index must appear exactly once; repeated or missing indexes are invalid. Rows may have different lengths: the window is divided by the number of grid rows and by the longest row, with short-row cells left empty. Buttons are centered in their cells. `button_width` and `button_height` are design pixels scaled by UI Size; omitted values default to `240` × `72` in a grid. The same size and spacing settings can also override the normal vertical rows for an individual screen. Grids are supported on the main, pause, settings, and save/load screens; Credits remains scrollable.

The `main` grid above assumes `menus.main.items` contains exactly three items. Change the grid numbers to match the item list. A grid for Settings must account for the automatically added UI Size item if the configured list does not already contain it. Save/load grids must contain one index for each save slot.

Story-choice buttons use their own image pair and dimensions:

```json
"choice_buttons": {
  "normal": "images/choice.png",
  "hovered": "images/choice-hover.png",
  "width": 900,
  "height": 56,
  "gap": 12
}
```

The pause icon in the top-left corner can also use a project PNG. Its default image is the engine's built-in `pause.png`:

```json
"pause_button": {
  "image": "images/pause.png",
  "size": 78,
  "margin": 16
}
```

Choice-button and pause-button dimensions are design pixels and scale with UI Size. If only one choice image is supplied, it is used for both normal and hovered states.

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
