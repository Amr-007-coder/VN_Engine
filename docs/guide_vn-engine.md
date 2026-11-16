# VN Engine user guide

This guide takes you from the platform-specific VN_Editor download to a playable project and a shareable game. Editor packages include the game runtime templates selected for that release, which can include Windows, Linux, macOS, and Web. Creators do not need Python, Pygame, Nuitka, or a compiler installed.

## 1. Extract and open the editor package

Extract the ZIP for your computer to a folder you can write to. Keep its project folders together. Launch the platform-specific editor app: `VN_Editor.exe` on Windows, `VN_Editor` on Linux, or `VN_Editor.app` on macOS.

The macOS editor app is not signed or notarized. If macOS blocks it on first launch, Control-click `VN_Editor.app` in Finder and choose **Open**.

```text
MyVisualNovel/                 # Project and editor package root
  VN_Editor.exe                # Windows; Linux uses VN_Editor, macOS uses VN_Editor.app/
  templates/
    template-windows.zip       # Prebuilt game runtimes used by Test Play and Export Game
    template-linux.zip
    template-macos.zip
    template-web.zip           # Present when Web was selected for the release
  android-web-source/          # Current engine and YAML sources used for fresh APK exports
  assets/                      # Project art and audio
  data/
    project.json               # Project settings
    story.yaml                 # Starter story
  readme.md
  docs/                        # This guide and the other Markdown references
```

The folder containing `assets/` and `data/` is the project root. The editor opens this packaged starter project automatically. Keep `android-web-source/` beside the editor; Android export uses it to build a fresh web app and does not read `template-web.zip`. Use **Open Project** to select another project folder.

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

## 3. Validate and test the project

The editor opens `data/project.json`, the selected story, and every YAML file listed by `includes`. Its live diagnostics check YAML syntax, story structure, supported keys and actions, project values, and asset references while you edit. Press `Ctrl+Space` for suggestions and `Ctrl+F` to search the active tab.

Press `F5` to save the open files and run the engine validator. The editor uses an installed engine runtime if the project has one. Otherwise, it prepares the current OS runtime template in a temporary folder and validates the packaged project there.

Click **Test Play** to save and check the project, place a copy of the current platform template with the project's `assets/` and `data/` in a temporary folder, and launch the game. Test Play uses a temporary `user_data/` folder. When the game closes, the editor removes the temporary build and its temporary saves. Closing the editor also stops an active test game and removes its temporary folder.

The editor command pane starts in the project folder. It uses PowerShell on Windows and the available bash, zsh, or sh shell on Linux/macOS. Commands can change the working folder; use **Restart** to start a fresh shell in the project root.

## 4. Play controls

| While playing | Control |
| --- | --- |
| Advance to the next line | `Space` or click the game window |
| Finish revealing the current typewriter line | Press `Space` or click once; press/click again to advance |
| Choose an option | Wait for the line to finish, then click a choice |
| Pause | `Esc` or the on-screen pause button in the upper-left corner |
| Open/close dialogue history | `H` |
| Scroll dialogue history | `Up`/`Down`, `Page Up`/`Page Down`, or mouse wheel |
| Replay the current voice line | `V` |
| Move through a menu | `Up`/`Down` or `W`/`S`; you can also move the mouse |
| Activate a menu item | `Enter` or click |
| Go back from a submenu | `Esc` or `Backspace` |
| Adjust a setting | Select it and press `Left`/`Right`; click the left or right half of a setting row to decrease or increase it |
| Save/load a slot | Select a slot, then press `Enter` again or use its Save/Load button |
| Delete the selected save | `Delete` or the Delete button |
| Scroll the credits list | Mouse wheel or `Page Up`/`Page Down` |

The settings menu provides type speed, music volume, sound-effects volume, UI size, and windowed/fullscreen display mode. UI size defaults to 120% and can be changed from 80% to 160%. Settings are remembered between launches. Choices are selected with the mouse or touch. On Android, the game requests that the display stay awake while the app is active. The main menu provides Load; the pause menu provides Save and Load. Continue loads whichever is newer: the story autosave or the most recent populated numbered save slot.

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
| `engine/assets/images/` | `logo.png`, `pause.png`, `content_warning.png`, `headphones.png`, `test.png` | `logo.png` is fixed in the opening splash and cannot be replaced. `pause.png` draws the in-game pause button; its size follows the UI Size setting. The warning and headphone images appear on the default notice card and can be replaced. `test.png` can be referenced like any other image. |
| `engine/assets/sounds/` | `intro.wav`/`.ogg`, `hover_button.wav`/`.ogg`, `click_button.wav`/`.ogg` | Opening splash and default menu hover/click sounds. Desktop builds use the WAV files; fresh Web and Android builds use their OGG counterparts. |

There are no built-in character portraits or music tracks. Add your own under `assets/characters/` and `assets/music/`. Built-in engine assets are bundled in each platform runtime template; you do not need a separate `VN_Engine/` folder to use Test Play or Export Game.

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

## 7. Share the editable project

To let someone play or continue editing, share the complete project folder with `assets/`, `data/`, and all YAML files named by `includes`. Recipients can open that folder from VN_Editor. Include the editor package and its `templates/` folder when they also need the authoring and Test Play tools.

The platform editor ZIP includes the game runtime templates selected for that release under `templates/`; the editor uses the current platform template for Test Play and any available selected platform template for export.

## 8. Export a desktop, browser, or Android game

The editor packages games for any supported desktop OS from a prebuilt runtime template. Built-in engine assets and data are compiled into each template executable as native constants. When you export a project, its own `assets/` and `data/` files are bundled into the game executable; the computer doing the export needs no compiler.

The release determines which `template-*.zip` files are included in each editor package. If a target is missing, it was not selected for that release; the editor also searches beside its application and in the project folder. If you move the templates, use **Browse** in the export dialog to select their folder. See the [release build guide](./releasing.md) for selecting targets.

To export in the editor:

1. Open the project and click **Export Game**.
2. Choose Windows, Linux, macOS, Web, or Android.
3. Choose the output file and click **Export**.

The editor saves its open YAML and JSON files, checks the project and story, then adds the project's configured `assets/` and `data/` files to the selected runtime executable. It rewrites the project paths to portable `assets/` and `data/` names inside that embedded bundle. The ZIP also contains a platform shortcut beside the game folder:

```text
Windows:
  <Game Name>/
    <Game Name>.exe        # Project assets and data are embedded here
    Shortcut.lnk
    ...runtime files...

Linux:
  <Game Name>/
    <Game Name>            # Project assets and data are embedded here
    Shortcut -> <Game Name>  # Relative symbolic link
    ...runtime files...

macOS:
  <Game Name> Shortcut.app -> <Game Name>.app  # Relative symbolic link
  <Game Name>.app/
    Contents/
      MacOS/Runner
```

The optional `icon` field in `data/project.json` sets the exported game's window icon and native app/file icon where supported. See [project configuration](./project-config.md#application-icon) for path and platform details.

The editor's own starter `assets/` and `data/` stay as editable files beside VN_Editor. Only exported game archives embed the project files in the game executable.

Linux and macOS archives preserve executable permissions for the main program and shared libraries. The macOS exporter removes the template bundle signature because it changes the app bundle; exported macOS apps are not signed or notarized. Players need the matching OS to run a desktop export.

A Web export is a static website ZIP containing `index.html`, the packaged game data, and the Pygbag runtime files. Upload the ZIP contents to a static web host, or start an HTTP server in the extracted folder to preview it. Opening `index.html` directly as a `file://` URL is not supported. The game loads its runtime from the exported files and does not need internet access after those files are available to the browser. Project sound and music files must be OGG (`.ogg`) for browser exports; convert WAV, MP3, and AIFF files before exporting.

An Android export creates a fresh Pygbag web build from the current engine source and project, then packages it as a Capacitor debug APK. It does not use `template-web.zip` or need Python installed; the editor includes the Pygbag build package and the engine source used for this build. Install Node.js/npm, a Java JDK, and the Android SDK (for example, through Android Studio) on the export computer. The build downloads current Pygbag runtime and Android dependencies, so it needs an internet connection. The APK uses `android.app_name`, `android.app_id`, and `android.orientation` from `data/project.json`; `icon` sets its launcher icon. The orientation defaults to landscape. Debug APKs are for testing and sideloading; Play Store distribution requires a signed release build.

### Command-line export

The editor ZIP does not include a command-line engine executable. These commands apply when you also have a separate compiled engine distribution; from the source repository, run `python main.py` with the same flags. Without `--platform`, `--build-game` makes a native package. With `--platform`, it creates a ZIP from the selected prebuilt template in `--output-dir`, which defaults to the project `output/` folder. The Android CLI normally builds an APK from `template-web.zip`. When running from the source repository, add `--fresh-android-web` to build the web app from current Pygbag and engine sources instead:

```powershell
.\VN_Engine\engine.exe --build-game --platform windows
.\VN_Engine\engine.exe --build-game --platform linux
.\VN_Engine\engine.exe --build-game --platform macos --templates-dir "D:\vn-templates" --output-dir output
.\VN_Engine\engine.exe --build-game --platform web --templates-dir "D:\vn-templates" --output-dir output
.\VN_Engine\engine.exe --build-game --platform android --templates-dir "D:\vn-templates" --output-dir output
python main.py --build-game --platform android --fresh-android-web --output-dir output
```

The source engine defaults to `engine/templates/` and also checks `templates/` in the project folder. Pass `--templates-dir` to select another folder. For example, the Linux command creates `output/<Game Name>-linux.zip`.

To publish a release, run `python .\tools\release.py` from the repository root. It reads `engine/data/version.txt`, asks which templates and editor packages to build, then pushes the branch and an annotated version tag. One GitHub Actions workflow builds and attaches the selected assets. It uses Git directly and does not require `gh`; see the [release build guide](./releasing.md). A released editor can export without Python, Pygame, Pygbag, Nuitka, or a compiler installed.

## 9. User data and common fixes

Settings and save slots are kept outside the editable project so an engine update or a new project ZIP does not overwrite them. By default, they live under:

```text
%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\
```

The project name is converted to a folder-safe name. Windows uses `%LOCALAPPDATA%\Visual Novel Engine\<project name>\user_data\`; macOS uses `~/Library/Application Support/Visual Novel Engine/<project name>/user_data/`; Linux uses `$XDG_DATA_HOME/visual-novel-engine/<project name>/user_data/` or `~/.local/share/visual-novel-engine/<project name>/user_data/`. `paths.user_data` in `data/project.json` can select a different location; see [user data, settings, and saves](./project-config.md#user-data-settings-and-saves).

If a story does not start, press `F5` to run the engine validator or use **Test Play** to launch the current platform build. If a portrait reference is unclear, use the editor asset hierarchy or character inventory command from a separate engine distribution. If files appear missing, confirm the project root contains the configured `assets/` and `data/` folders.

For YAML field syntax, start with the [story format](./story-format.md). For menu, path, and theme options, use [project configuration](./project-config.md).
