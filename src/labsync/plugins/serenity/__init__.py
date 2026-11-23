"""Serenity plugin: pair this computer with a Serenity organisation.

When turned on it adds
- a setup code (pairing) and a device key, kept in the credential store,
- a "Serenity" destination for lab results and one for images,
- a status heartbeat, and the imaging devices registered in Serenity to send
  through this computer (kept on disk, so it works offline).
"""

from __future__ import annotations

from typing import Any

from .. import Plugin
from .link import HEARTBEAT_SECONDS, NAME, SerenityLink, is_configured

LAB_TYPE = "serenity"
IMAGING_TYPE = "serenity"


class SerenityPlugin(Plugin):
    id = "serenity"
    name = NAME
    summary = "Pair with a Serenity organisation: results and images go to Serenity with this computer's device key."
    lab_destination_types = {LAB_TYPE: NAME}
    imaging_destination_types = {IMAGING_TYPE: NAME}
    secret_fields = ("device_key",)

    def defaults(self) -> dict[str, Any]:
        return {
            "url": "",  # the platform's API address, including its version prefix
            "device_key": "",  # sdk_...; kept in the OS credential store
            "device_id": "",
            "device_name": "",
            "organization": "",
            "ca_bundle": "",  # optional CA bundle for HTTPS-inspecting proxies
            "heartbeat_seconds": HEARTBEAT_SECONDS,
        }

    def configured(self, settings: dict[str, Any]) -> bool:
        return is_configured(settings)

    def validate(self, settings: dict[str, Any]) -> list[str]:
        if settings.get("enabled") and not settings.get("url"):
            return [f"{NAME}: enter the setup code from {NAME}'s Devices screen (Settings > Integrations)"]
        return []

    def new_lab_destination(self, dest_type: str) -> dict[str, Any]:
        return {"name": NAME, "timeout": 30}

    def make_sender(self, dest: dict[str, Any], settings: dict[str, Any]):
        from .sender import SerenitySender

        return SerenitySender(dest, settings)

    def new_imaging_destination(self, dest_type: str) -> dict[str, Any]:
        return {"name": NAME}

    def make_imaging_destination(self, spec: dict[str, Any], settings: dict[str, Any], imaging_config):
        from .imaging import SerenityDestination

        return SerenityDestination(spec, settings, imaging_config)

    def describe_destination(self, dest: dict[str, Any], settings: dict[str, Any]) -> str:
        org = settings.get("organization")
        return f"{NAME} ({org})" if org else f"{NAME} device gateway"

    def make_link(self, settings: dict[str, Any]) -> SerenityLink:
        return SerenityLink(settings)

    def settings_panel(self, parent, settings: dict[str, Any]):
        from .gui import SerenityPanel

        return SerenityPanel(parent, settings)
