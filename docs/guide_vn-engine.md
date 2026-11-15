# VN Engine user guide

This guide takes you from the downloadable Windows package to a playable project and a shareable game. You can write the project with any text editor; the packaged engine does not require Python or a separate installation. Game exports are native desktop builds for the operating system running the matching engine runtime.

## 1. Extract and understand the project

Extract the complete ZIP to a writable folder. Keep the folders together and do not move or rename `VN_Engine/`.

```text
MyVisualNovel/                 # Project root
  engine.exe.lnk               # Shortcut to run this project
  editor.exe                    # Standalone editor; no Python install needed
  readme.md                     # Documentation
  guide_vn-engine.md
  project-config.md
  story-format.md
  assets/                      # Project art and audio
  data/
    project.json               # Project settings; optional in custom projects
    story.yaml                 # Starter story
  VN_Engine/
    engine.exe                # Engine executable
    ...                        # Supporting runtime files
```

The project root is the folder containing the shortcut, `assets/`, and `data/`. The shortcut sets this folder as the engine’s working directory. You can move the whole project folder, but keep its contents in this layout.

Edit `data/story.yaml`, `data/project.json`, and files under `assets/`. Treat `VN_Engine/` as read-only engine files. The engine looks for your story in the configured data folder and your assets in the configured assets folder. If `data/project.json` is missing, it uses the built-in project defaults and looks for `data/story.yaml`.

## 2. Write a story and add assets

Write dialogue IDs, text, choices, conditions, and story actions in `data/story.yaml`. The [story format reference](./story-format.md) explains the YAML syntax and provides examples.

Add your files under `assets/`. A typical project might look like this:

```text
assets/
  images/
    station.png
    menu-background.jpg
  sounds/
    door.wav
  music/
    station-theme.ogg
  fonts/
    my-dialogue-font.ttf
  characters/
    Aiko/
      Summer/Uniform/
        Smile.png
        Frown.png
```

Project assets take priority over built-in engine assets for normal asset lookups. The opening splash always uses the engine's own logo and cannot be replaced by `assets/images/logo.png`. For backgrounds, sound effects, music, and fonts, use the path relative to `assets/` (for example, `images/station.png` or `sounds/door.wav`). For character art, the folders and filenames define the names used by story actions. The [asset section](#5-assets-and-built-in-art) below lists built-in files.

Set the project title, window size, menus, credits, intro message, and visual theme in `data/project.json`. See [project configuration](./project-config.md).

The Windows package includes a standalone `editor.exe`. Double-click it, or launch `editor.exe` from the project folder; no Python, Pygame, Nuitka, or extra editor dependency needs to be installed. The editor opens the configured story, each YAML file named by `includes`, and `data/project.json` in separate tabs. It also shows the included Markdown guides in read-only tabs and offers YAML/JSON coloring, engine-specific suggestions, asset browsing, and live diagnostics. Its PowerShell pane starts in the project folder; `Ctrl+F` searches the selected tab, and `F5` saves all open project files and runs the engine validator. It saves ordinary YAML and JSON files, so you can switch to another editor at any time.

## 3. Validate and run

Open PowerShell in the project root. Validate the configured story before playing:

```powershell
.\VN_Engine\engine.exe --validate
```

Validation checks YAML structure, dialogue targets, declared variables, conditions, supported action names, and referenced assets. It reports the location of errors and suggestions for character names, looks, or expressions when possible. The engine also validates the story before it opens the game window.

To validate or run another story file, pass its filename relative to the configured data folder:

```powershell
.\VN_Engine\engine.exe --story alternate.yaml --validate
.\VN_Engine\engine.exe --story alternate.yaml
```

The story file selected in `data/project.json` is used when `--story` is omitted. `--story` changes the selected story for that run; it does not edit the project configuration.

To see which character files the engine discovers, run:

```powershell
# List all discovered character names
.\VN_Engine\engine.exe --list-character-assets

# List each look and its expression names for one character
.\VN_Engine\engine.exe --list-character-assets Aiko

# Inspect one look; use forward slashes between nested folders
.\VN_Engine\engine.exe --list-character-assets Aiko --look Summer/Uniform
```

Double-click `engine.exe.lnk` to launch the selected project normally.

## 4. Play controls

| While playing | Control |
| --- | --- |
| Advance to the next line | `Space` or click the game window |
| Finish revealing the current typewriter line | Press `Space` or click once; press/click again to advance |
| Choose an option | Wait for the line to finish, then click a choice |
| Pause | `Esc` |
| Open/close dialogue history | `H` |
| Scroll dialogue history | `Up`/`Down`, `Page Up`/`Page Down`, or mouse wheel |
| Replay the current voice line | `V` |
| Move through a menu | `Up`/`Down` or `W`/`S`; you can also move the mouse |
| Activate a menu item | `Enter` or click |
| Go back from a submenu | `Esc` or `Backspace` |
| Adjust a setting | Select it and press `Left`/`Right`; click a setting row to increase it |
| Save/load a slot | Select a slot, then press `Enter` again or use its Save/Load button |
| Delete the selected save | `Delete` or the Delete button |
| Scroll the credits list | Mouse wheel or `Page Up`/`Page Down` |

The settings menu provides type speed, music volume, sound-effects volume, and windowed/fullscreen display mode. Settings are remembered between launches. Choices are selected with the mouse. The main menu provides Load; the pause menu provides Save and Load. Continue loads whichever is newer: the story autosave or the most recent populated numbered save slot.

## 5. Assets and built-in art

Use these folders for project assets:

| Type | Project folder | Typical reference in YAML or JSON |
| --- | --- | --- |
| Backgrounds and menu images | `assets/images/` | `station` or `images/menu.png` |
| Sound effects | `assets/sounds/` | `door` or `sounds/door.wav` |
| Music tracks | `assets/music/` | `station-theme.ogg` |
| Fonts | `assets/fonts/` | `my-dialogue-font.ttf` |
| Character portraits | `assets/characters/` | `characters/Aiko/Summer/Uniform/Smile.png` |

For images and sound effects, a filename without its extension is convenient: `station` finds `station.png`, and `door` finds `door.wav`, if the name is unique in that category. You can also use a relative path such as `images/station.png`. For music, use the filename with its extension, such as `station-theme.ogg`.

The runtime includes these assets, and the engine searches them after the project’s own `assets/` folder:

| Engine asset folder | Built-in files | Default use |
| --- | --- | --- |
| `engine/assets/fonts/` | `standard.ttf`, `Joystix.ttf`, `MS Gothic.ttf`, `PermanentMarker.ttf`, `rpg-maker-2k.ttf`, `Toriko.ttf`, `VCR_OSD_Mono.ttf` | `standard.ttf` is used for dialogue text and speaker names unless configured otherwise. All can be selected for dialogue or menus. |
| `engine/assets/images/` | `logo.png`, `content_warning.png`, `headphones.png`, `test.png` | `logo.png` is fixed in the opening splash and cannot be replaced. The warning and headphone images appear on the default notice card and can be replaced. `test.png` can be referenced like any other image. |
| `engine/assets/sounds/` | `intro.wav`, `hover_button.wav`, `click_button.wav` | Opening splash sound; default menu hover and click sounds. |

There are no built-in character portraits or music tracks. Add your own under `assets/characters/` and `assets/music/`. The built-in files are bundled in `VN_Engine/engine.exe` in the exported package, even if you do not see a loose `engine/assets/` folder.

### Character folder example

This file:

```text
assets/characters/Aiko/Summer/Uniform/Smile.png
```

defines character `Aiko`, look `Summer/Uniform`, and expression `Smile`. The expression is the PNG filename without `.png`. You can add nested look folders for outfits, moods, or alternate designs. The engine discovers them automatically; see [character art and portraits](./story-format.md#character-art-and-portraits) for defaults and YAML actions.

## 6. Configure the menus and presentation

`data/project.json` controls the displayed project name, selected story, save-slot count, menu labels and order, credits, window dimensions, intro-card text/images, and theme. If a setting is omitted, its built-in default is used. See [project configuration](./project-config.md) for all keys and copyable examples.

The first launch screen uses the engine logo, followed by a creator credit and a content notice. Set `intro.creator`, `intro.game_version`, and `intro.warning_message` to customize the text. You can replace the credit, warning, or headphone images with project images, or set an optional image field to `null` to omit that image. Menu colors, fonts, background, layout, slot artwork, and sounds are part of the theme configuration.

The dialogue textbox can use a color, an image, or both. Set `theme.textbox.color` and `theme.textbox.background` in `data/project.json`; the image is scaled to the panel and transparent parts show the configured color. See [the textbox theme reference](./project-config.md#dialogue-textbox-image-and-color).

The credits menu lists the project’s configured `credits` and also includes the engine creator’s credit. A credit may be plain text or an object with a label and an optional `http://` or `https://` URL.

## 7. Share the editable project (not recommended)

To let someone play or continue editing the project, share the complete project folder or ZIP it. Include the shortcut, `assets/`, `data/`, all documentation, and the full `VN_Engine/` directory. Recipients do not need to install Python or Pygame.

Do not distribute only `engine.exe` from inside `VN_Engine/`: the engine distribution also needs its supporting runtime files. The shortcut is included so Windows starts the engine with the correct project folder.

## 8. Build a project-specific game package (recommended)

From the project root, run:

```powershell
.\VN_Engine\engine.exe --build-game
```

The builder validates the configured story, embeds the project’s `data/` and `assets/` files, and creates `output/`. The project name in `data/project.json` determines the game executable and shortcut names.

```text
output/
  <Project Name>.lnk
  VN_Engine/
    <Project Name>.exe
    ...supporting runtime files...
```

Share the complete `output/` folder. Its project-specific executable contains the story, project configuration, and project assets; the other runtime files beside it are still required. The recipient does not need the authoring project folder.

The output folder must not already exist. Choose another path with `--output-dir` if needed:

```powershell
.\VN_Engine\engine.exe --build-game --output-dir "output-v2"
```

The output path is relative to the project root unless it is absolute. The command must run from a compiled engine distribution, not from a Python source checkout or a previously built game executable. It creates a native build for the operating system running that engine; it does not cross-compile. To ship for macOS or Linux, build on that OS using its matching native engine runtime. The macOS output includes a `.command` launcher; Linux output includes a `.sh` launcher. Windows output includes a `.lnk` shortcut and `.exe` game. Browser/HTML5 export is not supported by this desktop runtime.

To prepare a macOS or Linux engine runtime, build it on that operating system. On the maintainer’s machine, install Python, Pygame, PyYAML, and Nuitka, then run:

```sh
python -m pip install pygame PyYAML nuitka
python compile.py --engine-only --output-dir dist/native-engine
```

The complete `main.dist/` folder produced inside `dist/native-engine/` is the runtime. It contains `engine.exe` on Windows and `engine` on macOS/Linux, plus supporting files. Include that whole folder in the platform’s project package. Repeat the build on each target operating system; these builds do not cross-compile. People using a released matching engine runtime do not need Python or these build tools to build their game package.

## 9. User data and common fixes

Settings and save slots are kept outside the editable project so an engine update or a new project ZIP does not overwrite them. By default, they live under:

```text
%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\
```

The project name is converted to a folder-safe name. Windows uses `%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\`; macOS uses `~/Library/Application Support/Visual Novel Engine/<project name>/user_data/`; Linux uses `$XDG_DATA_HOME/visual-novel-engine/<project name>/user_data/` or `~/.local/share/visual-novel-engine/<project name>/user_data/`. `paths.user_data` in `data/project.json` can select a different location; see [user data, settings, and saves](./project-config.md#user-data-settings-and-saves).

If a story does not start, run `--validate` and follow the reported dialogue path. If a portrait reference is unclear, use `--list-character-assets`; the character folder and PNG filename determine the valid name/look/expression. If the shortcut cannot find files after you rearranged folders, restore the package layout or run the executable from the project root as shown in the commands above.

For YAML field syntax, start with the [story format](./story-format.md). For menu, path, and theme options, use [project configuration](./project-config.md).
