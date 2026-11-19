# Custom renderer API

The built-in renderer is controlled by portable, data-only `style.json` themes. For a game's unique visual behavior, an advanced Python launcher can pass a `RendererPlugin` to `Engine`. This hook runs in the game's process and is developer code; it is not loaded from `.vnstyle` presets or player-installed data packages.

```python
from engine.engine import Engine
from engine.renderer_api import RendererPlugin


class MyRenderer(RendererPlugin):
    def render_component(self, context, name, target, rect, state, data):
        if name != "choice":
            return False  # Keep the built-in renderer for other components.

        color = (65, 45, 82) if state in {"focus", "hover", "selected"} else (18, 18, 29)
        target.fill(color, rect)
        label = data.get("label", "")
        font = context.assets.load_font("standard.ttf", 22)
        text = font.render(str(label), True, (245, 240, 230))
        target.blit(text, text.get_rect(center=rect.center))
        return True  # The custom renderer drew and consumed this component.


Engine(renderer_plugin=MyRenderer()).run()
```

`render_component(context, name, target, rect, state, data)` is called while a component is being drawn:

- `context.style` is the currently active style, including the selected creator variant. `context.theme` is the resolved legacy theme tree.
- `context.assets` loads project and built-in images, sounds, and fonts. `context.ui_scale` is the current UI scale.
- `target` is the Pygame surface to draw onto; `rect` is the component's Pygame rectangle.
- `state` is typically `normal`, `hover`, `focus`, `pressed`, `disabled`, or `selected`.
- `data` supplies the component's runtime content. It can include engine objects; treat those as read-only and do not keep the target surface beyond the current call.
- Return `True` only after drawing the full component. Return `False` to let the built-in renderer handle it.

Current hook names are `menu`, `textbox`, `choice`, `dialogue_control`, `pause_control`, `history`, `overlay`, and `gallery`. Menu hooks receive the active menu and mode. Overlay hooks include a `kind` such as `confirmation`, `save_name`, `story_input`, or `variable_inspector`. The gallery hook receives the viewer mode and image surface.

Renderer code is coupled to the engine's Python API and should be versioned with the runtime that uses it. Use style layouts and skins for ordinary theme changes so themes remain editable in the visual theme editor and portable across supported runtime templates.
