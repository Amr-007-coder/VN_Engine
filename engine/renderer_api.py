"""Public hooks for code-authored renderers that extend VN Engine themes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RendererContext:
    """Runtime objects available to custom renderers for one draw call.

    ``engine`` is intentionally exposed as an advanced escape hatch. Plugins
    should prefer the explicit style, theme, assets, and scale fields where
    they are sufficient, and should not retain a render target between frames.
    """

    engine: object
    style: dict
    theme: dict
    assets: object
    ui_scale: float


class RendererPlugin:
    """Base class for optional custom component rendering.

    Override :meth:`render_component`. Return ``True`` after drawing the
    component to take over that component, or return ``False`` to let the
    built-in renderer draw it. Hook names include ``menu``, ``textbox``,
    ``choice``, ``dialogue_control``, ``pause_control``, ``history``,
    ``overlay``, and ``gallery``.
    """

    def render_component(self, context, name, target, rect, state, data):
        return False


def render_component(plugin, engine, name, target, rect, state="normal", data=None):
    """Call a plugin hook and report whether it consumed the component."""

    callback = getattr(plugin, "render_component", None)
    if not callable(callback):
        return False
    context = RendererContext(
        engine=engine,
        style=engine.style,
        theme=engine.theme,
        assets=engine.assets,
        ui_scale=float(engine.settings.values.get("ui_scale", 1.0)),
    )
    return bool(callback(context, name, target, rect, state, data or {}))
