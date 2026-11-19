"""Small declarative layout engine for theme-defined runtime screens."""

from copy import deepcopy


def _merge(base, override):
    result = deepcopy(base)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _ratio(value, total, fallback=0, scale=1.0):
    if isinstance(value, str) and value.strip().endswith("%"):
        try:
            return round(float(value.strip()[:-1]) * total / 100)
        except ValueError:
            return fallback
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value * scale)
    return fallback


def select_profile(layouts, viewport):
    """Select the last matching responsive profile, if any."""
    width, height = viewport
    aspect = width / max(1, height)
    selected = None
    for profile in layouts.get("profiles", []):
        if not isinstance(profile, dict):
            continue
        when = profile.get("when", {})
        if not isinstance(when, dict):
            continue
        if width < when.get("min_width", 0) or width > when.get("max_width", float("inf")):
            continue
        if aspect < when.get("min_aspect", 0) or aspect > when.get("max_aspect", float("inf")):
            continue
        selected = profile
    return selected


def _profile_layouts(layouts, viewport):
    profile = select_profile(layouts, viewport)
    result = deepcopy(layouts)
    if profile:
        result = _merge(result, {key: value for key, value in profile.items() if key != "when"})
    return result


def safe_area_rect(layouts, viewport):
    width, height = viewport
    selected = _profile_layouts(layouts, viewport)
    insets = selected.get("safe_area", {})
    if not isinstance(insets, dict):
        insets = {}
    left = max(0, _ratio(insets.get("left", 0), width))
    right = max(0, _ratio(insets.get("right", 0), width))
    top = max(0, _ratio(insets.get("top", 0), height))
    bottom = max(0, _ratio(insets.get("bottom", 0), height))
    return (left, top, max(1, width - left - right), max(1, height - top - bottom))


def screen_layout(layouts, screen_name, viewport):
    selected = _profile_layouts(layouts, viewport)
    screens = selected.get("screens", {})
    result = screens.get(screen_name, {}) if isinstance(screens, dict) else {}
    return result if isinstance(result, dict) else {}


def component_layout(layouts, screen_name, component_name, viewport):
    screen = screen_layout(layouts, screen_name, viewport)
    components = screen.get("components", {})
    result = components.get(component_name, {}) if isinstance(components, dict) else {}
    return result if isinstance(result, dict) else {}


def resolve_rect(spec, bounds, default=None, scale=1.0):
    """Resolve an anchored rectangle. Lengths accept design pixels or percentages."""
    bx, by, bw, bh = map(int, bounds)
    if not isinstance(spec, dict):
        return tuple(default or bounds)
    width = max(1, _ratio(spec.get("width", "100%"), bw, bw, scale))
    height = max(1, _ratio(spec.get("height", "100%"), bh, bh, scale))
    constraints = spec.get("constraints", {})
    if isinstance(constraints, dict):
        min_width = _ratio(constraints.get("min_width", 1), bw, 1, scale)
        max_width = _ratio(constraints.get("max_width", bw), bw, bw, scale)
        min_height = _ratio(constraints.get("min_height", 1), bh, 1, scale)
        max_height = _ratio(constraints.get("max_height", bh), bh, bh, scale)
        width = min(max_width, max(min_width, width))
        height = min(max_height, max(min_height, height))
    width, height = min(width, bw), min(height, bh)
    anchor = str(spec.get("anchor", "top_left")).replace("-", "_").casefold()
    anchor_points = {
        "top_left": ("left", "top"), "top_center": ("center", "top"),
        "top_right": ("right", "top"), "center_left": ("left", "center"),
        "center": ("center", "center"), "center_right": ("right", "center"),
        "bottom_left": ("left", "bottom"), "bottom_center": ("center", "bottom"),
        "bottom_right": ("right", "bottom"),
    }
    horizontal, vertical = anchor_points.get(anchor, ("left", "top"))
    if anchor in {"top", "bottom"}:
        horizontal, vertical = "center", anchor
    elif anchor in {"left", "right"}:
        horizontal, vertical = anchor, "center"
    x_offset = _ratio(spec.get("x", spec.get("left", 0)), bw, scale=scale)
    y_offset = _ratio(spec.get("y", spec.get("top", 0)), bh, scale=scale)
    if "right" in spec:
        right = _ratio(spec["right"], bw, scale=scale)
        x = bx + bw - right - width
    elif horizontal == "center":
        x = bx + (bw - width) // 2 + x_offset
    elif horizontal == "right":
        x = bx + bw - width - x_offset
    else:
        x = bx + x_offset
    if "bottom" in spec:
        bottom = _ratio(spec["bottom"], bh, scale=scale)
        y = by + bh - bottom - height
    elif vertical == "center":
        y = by + (bh - height) // 2 + y_offset
    elif vertical == "bottom":
        y = by + bh - height - y_offset
    else:
        y = by + y_offset
    return (int(x), int(y), int(width), int(height))


def _content_bounds(spec, bounds, scale):
    rect = resolve_rect(spec, bounds, bounds, scale)
    x, y, width, height = rect
    padding = spec.get("padding", 0) if isinstance(spec, dict) else 0
    if isinstance(padding, dict):
        left = _ratio(padding.get("left", 0), width, scale=scale)
        right = _ratio(padding.get("right", 0), width, scale=scale)
        top = _ratio(padding.get("top", 0), height, scale=scale)
        bottom = _ratio(padding.get("bottom", 0), height, scale=scale)
    else:
        left = right = top = bottom = max(0, _ratio(padding, min(width, height), scale=scale))
    return (x + left, y + top, max(1, width - left - right), max(1, height - top - bottom))


def layout_children(spec, bounds, count, item_sizes=None, scale=1.0):
    """Lay out uniform flex or grid children inside an anchored region."""
    if count <= 0:
        return []
    spec = spec if isinstance(spec, dict) else {}
    x, y, width, height = _content_bounds(spec, bounds, scale)
    kind = spec.get("type", "flex")
    gap = max(0, _ratio(spec.get("gap", 0), width if spec.get("direction") == "row" else height, scale=scale))
    if kind == "grid":
        columns = max(1, int(spec.get("columns", 1)))
        rows = max(1, int(spec.get("rows", 1)), (count + columns - 1) // columns)
        gap_x = max(0, _ratio(spec.get("column_gap", spec.get("gap", 0)), width, scale=scale))
        gap_y = max(0, _ratio(spec.get("row_gap", spec.get("gap", 0)), height, scale=scale))
        cell_width = max(1, (width - gap_x * (columns - 1)) // columns)
        cell_height = max(1, (height - gap_y * (rows - 1)) // rows)
        return [
            (x + (index % columns) * (cell_width + gap_x),
             y + (index // columns) * (cell_height + gap_y),
             cell_width, cell_height)
            for index in range(count)
        ]

    direction = spec.get("direction", "column")
    row = direction == "row"
    main_size = width if row else height
    cross_size = height if row else width
    requested = item_sizes if item_sizes is not None else spec.get("item_size")
    if isinstance(requested, list):
        sizes = [max(1, _ratio(requested[min(i, len(requested) - 1)], main_size, scale=scale)) for i in range(count)] if requested else []
    elif requested is not None:
        size = max(1, _ratio(requested, main_size, scale=scale))
        sizes = [size] * count
    else:
        size = max(1, (main_size - gap * (count - 1)) // count)
        sizes = [size] * count
    minimum = max(1, _ratio(spec.get("min_item_size", 1), main_size, 1, scale))
    maximum = max(minimum, _ratio(spec.get("max_item_size", main_size), main_size, main_size, scale))
    sizes = [max(minimum, min(maximum, size)) for size in sizes]
    total = sum(sizes) + gap * (count - 1)
    if total > main_size:
        available = max(count, main_size - gap * (count - 1))
        sizes = [max(1, available // count)] * count
        sizes[-1] = max(1, available - sum(sizes[:-1]))
        total = sum(sizes) + gap * (count - 1)
    justify = spec.get("justify", "center")
    distributed_gap = gap
    if justify == "end":
        cursor = main_size - total
    elif justify == "start" or total >= main_size:
        cursor = 0
    elif justify == "space_between" and count > 1:
        cursor = 0
        distributed_gap += (main_size - total) // (count - 1)
    elif justify in {"space_around", "space_evenly"}:
        slots = count if justify == "space_around" else count + 1
        extra = max(0, (main_size - total) // slots)
        distributed_gap += extra
        cursor = extra // 2 if justify == "space_around" else extra
    else:
        cursor = (main_size - total) // 2
    align = spec.get("align", "stretch")
    result = []
    for size in sizes:
        cross = cross_size
        if align == "center":
            cross = min(cross_size, _ratio(spec.get("cross_size", cross_size), cross_size, cross_size, scale))
            cross_offset = (cross_size - cross) // 2
        elif align == "end":
            cross = min(cross_size, _ratio(spec.get("cross_size", cross_size), cross_size, cross_size, scale))
            cross_offset = cross_size - cross
        else:
            cross_offset = 0
        if row:
            result.append((x + cursor, y + cross_offset, size, cross))
        else:
            result.append((x + cross_offset, y + cursor, cross, size))
        cursor += size + distributed_gap
    return result

