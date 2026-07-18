"""Example plugin demonstrating the Veyron Plugin SDK.

Provides a simple 'hello_world' tool and a 'greet' command.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from veyron.plugin.sdk import PluginBase, PluginManifest
from veyron.security.command_policy import PermissionLevel
from veyron.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)


class HelloWorldInputs(BaseModel):
    name: str = Field(default="World", description="Name to greet")


class HelloWorldTool(Tool):
    """A simple greeting tool provided as an example plugin."""

    name: str = "hello_world"
    description: str = "Greet someone — example plugin tool"
    permission: PermissionLevel = PermissionLevel.FREE
    Inputs: type[BaseModel] = HelloWorldInputs

    async def run(self, ctx: ToolContext, **inputs: Any) -> ToolResult:
        name = inputs.get("name", "World")
        return ToolResult(
            ok=True,
            output=f"Hello, {name}! This is an example plugin tool.",
            data={"greeting": f"Hello, {name}!"},
        )


class ExamplePlugin(PluginBase):
    """Example Veyron plugin demonstrating the SDK."""

    manifest = PluginManifest(
        name="example_plugin",
        version="1.0.0",
        description="Example plugin demonstrating the Veyron Plugin SDK",
        author="Veyron Team",
        entry_point="example_tool_plugin.py",
        min_veyron_version="1.0.0",
    )

    async def initialize(self) -> bool:
        """Register the hello_world tool and greet command."""
        self.register_tool(HelloWorldTool)
        self.register_command(
            name="greet",
            handler="hello_world",
            description="Greet someone using the hello_world tool",
        )
        self.set_setting("default_name", "World")
        logger.info("ExamplePlugin initialized")
        return True

    async def shutdown(self) -> None:
        logger.info("ExamplePlugin shut down")
