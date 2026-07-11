"""Tool registry with auto-discovery.

Tools self-register by subclassing Tool. The registry discovers all subclasses
on first use. Lookup is by name; the agent queries by name or fetches all
schemas.

Adding a tool = creating a Tool subclass in this package. The agent never
changes. See ARCHITECTURE.md §5.
"""

from __future__ import annotations

import importlib
import pkgutil
import threading
from typing import Any, Iterable

from paios.tools.base import Tool


class ToolRegistry:
    """Holds instances of every discovered Tool subclass."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._discovered = False
        self._lock = threading.Lock()

    def discover(self) -> None:
        """Import every module in paios.tools and register every Tool subclass.

        Tool subclasses are instantiated with no args and registered by name.
        Uses threading.Lock to prevent duplicate lazy-init races.
        """
        if self._discovered:
            return
        with self._lock:
            if self._discovered:
                return
            from paios.tools.base import Tool

            import paios.tools as tools_pkg

            for module_info in pkgutil.iter_modules(tools_pkg.__path__):
                if module_info.name in {"base", "registry", "__init__"}:
                    continue
                module = importlib.import_module(f"paios.tools.{module_info.name}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Tool)
                        and attr is not Tool
                        and attr.__module__ == module.__name__
                        and getattr(attr, "name", "")
                    ):
                        instance = attr()
                        self.register(instance)
            self._discovered = True

    def register(self, tool: Tool) -> None:
        """Manually register a tool instance."""
        if not tool.name:
            raise ValueError(f"tool {type(tool).__name__} has no name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name, discovering first if needed."""
        self.discover()
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        self.discover()
        return list(self._tools.values())

    def names(self) -> list[str]:
        self.discover()
        return sorted(self._tools.keys())

    def schemas_for(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """JSON-Schema descriptions for the LLM.

        If names is None, returns all. Unknown names are skipped.
        """
        self.discover()
        if names is None:
            tools = list(self._tools.values())
        else:
            tools = [self._tools[n] for n in names if n in self._tools]
        return [type(t).schema_for_llm() for t in tools]


# Process-wide registry.
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    """Test helper: a fresh registry forces re-discovery."""
    global _registry
    _registry = ToolRegistry()
