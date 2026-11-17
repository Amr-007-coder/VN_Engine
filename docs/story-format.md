# Story format reference

A story is a UTF-8 YAML file in the project’s configured data folder (`data/` by default). The default filename is `story.yaml`, selected in `data/project.json`. YAML indentation defines the structure: use spaces, not tabs.

Open the project in VN_Editor. Its live diagnostics check YAML syntax and engine-specific story rules as you edit. Press `F5` to run the engine validator, or click **Test Play** to validate and launch the current platform build.

If you are using a separate compiled engine distribution or running the engine from source, you can also validate the configured story from PowerShell at the project root:

```powershell
.\VN_Engine\engine.exe --validate
```

You can validate another YAML file in the data folder with `--story`:

```powershell
.\VN_Engine\engine.exe --story prologue.yaml --validate
```

The engine validates the selected story before opening its window. Validation catches malformed dialogue, missing targets, undeclared variables, invalid conditions/actions, and missing asset references.

## Small complete story

This example uses no external art or sound, so it can run by itself. The final dialogue has no `next` or `options`, so it ends the story.

```yaml
title: At the station
start: arrival

variables:
  player_name: Mira
  trust: 0
  has_ticket: false

dialogues:
  arrival:
    chapter: The Station
    speaker: Narrator
    active_character: null
    text: "A stranger greets {player_name}."
    next: question

  question:
    speaker: Stranger
    active_character: null
    text: "Will you help me find the platform?"
    options:
      - label: Offer to help
        target: help
      - label: Keep walking
        target: leave

  help:
    speaker: Narrator
    active_character: null
    text: "You point toward the platform. The stranger gives you a ticket."
    actions:
      - type: set
        var: has_ticket
        value: true
      - type: add
        var: trust
        value: 1
    next: ending

  leave:
    speaker: Narrator
    active_character: null
    text: "The stranger disappears into the crowd."
    next: ending

  ending:
    speaker: Narrator
    active_character: null
    text: "The train arrives."
```

You can copy this into `data/story.yaml`, save it, then press `F5` to validate or click **Test Play** to run it.

## Story structure and dialogue fields

| Field | Required? | Meaning |
| --- | --- | --- |
| `title` | No | Story title. Used as a fallback chapter name in save metadata. |
| `start` | Yes | ID of the first dialogue under `dialogues`. |
| `includes` | No | Ordered list of other YAML story files, relative to this file. Their dialogues, variables, and character defaults join this story. |
| `variables` | No | Mapping from variable names to starting scalar values: strings, numbers, booleans, or `null`. |
| `character_defaults` | No | Per-character default look and/or position. See [character portraits](#character-art-and-portraits). |
| `dialogues` | Yes | Non-empty mapping from unique IDs to dialogue objects. |

Each dialogue needs `speaker` and `text`, both strings. The engine also reads these optional fields:

| Field | Meaning |
| --- | --- |
| `chapter` | Chapter or scene label shown in save-slot metadata. If omitted, the story `title` is used. |
| `active_character` | Character ID to highlight for this line. By default it is the same as `speaker`. Set it to `null` for narration or a speaker with no portrait. |
| `voice` | Optional sound asset played when this dialogue begins. For example, `voices/aiko_001.ogg` refers to `assets/sounds/voices/aiko_001.ogg`. It uses the sound-effects volume. Press `V` during play to replay the current line’s voice. |
| `next` | ID of the next dialogue in a linear sequence. |
| `options` | Ordered list of player choices. Each item has a visible `label`, a `target` dialogue ID, and an optional `condition`. |
| `actions` | Actions applied when this dialogue is entered. |

Use IDs without spaces, such as `platform_question` or `ending_1`, and reference them exactly. A dialogue uses `next` for linear flow or `options` for a choice. When a line has neither, the story ends after that line. A choice whose condition is false is hidden. If every choice is hidden and there is no `next`, advancing ends the story.

The player can press `Space` or click to reveal a line instantly, then press/click again to advance. Choices appear after the dialogue text has finished revealing.

Press `H` during play to open or close the scrollable dialogue history. Use Up/Down, Page Up/Page Down, or the mouse wheel to scroll; `Esc` or a click closes it. History entries show the speaker and text after variable substitution. Up to 2,000 entries are kept and are stored in both numbered saves and autosaves. A dialogue’s optional `voice` sound plays when its line begins; press `V` to replay that line.

## Split a story across YAML files

Keep the project’s configured story file as the entry point, then list chapter files under `includes`. Paths are relative to the YAML file that contains the list, use forward slashes, and must stay inside the configured `data/` folder. Included files can themselves include more YAML files.

```text
data/
  story.yaml
  chapters/
    station.yaml
    ending.yaml
```

```yaml
# data/story.yaml
title: At the station
start: arrival
includes:
  - chapters/station.yaml
  - chapters/ending.yaml

variables:
  trust: 0

dialogues:
  arrival:
    speaker: Narrator
    text: "The train doors open."
    next: station_question
```

An included file defines dialogue IDs in the same way. Dialogue targets can point to IDs in any included file:

```yaml
# data/chapters/station.yaml
dialogues:
  station_question:
    speaker: Aiko
    text: "Should we take the northern train?"
    options:
      - label: Go north
        target: north_ending
      - label: Stay here
        target: ending
```

```yaml
# data/chapters/ending.yaml
dialogues:
  north_ending:
    speaker: Narrator
    text: "You board the northern train."
  ending:
    speaker: Narrator
    text: "You wait at the station."
```

Included files may define `includes`, `dialogues`, `variables`, and `character_defaults`. Only the entry file defines `title` and `start`. Dialogue IDs, variable names, and character-default IDs must be unique across the full include tree; duplicates and include cycles are errors. Variables and character defaults are merged before the story starts, so actions in any chapter can use declarations from another file. The editor creates a tab for each included file after you save the include list.

## Variables and text substitution

Declare every story variable in the top-level `variables` mapping before using it in an action or condition. Variables may start as strings, numbers, booleans, or `null`; lists and objects are not supported as starting values.

Put a variable name inside braces to print its current value in dialogue text:

```yaml
variables:
  name: Mira
  coins: 3

dialogues:
  greeting:
    speaker: Shopkeeper
    text: "Hello, {name}. You have {coins} coins."
```

The name inside `{...}` must match a declared variable. If it does not, the placeholder is shown literally, such as `{missing_name}`. Keep braces for substitutions; there is no separate escape syntax.
Formatting markers inside a placeholder are treated as part of the variable name, so underscores in names such as `{player_name}` do not activate italic text. Formatting markers outside placeholders, such as `_italic text_`, continue to work normally.

## Choices and conditions

Choices are shown in the order listed. A choice requires a non-empty `label` and a `target` that names an existing dialogue:

```yaml
options:
  - label: Use the ticket
    target: board_train
    condition:
      var: has_ticket
      op: "=="
      value: true
  - label: Ask for directions
    target: ask_directions
```

A simple condition compares a declared variable to a value:

```yaml
condition:
  var: trust
  op: ">="
  value: 1
```

Supported operators are:

| Operator | Meaning |
| --- | --- |
| `==` | Equal to |
| `!=` | Not equal to |
| `<`, `<=`, `>`, `>=` | Numeric or string comparison |
| `in` | Variable value occurs in the condition’s string or list |
| `not_in` | Variable value does not occur in the condition’s string or list |

For `<`, `<=`, `>`, and `>=`, both values must be numbers or both strings. For `in` and `not_in`, `value` must be a string or list. For example, test whether a string variable equals one of several listed values like this:

```yaml
condition:
  var: route
  op: in
  value: [north, west]
```

Combine checks with `all`, `any`, and `not`. `all` and `any` each take a non-empty list of conditions; `not` wraps one condition:

```yaml
condition:
  all:
    - var: trust
      op: ">="
      value: 2
    - not:
        var: has_ticket
        op: "=="
        value: true
```

```yaml
condition:
  any:
    - var: route
      op: "=="
      value: north
    - var: route
      op: "=="
      value: west
```

Conditions can only read variables declared in `variables`. A condition that is invalid at runtime does not pass validation; if a comparison cannot be evaluated, it is treated as false.

## Actions

Actions run each time the engine enters their dialogue, before its text is shown. They can change story variables or update the scene. Assignment actions are applied to story state; visual and audio actions are handled by the engine.

### Change variables

```yaml
actions:
  - type: set
    var: has_ticket
    value: true
  - type: add
    var: trust
    value: 1
  - type: subtract
    var: coins
    value: 2
```

`set` replaces the value. `add` and `subtract` require both the declared variable and action value to be numeric; booleans are not numbers for this purpose. Action values may be strings, numbers, booleans, or `null` for `set`.

### Collect player input

Use an `input` action to ask the player for a value and store it in a declared story variable. Text is the default input type; `integer` accepts whole numbers and saves them as numbers rather than strings.

```yaml
variables:
  player_name: ""
  player_age: 0

dialogues:
  ask_name:
    speaker: Narrator
    text: "What should we call you?"
    actions:
      - type: input
        var: player_name
        prompt: "Enter your name:"
    next: ask_age

  ask_age:
    speaker: Narrator
    text: "How old are you, {player_name}?"
    actions:
      - type: input
        var: player_age
        prompt: "Enter your age as a whole number:"
        input_type: integer
```

After the dialogue text finishes typewriting, the prompt appears in its own panel without dimming the rest of the screen. Story controls remain paused until a non-empty answer is submitted with `Enter`; Backspace edits the answer. Integer input stays open until a whole number is entered. Text answers are trimmed at the ends. Each dialogue may contain at most one input action, and it cannot also autosave on entry. Collected values become normal story variables, so `{player_name}` substitution, conditions, and existing save/load slots work with them.

### Change backgrounds, music, and sound

```yaml
actions:
  - type: background
    image: station
  - type: music
    track: station-theme.ogg
  - type: sound
    name: train-bell
```

| Action | Required key | Effect |
| --- | --- | --- |
| `background` | `image` | Loads and displays the named image, scaled to the game window. |
| `clear_background` | None | Removes the current background. |
| `music` | `track` | Starts the named music track and loops it. Choosing the currently playing track does not restart it. |
| `stop_music` | None | Stops the current music. |
| `sound` | `name` | Plays a one-shot sound effect. |

Images resolve from the project `assets/` folder first, then from engine assets. Sound effects and music follow the same project-first lookup. A project asset can be written as a path from `assets/`, such as `images/station.png`, or by its unique filename stem, such as `station`. Music references should include the filename and extension, such as `station-theme.ogg`. The settings menu controls music and sound-effect volume separately.

### Screen effects and sprite animations

Use `fade`, `shake`, and `animate_character` actions to add effects when a dialogue begins:

```yaml
actions:
  - type: fade
    direction: out
    duration: 0.8
    color: [0, 0, 0]
  - type: shake
    duration: 0.4
    intensity: 10
  - type: animate_character
    name: Aiko
    look: Summer/Uniform
    frames: [BlinkClosed, BlinkOpen]
    frame_duration: 0.15
    loop: true
```

`fade.direction` is `out` to cover the scene with the chosen color or `in` to reveal the scene from that color. `duration` is measured in seconds. The default fade duration is `0.6` seconds and the default fade color is black. `color` accepts `[R, G, B]` or `[R, G, B, A]`, with channels from `0` to `255`. A fade out waits until it finishes before the player can advance. To change scenes under a fade, put the fade out on the current dialogue, then put the `background` and a fade in on the next dialogue:

```yaml
  before_transition:
    speaker: Narrator
    text: "The lights go dark."
    actions:
      - type: fade
        direction: out
        duration: 0.7
    next: after_transition

  after_transition:
    speaker: Narrator
    text: "The lights come back on in a new place."
    actions:
      - type: background
        image: night_street
      - type: fade
        direction: in
        duration: 0.7
```

`shake.duration` defaults to `0.35` seconds. `shake.intensity` defaults to `8` pixels and may be set from above `0` through `100`; a higher value moves the whole game scene farther. A new shake action replaces any shake still running.

`animate_character` shows or updates a character using a repeating sequence of expression PNGs. Put each frame in the same character look folder, and list each filename without `.png` in `frames`. At least two frames are required. `look` and `position` are optional; omitted values use the visible character's current values, then `character_defaults`, then the normal defaults. `frame_duration` is the time each image stays on screen in seconds (default `0.25`). Set `loop: false` to stop on the last frame; the default is `true`. The animation is included in saves and resumes from its first frame when loaded.

```text
assets/characters/Aiko/Summer/Uniform/
  BlinkClosed.png
  BlinkOpen.png
```

Use `show_character` later to stop the animation and switch to a single expression, or use `hide_character` to remove the portrait.

### Save an autosave from the story

Add an `autosave` action to any dialogue to overwrite the project’s dedicated autosave with the current story position, variables, scene, portraits, and dialogue history:

```yaml
actions:
  - type: autosave
```

The action runs once when the dialogue is entered. It does not consume a numbered save slot. The main-menu Continue command loads whichever is newer: the autosave or the most recently saved numbered slot. Numbered saves remain available in the regular Save/Load screens.

### Show and remove character portraits

```yaml
actions:
  - type: show_character
    name: Aiko
    look: Summer/Uniform
    expression: Smile
    position: left
  - type: hide_character
    name: Aiko
```

| Action | Required keys | Effect |
| --- | --- | --- |
| `show_character` | `name`, `expression` | Adds a portrait or updates an already visible character’s expression, look, or position. |
| `hide_character` | `name` | Hides one visible character. |
| `clear_characters` | None | Hides every visible character. |

Valid positions are `far_left`, `left`, `center`, `right`, and `far_right`. A new portrait uses its configured default position or `center`. When updating a visible portrait, omitted look and position keep their current values. The speaking/active character is drawn at full brightness; other visible characters are dimmed. Characters remain visible until hidden or cleared.

## Character art and portraits

Create one PNG for each expression. The first folder below `characters/` is the character ID, any folders between it and the PNG make up the look path, and the PNG filename without `.png` is the expression:

```text
assets/
  characters/
    Aiko/
      Summer/
        Uniform/
          Smile.png
          Frown.png
      Winter/
        Coat/
          Smile.png
```

In this example the character ID is `Aiko`, the looks are `Summer/Uniform` and `Winter/Coat`, and both looks contain the `Smile` expression. If an expression PNG is placed directly inside `Aiko/`, its look is the root (empty) look; it can be selected automatically when that expression exists only there. Look values must be non-empty, so put expressions in a named look folder if you need to select that look explicitly. Use forward slashes in YAML look paths, even on Windows.

Set a default look and position once at the story root:

```yaml
character_defaults:
  Aiko:
    look: Summer/Uniform
    position: left
```

Then an action can omit `look` and `position`:

```yaml
actions:
  - type: show_character
    name: Aiko
    expression: Smile
```

When an expression exists in more than one look, configure a default look or include `look` in the action. If an expression appears in only one look, the engine can select that look automatically. Character names, looks, and expression stems are matched without regard to letter case when the match is unambiguous. If multiple files collide by case, use exact filename casing.

`speaker` is also used as the active character ID by default. If the speaker is a narrator, or its display name differs from the character folder, set the line’s `active_character` explicitly. Use `active_character: null` to leave every visible portrait dimmed. The character catalog includes both project portraits and any engine portraits.

To browse the discovered assets, run these commands from the project root:

```powershell
.\VN_Engine\engine.exe --list-character-assets
.\VN_Engine\engine.exe --list-character-assets Aiko
.\VN_Engine\engine.exe --list-character-assets Aiko --look Summer/Uniform
```

These optional command-line inventory commands require a separate compiled engine distribution or a source checkout. In the editor package, use the asset hierarchy to browse characters, looks, and expressions. The validator also suggests close matches for missing character references.

## Text formatting and inline asset markers

Dialogue text can contain these paired markers:

| Write | Appearance or action |
| --- | --- |
| `*bold text*` | Bold text |
| `_italic text_` | Italic text |
| `#highlighted text#` | Accent-colored text |
| `~struck text~` | Text with a strike-through |
| `{player_name}` | Insert a story variable’s current value |
| `%station%` | Set the background image to `station` |
| `§door§` | Play the `door` sound effect |

Example:

```yaml
text: "*Wait!* _Look over there._ #The train is here!#"
```

For legacy inline asset markers, put the image or sound name between matching markers in the dialogue text:

```yaml
text: "The doors open. %station% §door§"
```

The marker and name are not printed as dialogue. `%...%` changes the background and `§...§` plays a sound when the line is entered. Explicit `actions` make scene changes easier to see and validate, so prefer them for new stories. Quote text containing `#`, a colon, or other YAML punctuation to avoid the YAML parser treating it as syntax (as shown in the example above).

## Saves and story changes

The engine saves the current dialogue ID, variable values, visible background, music track, visible character states, and dialogue history. A load resumes that dialogue without re-running its entry actions. The save must belong to the same configured story filename, and the dialogue IDs and variables it stores must still exist. If you rename or remove dialogue IDs or variables after making saves, those older saves may no longer load.

Settings and save slots are stored in the user-data folder, not in `data/story.yaml`. Their location and the available project settings are described in [project configuration](./project-config.md#user-data-settings-and-saves).
