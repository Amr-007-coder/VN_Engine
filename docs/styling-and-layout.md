# Styling and responsive layout

`data/style.json` controls the game's visual presentation independently of `data/project.json`. It supports the built-in declarative renderer: colors, typography, component spacing and geometry, responsive screen layouts, image skins, and named theme variants. It does not execute code or bundle assets. Keep referenced images and fonts under the project's `assets/` folder.

Creators can edit common properties without hand-editing JSON in **Project > Visual Theme Editor**. Choose a screen, preview size, component, and control state. Click a component to select it, drag it to reposition it, or edit its properties in the inspector. The preview includes desktop, tablet, and mobile portrait sizes. Use **Apply to style.json** to keep the changes. **Project > Export Theme Preset** saves a `.vnstyle` JSON preset; **Import Theme Preset** merges its style into the open project. The preset carries style data, while image and font assets remain normal project assets.

## Component styles

Component settings live under `components`. Each component can define its own fonts, font sizes, colors, padding, border, radius, opacity, and image fit. For example:

```json
{
  "schema_version": 1,
  "components": {
    "textbox": {
      "background_image": "images/frame.png",
      "fit": "stretch",
      "nine_slice": { "left": 32, "right": 32, "top": 24, "bottom": 24 },
      "background_color": [12, 16, 29, 220],
      "opacity": 0.95,
      "border_color": [115, 94, 129],
      "border_width": 2,
      "radius": 12,
      "padding": 18
    },
    "dialogue_text": {
      "text": { "font": "fonts/story.ttf", "font_size": 25, "color": [244, 239, 224] },
      "speaker": { "font": "fonts/title.ttf", "font_size": 30, "color": [255, 190, 125] }
    }
  }
}
```

Use RGB or RGBA arrays for colors. `opacity` ranges from `0.0` to `1.0`. Image fit modes are `stretch`, `contain`, and `cover`. Set `nine_slice` to preserve the image's corners while stretching its middle; it can be one integer for equal edges, or an object with `left`, `right`, `top`, and `bottom` edge widths in source-image pixels. Button-like components support `normal`, `hover`, `focus`, `pressed`, `disabled`, and `selected` states. Each state may specify a fill color, image, border, or opacity; missing states fall back to a nearby state and then to the normal appearance.

The `intro_cards` component controls the opening logo, creator credit, and content notice presentation, including colors, font sizes, timing, image bounds, and star effects. Their text and images still come from `project.json` and `style.json`'s `intro` fields.

## Responsive layout

Layouts live under `layouts.screens.<screen>.components.<component>`. Lengths accept design pixels or percentages of the containing safe area. Anchors are `top_left`, `top_center`, `top_right`, `center_left`, `center`, `center_right`, `bottom_left`, `bottom_center`, and `bottom_right`. Optional `constraints` clamp the resolved width or height. Child groups can use `flex` or `grid` layouts.

```json
{
  "layouts": {
    "safe_area": { "top": 0, "right": 0, "bottom": 0, "left": 0 },
    "screens": {
      "dialogue": {
        "components": {
          "textbox": { "anchor": "bottom_left", "x": "2%", "bottom": 0, "width": "96%", "height": "24%" },
          "choices": {
            "anchor": "top_center", "width": "88%", "height": "62%",
            "type": "flex", "direction": "column", "item_size": 56, "gap": 12,
            "justify": "center", "align": "stretch"
          }
        }
      },
      "save_slots": {
        "components": {
          "items": { "anchor": "top_center", "y": "8%", "width": "90%", "height": "72%", "type": "grid", "columns": 2, "gap": 12 }
        }
      }
    }
  }
}
```

The built-in layouts cover dialogue, choices, menus, history, save slots, overlays, and the CG viewer. Add entries under `layouts.profiles` to override layouts and safe-area insets for viewport ranges. A profile has a `name`, optional `when` rules (`min_width`, `max_width`, `min_aspect`, and `max_aspect`), and `screens`/`safe_area` overrides. The built-in `mobile_portrait` and `compact_landscape` profiles are examples. Percentages are resolved against the available safe area; design-pixel offsets and item sizes scale with the player's UI Size setting.

## Creator themes and player preferences

The base creator theme and its supported variants are stored in `style.json`. Variants go under `variants` and contain only the component or layout values they override:

```json
{
  "variants": {
    "night": {
      "label": "Night",
      "components": { "dialogue_text": { "text": { "color": [220, 230, 255] } } }
    }
  }
}
```

When variants exist, the game exposes them as a player **Theme** setting. The chosen variant and personal accessibility preferences (font scaling, high contrast, reduced motion, and UI size) live in the player's user data, not in `style.json`; changing player preferences does not rewrite the creator's theme.

## Extending the renderer

Data-only styles are portable and work with the built-in renderer. A game that needs a unique drawing path can use the advanced Python renderer hook. It requires a custom runtime launcher and renderer code; `.vnstyle` presets remain data-only. See the [renderer API](./renderer-api.md) for hook names and a minimal example.
