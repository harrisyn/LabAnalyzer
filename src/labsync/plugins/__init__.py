"""Plugins: optional integrations with a particular platform.

LabSync itself only knows generic destinations (REST/JSON, FHIR, HL7 over
MLLP, a folder, DICOM nodes and DICOMweb servers). A plugin adds what one
platform needs on top of that, for example a pairing code, a device key, a
status heartbeat, or a list of imaging devices managed on the platform's side.
Nothing a plugin adds is shown until the plugin is turned on under
Settings > Integrations.

A plugin is a subclass of :class:`Plugin`. Built-in plugins are listed in
``BUILTIN``; third-party packages can add their own through the
``labsync.plugins`` entry point group::

    [project.entry-points."labsync.plugins"]
    myplatform = "myplatform_labsync:MyPlatformPlugin"

Settings for each plugin live under ``config["plugins"][<plugin id>]``, with
``enabled`` (default False) plus whatever the plugin's ``defaults()`` returns.
Fields named in ``secret_fields`` are kept in the operating system's
credential store, like destination passwords.

Nothing in this module imports tkinter; a plugin's settings panel is loaded
only by the desktop app (``settings_panel``).
"""

from __future__ import annotations

import copy
import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("labsync.plugins")

BUILTIN = {"serenity": "labsync.plugins.serenity:SerenityPlugin"}
ENTRY_POINT_GROUP = "labsync.plugins"


@dataclass
class LinkState:
    """What the status bar shows for a plugin's connection."""

    ok: bool | None = None  # None = not checked yet / not set up
    at: float | None = None
    text: str = ""  # short, e.g. "connected (Test Clinic)" or the problem in plain words
    details: dict[str, Any] = field(default_factory=dict)


class Link:
    """A plugin's connection to its platform, polled by the engine (blocking; runs in a worker thread).

    ``check`` sends LabSync's status report and returns the platform's answer, or
    None when it could not be reached. ``remote_nodes`` turns an answer into the
    imaging devices the platform says may send through this computer.
    """

    interval_seconds = 60

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.state = LinkState()

    def check(self, report: dict[str, Any]) -> dict[str, Any] | None:
        return None

    def remote_nodes(self, answer: dict[str, Any]) -> list[dict[str, Any]] | None:
        return None

    def close(self) -> None:
        pass


class Plugin:
    id = ""
    name = ""
    summary = ""  # one line for Settings > Integrations
    # Destination types this plugin adds, {type: label}
    lab_destination_types: dict[str, str] = {}
    imaging_destination_types: dict[str, str] = {}
    secret_fields: tuple[str, ...] = ()

    def defaults(self) -> dict[str, Any]:
        return {}

    def configured(self, settings: dict[str, Any]) -> bool:
        """True once the plugin has what it needs to talk to its platform."""
        return True

    def validate(self, settings: dict[str, Any]) -> list[str]:
        return []

    # lab results
    def new_lab_destination(self, dest_type: str) -> dict[str, Any]:
        return {}

    def make_sender(self, dest: dict[str, Any], settings: dict[str, Any]):
        raise NotImplementedError

    # imaging
    def new_imaging_destination(self, dest_type: str) -> dict[str, Any]:
        return {}

    def make_imaging_destination(self, spec: dict[str, Any], settings: dict[str, Any], imaging_config):
        raise NotImplementedError

    def describe_destination(self, dest: dict[str, Any], settings: dict[str, Any]) -> str:
        return self.name

    # connection to the platform
    def make_link(self, settings: dict[str, Any]) -> Link | None:
        return None

    # desktop app
    def settings_panel(self, parent, settings: dict[str, Any]):
        """Return a ttk widget with ``collect() -> dict`` (the new settings); None for no options."""
        return None


_cache: dict[str, Plugin] | None = None


def _load(target: str) -> Plugin | None:
    module_name, _, attr = target.partition(":")
    try:
        cls = getattr(importlib.import_module(module_name), attr)
        plugin = cls()
        if not plugin.id:
            raise ValueError("plugin has no id")
        return plugin
    except Exception:
        log.exception("could not load plugin %s", target)
        return None


def available() -> dict[str, Plugin]:
    """Every plugin installed: the built-in ones plus entry points."""
    global _cache
    if _cache is None:
        found: dict[str, Plugin] = {}
        for target in BUILTIN.values():
            p = _load(target)
            if p:
                found[p.id] = p
        try:
            from importlib.metadata import entry_points

            for ep in entry_points(group=ENTRY_POINT_GROUP):
                if ep.name in found:
                    continue
                p = _load(ep.value)
                if p:
                    found[p.id] = p
        except Exception:  # pragma: no cover - broken metadata
            log.exception("could not list plugin entry points")
        _cache = found
    return _cache


def get(plugin_id: str) -> Plugin | None:
    return available().get(plugin_id)


def settings_for(cfg: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    plugin = get(plugin_id)
    base = {"enabled": False, **(plugin.defaults() if plugin else {})}
    return {**base, **(((cfg.get("plugins") or {}).get(plugin_id)) or {})}


def is_enabled(cfg: dict[str, Any], plugin_id: str) -> bool:
    return get(plugin_id) is not None and bool(settings_for(cfg, plugin_id).get("enabled"))


def enabled(cfg: dict[str, Any]) -> list[tuple[Plugin, dict[str, Any]]]:
    return [(p, settings_for(cfg, pid)) for pid, p in available().items() if is_enabled(cfg, pid)]


def default_plugin_settings() -> dict[str, dict[str, Any]]:
    return {pid: {"enabled": False, **p.defaults()} for pid, p in available().items()}


def _owner(cfg: dict[str, Any], dest_type: str, attr: str, only_enabled: bool) -> tuple[Plugin, dict[str, Any]] | None:
    for pid, p in available().items():
        if dest_type in getattr(p, attr) and (not only_enabled or is_enabled(cfg, pid)):
            return p, settings_for(cfg, pid)
    return None


def lab_destination_owner(cfg: dict[str, Any], dest_type: str, only_enabled: bool = True):
    return _owner(cfg, dest_type, "lab_destination_types", only_enabled)


def imaging_destination_owner(cfg: dict[str, Any], dest_type: str, only_enabled: bool = True):
    return _owner(cfg, dest_type, "imaging_destination_types", only_enabled)


def lab_destination_types(cfg: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p, _ in enabled(cfg):
        out.update(p.lab_destination_types)
    return out


def imaging_destination_types(cfg: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p, _ in enabled(cfg):
        out.update(p.imaging_destination_types)
    return out


def secret_slots(cfg: dict[str, Any]):
    """(container, field, keyring key) for every plugin secret present in ``cfg``."""
    for pid, settings in (cfg.get("plugins") or {}).items():
        plugin = get(pid)
        if plugin is None or not isinstance(settings, dict):
            continue
        for f in plugin.secret_fields:
            if f in settings:
                yield settings, f, f"{pid}:{f}"


def copy_settings(cfg: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    return copy.deepcopy(settings_for(cfg, plugin_id))
