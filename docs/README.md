# VN Engine

The downloadable VN_Editor package is available for Windows, Linux, and macOS. Each platform ZIP contains its native editor app, the Windows/Linux/macOS game runtime templates, a starter `assets/` folder, `data/`, and the Markdown guides. Creators do not need Python, Pygame, Nuitka, or a compiler installed. A separate `template-web.zip` is available for web-enabled editor builds; download it from the matching GitHub release and place it in the editor package's `templates/` folder. Older editor executables need to be rebuilt before they show the Web export target.

## Start here

1. Extract the ZIP for your computer to a folder you can write to.
2. Launch the editor for that platform: `VN_Editor.exe` on Windows, `VN_Editor` on Linux, or `VN_Editor.app` on macOS.
3. Edit `data/story.yaml`, `data/project.json`, and files under `assets/`. The starter project is ready to edit.
4. Click **Test Play** to run the project with a temporary copy of the engine runtime for your current OS.
5. Click **Export Game** to create a Windows, Linux, macOS, or browser build from its prebuilt template.

The extracted editor package has this layout; it contains one platform-specific editor app:

```text
MyVisualNovel/
  VN_Editor.exe             # Windows; Linux uses VN_Editor, macOS uses VN_Editor.app/
  templates/
    template-windows.zip
    template-linux.zip
    template-macos.zip
    template-web.zip          # Optional browser export template, downloaded separately
  assets/                   # Project art, sound, music, fonts, and character art
  data/
    project.json            # Project name, menus, settings, and theme
    story.yaml              # Starter story
  readme.md
  docs/                     # The included Markdown guides
```

The editor and `templates/` are tools for authoring and running the project. Edit `assets/` and `data/`; Test Play and game export use temporary or output folders and do not require moving files into the editor app.

## What the engine provides

- Dialogue with a typewriter effect, speaker names, text formatting, variable substitution, branching choices, optional voice lines, and a scrollable dialogue history.
- Story variables, conditional choices, and actions for backgrounds, static and animated character portraits, music, sound effects, fades, screen shake, and command-triggered autosaves.
- Multi-file YAML stories with recursive includes for chapter-sized files.
- Automatic discovery of character looks and PNG expressions from folders.
- Main and pause menus, save/load slots, continue, credits, and settings for text speed, volume, and fullscreen.
- Project-level menu labels, window size, intro cards, credits, and a declarative menu theme.
- Story validation and a character-asset inventory from the command line.
- An editor export pipeline for Windows, Linux, macOS, and browser game archives using prebuilt templates.

The [story format reference](./story-format.md) explains how to write each feature. The [project configuration reference](./project-config.md) explains `data/project.json` and the theme options.

## Built-in assets

The engine includes the following assets. Desktop builds embed them into the runtime executable; the browser template packages them in its Pygbag app archive. They can be referenced by filename; you do not need to copy them into your project. Project assets with the same relative name take priority for normal image, sound, music, and font lookups. The opening splash logo is fixed to the engine's `logo.png` and cannot be replaced by a project asset.

| Folder in the engine | Included files | Use |
| --- | --- | --- |
| `engine/assets/fonts/` | `standard.ttf`, `Joystix.ttf`, `MS Gothic.ttf`, `PermanentMarker.ttf`, `rpg-maker-2k.ttf`, `Toriko.ttf`, `VCR_OSD_Mono.ttf` | Use in `theme.game_fonts`, `theme.fonts.menu`, or `theme.fonts.title`. `standard.ttf` is the default dialogue font. |
| `engine/assets/images/` | `logo.png`, `content_warning.png`, `headphones.png`, `test.png` | `logo.png` is fixed in the opening splash. The warning and headphone images are the default notice-card images and can be replaced. `test.png` is available as a general image asset. |
| `engine/assets/sounds/` | `intro.wav`, `hover_button.wav`, `click_button.wav` | Opening splash sound and default menu hover/click sounds. |

The browser template converts its built-in WAV sounds to OGG. Projects exported for the browser must also use `.ogg` for all sound and music assets.

Project assets are searched before these built-ins for normal asset lookups. The opening splash always uses the engine's own `logo.png`; a project image cannot replace it. Backgrounds and menu art go in `assets/images/`, sound effects in `assets/sounds/`, music in `assets/music/`, fonts in `assets/fonts/`, and character art in `assets/characters/`. See the [user guide](./guide_vn-engine.md#5-assets-and-built-in-art) for path examples.

The dialogue textbox can use a project image, a project color, or both. Configure `theme.textbox.background` and `theme.textbox.color` in `data/project.json`; see [project configuration](./project-config.md#dialogue-textbox-image-and-color). Story chapters can be split into YAML files with the top-level `includes` list; see [story format](./story-format.md#split-a-story-across-yaml-files).

## Use the editor

The editor opens the configured story, each YAML file named by `includes`, and `data/project.json` in separate tabs. It provides YAML/JSON highlighting, engine-specific key and asset suggestions, asset browsing, live diagnostics, and read-only tabs for the included Markdown files. `Ctrl+F` searches the selected tab. `Ctrl+S` saves the current file; `Ctrl+Shift+S` saves the open story files and project configuration.

**Test Play** saves and checks the project, copies the current platform's game template and project files to a temporary folder, then launches that game. The temporary folder is removed when the game closes or the editor exits. Test Play stores settings and saves in that temporary folder, so it does not change the project's normal save data.

**Export Game** saves and checks the project, then embeds its `assets/` and `data/` files in a desktop game executable. Desktop ZIPs also contain a platform shortcut: a Windows `.lnk`, a relative Linux symbolic link, or a macOS app-bundle symbolic link. For a browser export, the ZIP contains a static website with an `index.html`; upload its contents to a web host, or serve it through a local HTTP server. The browser build loads the Pygbag runtime from its CDN, so players need an internet connection. Browser project audio must use OGG files (`.ogg`).

The command pane uses PowerShell on Windows and the available bash, zsh, or sh shell on Linux/macOS. It starts in the project folder and keeps its working directory as commands run. Use **Restart** to reopen the shell.

## Optional VS Code helper

The [VN Engine YAML Helper](https://marketplace.visualstudio.com/items?itemName=Marpp.yaml-helper) can suggest character folders and expression filenames while you edit YAML. It is optional and does not run or change the engine. Open the project root, the folder containing `assets/` and `data/`, in VS Code to use it.

## Where settings and saves go

On Windows, user settings and saves are stored separately from the project under `%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\`. macOS uses `~/Library/Application Support/Visual Novel Engine/<project name>/user_data/`; Linux uses `$XDG_DATA_HOME/visual-novel-engine/<project name>/user_data/` or `~/.local/share/visual-novel-engine/<project name>/user_data/`. See [project configuration](./project-config.md#user-data-settings-and-saves).
