from copy import deepcopy


class Menu:
    """Menu data and navigation state, independent of its visual renderer."""

    def __init__(self, title: str, items=None, kind: str = "menu"):
        self.title = title
        self.kind = kind
        self.items = []
        self.selected = 0
        self.row_rects = []
        self.set_items(items or [])

    @property
    def selected_item(self):
        if not self.items:
            return None
        return self.items[self.selected]

    def set_items(self, items, title: str | None = None):
        self.items = [self._normalize_item(item) for item in items]
        if title is not None:
            self.title = title
        self.selected = min(self.selected, max(0, len(self.items) - 1))

    def move(self, offset: int) -> bool:
        if not self.items:
            return False
        old_selection = self.selected
        self.selected = (self.selected + offset) % len(self.items)
        return self.selected != old_selection

    def select_at(self, position):
        for index, rect in enumerate(self.row_rects):
            if rect.collidepoint(position):
                self.selected = index
                return index
        return None

    @staticmethod
    def _normalize_item(item):
        if isinstance(item, str):
            return {"label": item, "action": ""}
        if isinstance(item, (tuple, list)) and len(item) == 2:
            return {"label": str(item[0]), "detail": str(item[1]), "action": ""}
        if isinstance(item, dict):
            normalized = deepcopy(item)
            if not isinstance(normalized.get("label"), str):
                raise ValueError("Menu item must have a text 'label'.")
            if not isinstance(normalized.get("action", ""), str):
                raise ValueError("Menu item action must be a stable string ID.")
            return normalized
        raise ValueError("Menu items must be objects with labels and action IDs.")
