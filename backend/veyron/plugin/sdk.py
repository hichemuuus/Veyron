"""Plugin SDK — base classes for external Veyron plugins."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from veyron.tools.base import Tool

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Plugin metadata descriptor."""

    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    entry_point: str = ""
    min_veyron_version: str = "1.0.0"


class PluginBase(ABC):
    """Base class all Veyron plugins must subclass.

    Subclasses define:
      - manifest (class variable)
      - register() to provide tools, commands, workflows
    """

    manifest: PluginManifest = PluginManifest(name="", version="0.0.0")

    def __init__(self) -> None:
        self._tools: list[type[Tool]] = []
        self._commands: list[dict[str, Any]] = []
        self._workflows: list[dict[str, Any]] = []
        self._settings: dict[str, Any] = {}

    @abstractmethod
    async def initialize(self) -> bool:
        """Called when the plugin is loaded. Return False to indicate failure."""
        ...

    async def shutdown(self) -> None:
        """Called when the plugin is unloaded."""
        ...

    def register_tool(self, tool_cls: type[Tool]) -> None:
        """Register a Tool subclass provided by this plugin."""
        if not issubclass(tool_cls, Tool):
            raise TypeError(f"{tool_cls.__name__} is not a Tool subclass")
        self._tools.append(tool_cls)

    def register_command(
        self, name: str, handler: str, description: str = ""
    ) -> None:
        """Register a custom command."""
        self._commands.append(
            {"name": name, "handler": handler, "description": description}
        )

    def register_workflow(
        self, name: str, definition: dict[str, Any]
    ) -> None:
        """Register a workflow definition."""
        self._workflows.append({"name": name, "definition": definition})

    def get_tools(self) -> list[type[Tool]]:
        return list(self._tools)

    def get_commands(self) -> list[dict[str, Any]]:
        return list(self._commands)

    def get_workflows(self) -> list[dict[str, Any]]:
        return list(self._workflows)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def get_all_settings(self) -> dict[str, Any]:
        return dict(self._settings)
