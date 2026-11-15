# VN Engine

VN Engine is a visual novel player and authoring template. The downloadable editor package currently targets Windows. Its Export Game dialog can create Windows, Linux, or macOS game ZIPs from prebuilt runtime templates, without a compiler on the author’s computer. You write the story in YAML, place artwork and audio in the project’s `assets/` folder, then run the project or export a game package.

You do not need to install Python, Pygame, Nuitka, or another tool to use the packaged engine or editor. Keep the extracted files together and use the shortcut or commands below. The included `editor.exe` is a standalone desktop authoring tool.

## Start here

1. Extract the complete ZIP to a folder you can write to. Do not move files out of `VN_Engine/`.
2. Open the extracted project folder in a text editor or Visual Studio Code.
3. Edit `data/story.yaml`. The starter story has one line; replace it or add dialogue. Put your own art and audio in `assets/`.
4. In PowerShell opened at the project folder, validate the story:

   ```powershell
   .\VN_Engine\engine.exe --validate
   ```

5. Double-click `engine.exe.lnk` to play. The shortcut starts the engine with the project folder as its working folder, so it can find `data/` and `assets/`.

The package has this layout:

```text
MyVisualNovel/
  engine.exe.lnk          # Starts the editable project
  readme.md                 # This documentation set
  guide_vn-engine.md
  story-format.md
  project-config.md
  editor.exe               # Standalone story/project editor
  assets/                  # Your images, sounds, music, and character art
  data/
    project.json           # Project name, menus, settings, and theme
    story.yaml             # Story flow and dialogue
  VN_Engine/               # Engine executable and its supporting runtime files
```

`assets/`, `data/`, and the shortcut belong to the project. Treat `VN_Engine/` as read-only. For the full workflow, see the [user guide](./guide_vn-engine.md).

## What the engine provides

- Dialogue with a typewriter effect, speaker names, text formatting, variable substitution, branching choices, optional voice lines, and a scrollable dialogue history.
- Story variables, conditional choices, and actions for backgrounds, static and animated character portraits, music, sound effects, fades, screen shake, and command-triggered autosaves.
- Multi-file YAML stories with recursive includes for chapter-sized files.
- Automatic discovery of character looks and PNG expressions from folders.
- Main and pause menus, save/load slots, continue, credits, and settings for text speed, volume, and fullscreen.
- Project-level menu labels, window size, intro cards, credits, and a declarative menu theme.
- Story validation and a character-asset inventory from the command line.
- An editor export pipeline for standalone Windows, Linux, and macOS desktop game archives using prebuilt runtime templates.

The [story format reference](./story-format.md) explains how to write each feature. The [project configuration reference](./project-config.md) explains `data/project.json` and the theme options.

## Built-in assets

The engine includes the following assets. They are inside the packaged runtime and can be referenced by filename; you do not need to copy them into your project. Project assets with the same relative name take priority for normal image, sound, music, and font lookups. The opening splash logo is fixed to the engine's `logo.png` and cannot be replaced by a project asset.

| Folder in the engine | Included files | Use |
| --- | --- | --- |
| `engine/assets/fonts/` | `standard.ttf`, `Joystix.ttf`, `MS Gothic.ttf`, `PermanentMarker.ttf`, `rpg-maker-2k.ttf`, `Toriko.ttf`, `VCR_OSD_Mono.ttf` | Use in `theme.game_fonts`, `theme.fonts.menu`, or `theme.fonts.title`. `standard.ttf` is the default dialogue font. |
| `engine/assets/images/` | `logo.png`, `content_warning.png`, `headphones.png`, `test.png` | `logo.png` is fixed in the opening splash. The warning and headphone images are the default notice-card images and can be replaced. `test.png` is available as a general image asset. |
| `engine/assets/sounds/` | `intro.wav`, `hover_button.wav`, `click_button.wav` | Opening splash sound and default menu hover/click sounds. |

Project assets are searched before these built-ins for normal asset lookups. The opening splash always uses the engine's own `logo.png`; a project image cannot replace it. Backgrounds and menu art go in `assets/images/`, sound effects in `assets/sounds/`, music in `assets/music/`, fonts in `assets/fonts/`, and character art in `assets/characters/`. See the [user guide](./guide_vn-engine.md#5-assets-and-built-in-art) for path examples.

The dialogue textbox can use a project image, a project color, or both. Configure `theme.textbox.background` and `theme.textbox.color` in `data/project.json`; see [project configuration](./project-config.md#dialogue-textbox-image-and-color). Story chapters can be split into YAML files with the top-level `includes` list; see [story format](./story-format.md#split-a-story-across-yaml-files).

## Useful commands

Run these from the extracted project folder:

```powershell
# Validate the configured story without opening a window
.\VN_Engine\engine.exe --validate

# Validate a different YAML story in the configured data folder
.\VN_Engine\engine.exe --story alternate.yaml --validate

# List characters, then inspect one character’s looks and expressions
.\VN_Engine\engine.exe --list-character-assets
.\VN_Engine\engine.exe --list-character-assets Aiko
.\VN_Engine\engine.exe --list-character-assets Aiko --look Summer/Uniform

# Build for the OS running this engine (the editor can export for any supported OS)
.\VN_Engine\engine.exe --build-game
```

The `--build-game` command creates a game for the same OS as the engine runtime. For cross-platform exports, use the editor’s **Export Game…** button and provide the prebuilt template ZIP for the target OS. Download `template-windows.zip`, `template-linux.zip`, and `template-macos.zip` from the project’s GitHub release assets and place them in a `templates/` folder beside `editor.exe` or in the project folder. You can also select any templates folder in the export dialog. Browser/HTML5 exports are not supported by this Pygame desktop runtime.

See the [user guide](./guide_vn-engine.md) for command details and the [story format](./story-format.md#character-art-and-portraits) for character folders.

## Optional VS Code helper

The [VN Engine YAML Helper](https://marketplace.visualstudio.com/items?itemName=Marpp.yaml-helper) can suggest character folders and expression filenames while you edit YAML. It is optional and does not run or change the engine. Open the project root—the folder containing `assets/` and `data/`—in VS Code to use it.

## Optional desktop editor

The Windows package includes `editor.exe`, a standalone editor with a tab for the entry story, tabs for each included YAML file, a project JSON tab, YAML and JSON highlighting, field suggestions, asset browsing, live diagnostics, a PowerShell command pane, read-only tabs for the included Markdown guides, and a cross-platform **Export Game…** dialog. It does not require an installed Python or compiler. Its terminal uses Windows PowerShell, which is included with Windows. Double-click `editor.exe`, or run it from PowerShell in the project folder:

```powershell
.\editor.exe
```

Suggestions appear while typing; press `Ctrl+Space` to open them, use the arrow keys to choose an item, then press `Tab` or `Enter` to insert it. Double-click an asset to insert its reference. `Ctrl+S` saves the selected file, `Ctrl+Shift+S` saves all open story files and `project.json`, `F5` saves and runs the engine validator, and `Ctrl+F` searches the current tab. For export, download the target platform’s template ZIP into the local `templates/` folder, click **Export Game…**, choose the target platform, and select where to save the game ZIP. The PowerShell pane starts in the project folder and keeps its working directory as you run commands. To open another project, run `.\editor.exe --project-dir "C:\path\to\project"`.

## Where settings and saves go

On Windows, user settings and saves are stored separately from the project under `%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\`. macOS uses `~/Library/Application Support/Visual Novel Engine/<project name>/user_data/`; Linux uses `$XDG_DATA_HOME/visual-novel-engine/<project name>/user_data/` or `~/.local/share/visual-novel-engine/<project name>/user_data/`. See [project configuration](./project-config.md#user-data-settings-and-saves).
