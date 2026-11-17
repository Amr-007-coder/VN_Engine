# VN Engine

The downloadable VN_Editor package is available for Windows, Linux, and macOS. Each platform ZIP contains its native editor app, the editor version, and the user guides. On first launch, the editor creates a starter project from its built-in defaults under `Documents/VN Engine Projects/My Visual Novel` only if that folder does not already exist. Existing projects and their configuration are left untouched. Game runtime templates download from GitHub Releases on first use and are cached locally. Creators do not need Python, Pygame, Pygbag, Nuitka, or a compiler installed to use the editor.

## Start here

1. Extract the ZIP for your computer to a folder you can write to.
2. Launch the editor for that platform: `VN_Editor.exe` on Windows, `VN_Editor` on Linux, or `VN_Editor.app` on macOS. If the default project folder does not exist, the editor creates the starter project locally.
3. Edit `data/story.yaml`, `data/project.json`, and files under `assets/` in the project folder. The starter project is ready to edit.
4. Click **Test Play** to run the project with a temporary copy of the engine runtime for your current OS.
5. Click **Export Game** to create a Windows, Linux, macOS, browser, or Android build.

The extracted editor package contains one platform-specific editor app and does not contain project data:

```text
VN_Editor/
  VN_Editor.exe             # Windows; Linux uses VN_Editor, macOS uses VN_Editor.app/
  engine-version.txt        # Version used to recommend a matching Android runtime release
  readme.md
  docs/                     # The included Markdown guides
```

The starter project is stored separately at `Documents/VN Engine Projects/My Visual Novel`. The editor creates it from its built-in template only if that folder does not exist; later launches preserve its `data/project.json` and all other user files. Use **Open Project** to work on another project folder. Test Play and game export use temporary or output folders. Runtime templates are downloaded on demand from GitHub Releases and cached in the user's local cache.

## What the engine provides

- Dialogue with a typewriter effect, speaker names, text formatting, variable substitution, branching choices, optional voice lines, and a scrollable dialogue history.
- Story variables, player text/integer input, conditional choices, and actions for backgrounds, static and animated character portraits, music, sound effects, fades, screen shake, and command-triggered autosaves.
- Multi-file YAML stories with recursive includes for chapter-sized files.
- Automatic discovery of character looks and PNG expressions from folders.
- Main and pause menus, save/load slots, continue, credits, and settings for text speed, volume, fullscreen, and adjustable UI size.
- A touch-friendly pause button during gameplay, alongside the Escape key on desktop.
- Project-level menu labels, window size, intro cards, credits, textbox image/color, and a declarative menu theme.
- Story validation and a character-asset inventory from the command line.
- An editor export pipeline for Windows, Linux, macOS, and browser game archives using downloaded prebuilt templates, plus Android APKs built from a selected GitHub release.

The [story format reference](./story-format.md) explains how to write each feature. The [project configuration reference](./project-config.md) explains `data/project.json`, application icons, and theme options.

## Built-in assets

The engine includes the following game assets. Desktop builds embed them into the runtime executable; Web and Android builds package them with the Pygbag app. They can be referenced by filename; you do not need to copy them into your project. Project assets with the same relative name take priority for normal image, sound, music, and font lookups. The opening splash logo is fixed to the engine's `logo.png` and cannot be replaced by a project asset.

| Folder in the engine | Included files | Use |
| --- | --- | --- |
| `engine/assets/fonts/` | `standard.ttf`, `Joystix.ttf`, `MS Gothic.ttf`, `PermanentMarker.ttf`, `rpg-maker-2k.ttf`, `Toriko.ttf`, `VCR_OSD_Mono.ttf` | Use in `theme.game_fonts`, `theme.fonts.menu`, or `theme.fonts.title`. `standard.ttf` is the default dialogue font. |
| `engine/assets/images/` | `logo.png`, `pause.png`, `content_warning.png`, `headphones.png`, `test.png` | `logo.png` is fixed in the opening splash. `pause.png` is the in-game pause button. The warning and headphone images are the default notice-card images and can be replaced. `test.png` is available as a general image asset. |
| `engine/assets/sounds/` | `intro.wav`/`.ogg`, `hover_button.wav`/`.ogg`, `click_button.wav`/`.ogg` | Opening splash sound and default menu hover/click sounds. Desktop uses WAV; Web and Android use OGG. |

Projects exported for Web or Android must use `.ogg` for project sound and music assets. Configure a project-specific game/window icon with the optional `icon` field in `data/project.json`; the opening splash continues to show the engine logo.

`engine/assets/images/logo.ico` is the default Windows game executable icon. `editor_logo.png` and `editor_logo.ico` are used when building the VN_Editor application; they are not story image assets.

Project assets are searched before these built-ins for normal asset lookups. The opening splash always uses the engine's own `logo.png`; a project image cannot replace it. Backgrounds and menu art go in `assets/images/`, sound effects in `assets/sounds/`, music in `assets/music/`, fonts in `assets/fonts/`, and character art in `assets/characters/`. See the [user guide](./guide_vn-engine.md#5-assets-and-built-in-art) for path examples.

The dialogue textbox can use a project image, a project color, or both. Configure `theme.textbox.background` and `theme.textbox.color` in `data/project.json`; see [project configuration](./project-config.md#dialogue-textbox-image-and-color). Story chapters can be split into YAML files with the top-level `includes` list; see [story format](./story-format.md#split-a-story-across-yaml-files).

## Use the editor

The editor opens the configured story, each YAML file named by `includes`, and `data/project.json` in separate tabs. It provides YAML/JSON highlighting, engine-specific key and asset suggestions (`Ctrl+Space`), live diagnostics, an expandable Asset hierarchy, and read-only tabs for Markdown guides. `Ctrl+F` searches the selected tab. `Ctrl+S` saves the current file; `Ctrl+Shift+S` saves the open story files and project configuration.

**Test Play** saves and checks the project, downloads the current platform's runtime template if needed, prepares a temporary game using the template and project files, then launches it. The temporary game folder is removed when the game closes or the editor exits. Test Play stores settings and saves in that temporary folder, so it does not change the project's normal save data.

**Export Game** saves and checks the project. Desktop exports embed the project's `assets/` and `data/` files in the game executable and include a platform shortcut: a Windows `.lnk`, a relative Linux symbolic link, or a macOS app-bundle symbolic link. Web exports create a static website ZIP. Runtime templates download from GitHub Releases on demand and remain cached locally. Android exports let you choose a published runtime release, recommend the version matching the editor, fetch the matching engine source temporarily, and create a fresh project-specific Web archive before packaging it as a Capacitor APK; they do not reuse a previously exported `web.zip`. Android export requires Node.js/npm, a Java JDK, the Android SDK, and an internet connection. Web and Android project audio must use OGG files (`.ogg`).

The command pane uses PowerShell on Windows and the available bash, zsh, or sh shell on Linux/macOS. It starts in the project folder and keeps its working directory as commands run. Use **Restart** to reopen the shell.

## Optional VS Code helper

The [VN Engine YAML Helper](https://marketplace.visualstudio.com/items?itemName=Marpp.yaml-helper) can suggest character folders and expression filenames while you edit YAML. It is optional and does not run or change the engine. Open the project root, the folder containing `assets/` and `data/`, in VS Code to use it.

## Where settings and saves go

On Windows, user settings and saves are stored separately from the project under `%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\`. macOS uses `~/Library/Application Support/Visual Novel Engine/<project name>/user_data/`; Linux uses `$XDG_DATA_HOME/visual-novel-engine/<project name>/user_data/` or `~/.local/share/visual-novel-engine/<project name>/user_data/`. See [project configuration](./project-config.md#user-data-settings-and-saves).
