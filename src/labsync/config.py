"""Application configuration: load, validate, migrate and save.

The file is plain JSON so it can be provisioned by IT tooling. Credentials
(API keys, tokens, passwords, client secrets) are kept in the operating
system's credential store (Windows Credential Manager, macOS Keychain, Secret
Service on Linux) whenever one is available; the JSON then only holds a
``"__keyring__"`` marker.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any

from croniter import croniter

from .devices.catalog import LEGACY_ANALYZER_NAMES, find_profile

log = logging.getLogger("labsync.config")

CONFIG_VERSION = 2
KEYRING_MARKER = "__keyring__"
KEYRING_SERVICE = "LabSync"
SECRET_FIELDS = ("api_key", "token", "password", "client_secret")

TRANSPORT_TYPES = ("tcp_server", "tcp_client", "serial")
DESTINATION_TYPES = ("http", "fhir", "hl7_mllp", "file")
SCHEDULE_MODES = ("realtime", "interval", "cron")
AUTH_METHODS = ("none", "api_key", "bearer", "basic", "oauth2")


def default_config() -> dict[str, Any]:
    return {
        "config_version": CONFIG_VERSION,
        "instance_id": f"LABSYNC-{socket.gethostname()[:20].upper()}",
        "app_name": "LabSync",
        "auto_start": True,
        "start_minimized": False,
        "minimize_to_tray": True,
        "check_updates": True,
        "log_level": "INFO",
        "retention_days": 0,
        "theme": "light",
        "devices": [],
        "destinations": [],
        "orders": {"provider": "none", "url": "", "timeout": 10, "auth": {"method": "none"}},
    }


def new_device(profile_id: str = "generic_astm", name: str = "", port: int = 5000) -> dict[str, Any]:
    profile = find_profile(profile_id)
    transport: dict[str, Any] = {"type": "tcp_server", "host": "0.0.0.0", "port": port}
    if profile and profile.transport == "serial":
        transport = {"type": "serial", "port": "COM1" if os.name == "nt" else "/dev/ttyUSB0", **profile.serial}
    return {
        "id": f"dev-{uuid.uuid4().hex[:8]}",
        "name": name or (profile.label if profile else "Analyzer"),
        "profile": profile_id,
        "enabled": True,
        "transport": transport,
        "options": {},
    }


def new_destination(dest_type: str = "http", name: str = "") -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": f"dst-{uuid.uuid4().hex[:8]}",
        "name": name or {"http": "REST endpoint", "fhir": "FHIR server", "hl7_mllp": "LIS (HL7)", "file": "Export folder"}[dest_type],
        "type": dest_type,
        "enabled": True,
        "schedule": {"mode": "realtime", "interval_minutes": 15, "cron": "0 * * * *"},
        "devices": [],
        "include_qc": False,
        "max_attempts": 0,
    }
    if dest_type == "http":
        base.update({"url": "", "method": "POST", "payload_format": "labsync", "timeout": 30, "verify_tls": True,
                     "ca_bundle": "", "headers": {}, "batch_size": 1, "include_attachments": False,
                     "auth": {"method": "none"}})
    elif dest_type == "fhir":
        base.update({"url": "", "timeout": 30, "verify_tls": True, "ca_bundle": "", "headers": {},
                     "auth": {"method": "none"}})
    elif dest_type == "hl7_mllp":
        base.update({"host": "", "port": 2575, "timeout": 30, "hl7_version": "2.5.1", "receiving_app": "",
                     "receiving_facility": "", "sending_facility": ""})
    elif dest_type == "file":
        base.update({"folder": "", "format": "json"})
    return base


class ConfigError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


class SecretStore:
    def __init__(self, enabled: bool = True):
        self._kr = None
        if enabled and not os.environ.get("LABSYNC_NO_KEYRING"):
            try:
                import keyring
                from keyring.backends import fail

                backend = keyring.get_keyring()
                if not isinstance(backend, fail.Keyring) and "null" not in type(backend).__name__.lower():
                    self._kr = keyring
            except Exception:  # pragma: no cover - depends on the OS
                self._kr = None

    @property
    def available(self) -> bool:
        return self._kr is not None

    def get(self, key: str) -> str:
        if self._kr is None:
            return ""
        try:
            return self._kr.get_password(KEYRING_SERVICE, key) or ""
        except Exception:
            log.warning("could not read secret %s from the credential store", key)
            return ""

    def set(self, key: str, value: str) -> bool:
        if self._kr is None:
            return False
        try:
            if value:
                self._kr.set_password(KEYRING_SERVICE, key, value)
            else:
                try:
                    self._kr.delete_password(KEYRING_SERVICE, key)
                except Exception:
                    pass
            return True
        except Exception:
            log.warning("could not store secret %s in the credential store", key)
            return False


def _secret_slots(cfg: dict[str, Any]):
    """Yield (container dict, field name, keyring key) for every secret-bearing field."""
    for dest in cfg.get("destinations", []):
        auth = dest.get("auth") or {}
        for f in SECRET_FIELDS:
            if f in auth:
                yield auth, f, f"{dest.get('id')}:{f}"
    orders_auth = (cfg.get("orders") or {}).get("auth") or {}
    for f in SECRET_FIELDS:
        if f in orders_auth:
            yield orders_auth, f, f"orders:{f}"


# ---------------------------------------------------------------------------
# Migration from LabSync 1.x
# ---------------------------------------------------------------------------


def migrate_v1(old: dict[str, Any]) -> dict[str, Any]:
    cfg = default_config()
    cfg["instance_id"] = old.get("instance_id") or cfg["instance_id"]
    cfg["app_name"] = old.get("app_name") or "LabSync"
    cfg["auto_start"] = bool(old.get("auto_start", False))
    profile = LEGACY_ANALYZER_NAMES.get(old.get("analyzer_type", ""), "generic_astm")
    dev = new_device(profile, port=int(old.get("port", 5000)))
    dev["transport"] = {"type": "tcp_server", "host": "0.0.0.0", "port": int(old.get("port", 5000))}
    if old.get("analyzer_type"):
        dev["options"]["legacy_analyzer_type"] = old["analyzer_type"]
    cfg["devices"].append(dev)
    ext = old.get("external_server") or {}
    if ext.get("url"):
        dest = new_destination("http", "External server")
        dest["enabled"] = bool(ext.get("enabled", False))
        dest["url"] = ext["url"].rstrip("/") + ("/" + ext["endpoint_path"].lstrip("/") if ext.get("endpoint_path") else "")
        dest["method"] = str(ext.get("http_method", "POST")).upper()
        dest["payload_format"] = "legacy"  # keep the exact JSON shape existing servers expect
        method = ext.get("auth_method", "api_key")
        auth: dict[str, Any] = {"method": "none"}
        if method == "api_key" and ext.get("api_key"):
            auth = {"method": "api_key", "header": ext.get("api_key_header", "X-API-Key"), "api_key": ext["api_key"]}
        elif method == "bearer_token":
            auth = {"method": "bearer", "token": ext.get("bearer_token", "")}
        elif method == "basic_auth":
            auth = {"method": "basic", "username": ext.get("username", ""), "password": ext.get("password", "")}
        elif method == "oauth2":
            auth = {"method": "oauth2", "token_url": ext.get("oauth2_token_url", ""), "client_id": ext.get("client_id", ""),
                    "client_secret": ext.get("client_secret", ""), "scope": ext.get("scope", "")}
        elif method == "custom_header":
            dest["headers"] = {ext.get("custom_header_name", "X-Custom"): ext.get("custom_header_value", "")}
        dest["auth"] = auth
        freq = ext.get("sync_frequency", "realtime")
        if freq == "cron":
            dest["schedule"] = {"mode": "cron", "cron": ext.get("cron_expression") or ext.get("cron_schedule") or "0 * * * *"}
        elif freq == "scheduled":
            h, m = int(ext.get("scheduled_hour", 0) or 0), int(ext.get("scheduled_minute", 0) or 0)
            dest["schedule"] = {"mode": "cron", "cron": f"{m} {h} * * *"}
        else:
            dest["schedule"] = {"mode": "realtime"}
        cfg["destinations"].append(dest)
    return cfg


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(cfg: dict[str, Any]) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    problems: list[str] = []
    ids: set[str] = set()
    listen: dict[tuple[str, int], str] = {}
    for dev in cfg.get("devices", []):
        name = dev.get("name") or dev.get("id")
        if not dev.get("id"):
            problems.append(f"device {name!r} has no id")
        elif dev["id"] in ids:
            problems.append(f"duplicate id {dev['id']!r}")
        ids.add(dev.get("id", ""))
        if find_profile(dev.get("profile", "")) is None:
            problems.append(f"device {name!r}: unknown profile {dev.get('profile')!r}")
        t = dev.get("transport") or {}
        ttype = t.get("type")
        if ttype not in TRANSPORT_TYPES:
            problems.append(f"device {name!r}: transport type must be one of {', '.join(TRANSPORT_TYPES)}")
        elif ttype in ("tcp_server", "tcp_client"):
            try:
                port = int(t.get("port", 0))
                if not 1 <= port <= 65535:
                    raise ValueError
            except (TypeError, ValueError):
                problems.append(f"device {name!r}: port must be 1-65535")
                port = 0
            if ttype == "tcp_client" and not t.get("host"):
                problems.append(f"device {name!r}: analyzer host/IP is required for a client connection")
            if ttype == "tcp_server" and dev.get("enabled", True) and port:
                key = (t.get("host") or "0.0.0.0", port)
                if key in listen:
                    problems.append(f"devices {listen[key]!r} and {name!r} both listen on port {port}")
                listen[key] = name
        elif ttype == "serial" and not t.get("port"):
            problems.append(f"device {name!r}: serial port is required")
    for dest in cfg.get("destinations", []):
        name = dest.get("name") or dest.get("id")
        if dest.get("id") in ids:
            problems.append(f"duplicate id {dest.get('id')!r}")
        ids.add(dest.get("id", ""))
        dtype = dest.get("type")
        if dtype not in DESTINATION_TYPES:
            problems.append(f"destination {name!r}: type must be one of {', '.join(DESTINATION_TYPES)}")
            continue
        if dtype in ("http", "fhir"):
            url = str(dest.get("url", ""))
            if not url.startswith(("http://", "https://")):
                problems.append(f"destination {name!r}: URL must start with http:// or https://")
            auth = dest.get("auth") or {}
            if auth.get("method", "none") not in AUTH_METHODS:
                problems.append(f"destination {name!r}: unknown auth method {auth.get('method')!r}")
            if auth.get("method") == "oauth2" and not auth.get("token_url"):
                problems.append(f"destination {name!r}: OAuth2 token URL is required")
        elif dtype == "hl7_mllp" and not dest.get("host"):
            problems.append(f"destination {name!r}: host is required")
        elif dtype == "file" and not dest.get("folder"):
            problems.append(f"destination {name!r}: folder is required")
        sched = dest.get("schedule") or {}
        mode = sched.get("mode", "realtime")
        if mode not in SCHEDULE_MODES:
            problems.append(f"destination {name!r}: schedule must be realtime, interval or cron")
        elif mode == "cron" and not croniter.is_valid(str(sched.get("cron", ""))):
            problems.append(f"destination {name!r}: invalid cron expression {sched.get('cron')!r}")
        elif mode == "interval":
            try:
                if float(sched.get("interval_minutes", 0)) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                problems.append(f"destination {name!r}: interval must be a positive number of minutes")
    return problems


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ConfigManager:
    def __init__(self, path: Path, secrets: SecretStore | None = None):
        self.path = Path(path)
        self.secrets = secrets or SecretStore()
        self.data: dict[str, Any] = default_config()
        self.migrated_from: int | None = None

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.data = default_config()
            self.save()
            return self.data
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            backup = self.path.with_suffix(".corrupt.json")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            log.error("configuration file was unreadable (%s); a backup was kept at %s", exc, backup)
            self.data = default_config()
            self.save()
            return self.data
        if int(raw.get("config_version", 1)) < 2:
            backup = self.path.with_name("config.v1.backup.json")
            if not backup.exists():
                backup.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            raw = migrate_v1(raw)
            self.migrated_from = 1
            log.info("migrated configuration from LabSync 1.x (backup at %s)", backup)
        merged = default_config()
        merged.update(raw)
        self.data = merged
        self._resolve_secrets(self.data)
        if self.migrated_from:
            self.save()
        return self.data

    def _resolve_secrets(self, cfg: dict[str, Any]) -> None:
        for container, f, key in _secret_slots(cfg):
            if container.get(f) == KEYRING_MARKER:
                container[f] = self.secrets.get(key)

    def save(self, data: dict[str, Any] | None = None) -> None:
        if data is not None:
            self.data = data
        to_disk = copy.deepcopy(self.data)
        for container, f, key in _secret_slots(to_disk):
            value = container.get(f) or ""
            if value and value != KEYRING_MARKER and self.secrets.set(key, value):
                container[f] = KEYRING_MARKER
        to_disk["config_version"] = CONFIG_VERSION
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(to_disk, fh, indent=2)
            if os.name != "nt":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)
