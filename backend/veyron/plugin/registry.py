"""Plugin registry — manages plugin lifecycle, discovery, and isolation."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import select

from veyron.db.base import sync_session_scope
from veyron.db.models import PluginRegistration
from veyron.plugin.sdk import PluginBase, PluginManifest

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).resolve().parent.parent.parent / "plugins"


def _utcnow() -> datetime:
    """Return a naive datetime in UTC, matching SQLite storage format."""
    return datetime.now(UTC).replace(tzinfo=None)


class PluginRegistry:
    """Manages plugin lifecycle: discovery, load, unload, isolation."""

    def __init__(self) -> None:
        self._plugins: dict[str, PluginBase] = {}
        self._lock = threading.Lock()

    def discover(self) -> list[PluginManifest]:
        """Scan the plugins directory and return available manifests."""
        if not PLUGINS_DIR.exists():
            return []
        manifests: list[PluginManifest] = []
        for entry in sorted(PLUGINS_DIR.iterdir()):
            if entry.is_dir() and (entry / "__init__.py").exists():
                manifest = self._load_manifest(entry)
                if manifest:
                    manifests.append(manifest)
            elif entry.suffix == ".py" and entry.stem != "__init__":
                manifest = self._load_manifest_from_file(entry)
                if manifest:
                    manifests.append(manifest)
        return manifests

    async def load_plugin(self, name: str) -> PluginBase | None:
        """Load a plugin by name."""
        with self._lock:
            if name in self._plugins:
                return self._plugins[name]

            plugin_path = PLUGINS_DIR / f"{name}.py"
            if not plugin_path.exists():
                plugin_path = PLUGINS_DIR / name / "__init__.py"
                if not plugin_path.exists():
                    logger.warning("plugin not found: %s", name)
                    return None

            try:
                spec = importlib.util.spec_from_file_location(
                    f"veyron_plugin_{name}", str(plugin_path)
                )
                if spec is None or spec.loader is None:
                    return None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                plugin_instance = self._find_plugin_class(module)
                if plugin_instance is None:
                    logger.warning("no PluginBase subclass found in %s", name)
                    return None

                ok = await plugin_instance.initialize()
                if not ok:
                    logger.warning("plugin %s failed to initialize", name)
                    return None

                self._plugins[name] = plugin_instance
                self._persist_registration(plugin_instance)
                logger.info(
                    "plugin loaded: %s v%s",
                    name,
                    plugin_instance.manifest.version,
                )
                return plugin_instance
            except Exception as e:
                logger.error("failed to load plugin %s: %s", name, e)
                return None

    def unload_plugin(self, name: str) -> bool:
        """Unload a previously loaded plugin by name."""
        with self._lock:
            plugin = self._plugins.pop(name, None)
            if plugin is None:
                return False
            try:
                try:
                    asyncio.get_running_loop().create_task(plugin.shutdown())
                except RuntimeError:
                    pass
            except Exception as e:
                logger.warning("plugin %s shutdown error: %s", name, e)
            logger.info("plugin unloaded: %s", name)
            return True

    def get_plugin(self, name: str) -> PluginBase | None:
        """Return a loaded plugin instance by name, or None."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return summary metadata for all loaded plugins."""
        return [
            {
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "author": p.manifest.author,
                "tool_count": len(p.get_tools()),
                "command_count": len(p.get_commands()),
            }
            for p in self._plugins.values()
        ]

    def get_tools_from_plugins(self) -> list[type]:
        """Aggregate all Tool classes registered by loaded plugins."""
        tools: list[type] = []
        for plugin in self._plugins.values():
            tools.extend(plugin.get_tools())
        return tools

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_manifest(self, plugin_dir: Path) -> PluginManifest | None:
        """Load and return the manifest from a directory-based plugin."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"veyron_plugin_{plugin_dir.name}",
                plugin_dir / "__init__.py",
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return self._find_manifest(module)
        except Exception:
            return None

    def _load_manifest_from_file(
        self, plugin_file: Path
    ) -> PluginManifest | None:
        """Load and return the manifest from a single-file plugin."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"veyron_plugin_{plugin_file.stem}", str(plugin_file)
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return self._find_manifest(module)
        except Exception:
            return None

    def _find_manifest(self, module) -> PluginManifest | None:
        """Search module for a PluginBase subclass with a named manifest."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if not (isinstance(attr, type) and issubclass(attr, PluginBase)):
                continue
            if attr is PluginBase:
                continue
            manifest: PluginManifest | None = getattr(attr, "manifest", None)
            if isinstance(manifest, PluginManifest) and manifest.name:
                return manifest
        return None

    def _find_plugin_class(self, module) -> PluginBase | None:
        """Search module for a PluginBase subclass, instantiate it."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name, None)
            if not (isinstance(attr, type) and issubclass(attr, PluginBase)):
                continue
            if attr is PluginBase:
                continue
            try:
                return attr()
            except Exception as e:
                logger.warning(
                    "failed to instantiate plugin class %s: %s", attr_name, e
                )
                return None
        return None

    def _persist_registration(self, plugin: PluginBase) -> None:
        """Upsert a PluginRegistration row for the given plugin."""
        try:
            with sync_session_scope() as session:
                existing = session.exec(
                    select(PluginRegistration).where(
                        PluginRegistration.name == plugin.manifest.name
                    )
                ).first()
                if existing:
                    existing.version = plugin.manifest.version
                    existing.updated_at = _utcnow()
                    session.add(existing)
                    return
                reg = PluginRegistration(
                    name=plugin.manifest.name,
                    version=plugin.manifest.version,
                    description=plugin.manifest.description,
                    author=plugin.manifest.author,
                    entry_point=plugin.manifest.entry_point,
                    tool_names=json.dumps(
                        [t.__name__ for t in plugin.get_tools()]
                    ),
                    command_names=json.dumps(
                        [c["name"] for c in plugin.get_commands()]
                    ),
                    enabled=True,
                )
                session.add(reg)
        except Exception as e:
            logger.warning(
                "failed to persist plugin registration: %s", e
            )

    def get_registered_plugins(self) -> list[PluginRegistration]:
        """Return all persisted plugin registrations, ordered by name."""
        with sync_session_scope() as session:
            return session.exec(
                select(PluginRegistration).order_by(PluginRegistration.name)
            ).all()


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_registry: PluginRegistry | None = None


def get_plugin_registry() -> PluginRegistry:
    """Return the process-wide PluginRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


def reset_plugin_registry() -> None:
    """Test helper: clear the cached registry singleton."""
    global _registry
    _registry = None
