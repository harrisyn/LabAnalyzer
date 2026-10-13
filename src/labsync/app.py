"""Command-line entry point.

    labsync                      start the desktop app
    labsync --headless           run the engine without a GUI (service / server use)
    labsync profiles             list supported instrument profiles
    labsync parse FILE --profile sysmex_xn_l   parse a captured byte stream and print JSON
    labsync check-config         validate the configuration file
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path

from . import __version__, paths
from .config import ConfigManager, validate
from .logging_setup import configure_logging

log = logging.getLogger("labsync")


class SingleInstance:
    """Advisory lock so two copies never fight over the same ports and database."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "a+")  # noqa: SIM115 - held for the process lifetime
        try:
            if os.name == "nt":
                import msvcrt

                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True


def _load(args) -> tuple[ConfigManager, dict]:
    mgr = ConfigManager(Path(args.config) if args.config else paths.config_file())
    cfg = mgr.load()
    return mgr, cfg


def cmd_profiles(args) -> int:
    from .devices.catalog import PROFILES
    from .protocols import PROTOCOL_LABELS

    if getattr(args, "markdown", False):
        print("| Category | Vendor | Models | Protocol | Default link | Status | Profile id |")
        print("|---|---|---|---|---|---|---|")
        for p in PROFILES:
            link = "RS-232" if p.transport == "serial" else "TCP/IP"
            print(f"| {p.category} | {p.vendor} | {p.model} | {PROTOCOL_LABELS.get(p.protocol, p.protocol)} | {link}"
                  f" | {p.maturity} | `{p.id}` |")
        return 0
    for p in PROFILES:
        print(f"{p.id:28} {p.protocol:11} {p.maturity:12} {p.vendor} {p.model}")
    return 0


def cmd_parse(args) -> int:
    from .devices.catalog import get_profile, merged_options
    from .models import report_to_dict
    from .protocols import parse_capture

    profile = get_profile(args.profile)
    options = merged_options(profile, json.loads(args.options) if args.options else None)
    protocol = options.pop("protocol", None) or profile.protocol
    data = Path(args.file).read_bytes()
    messages, replies = parse_capture(protocol, data, options)
    out = [{
        "type": m.message_type, "sender": m.sender, "warnings": m.warnings,
        "reports": [report_to_dict(r) for r in m.reports],
        "queries": [{"specimen_ids": q.specimen_ids} for q in m.queries],
    } for m in messages]
    print(json.dumps({"protocol": protocol, "messages": out, "reply_bytes": replies.hex()}, indent=2, default=str))
    return 0


def cmd_check(args) -> int:
    _, cfg = _load(args)
    problems = validate(cfg)
    for p in problems:
        print(f"- {p}")
    print("configuration OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def run_headless(args) -> int:
    from .engine import Engine
    from .storage.db import Database

    mgr, cfg = _load(args)
    configure_logging(paths.log_dir(), cfg.get("log_level", "INFO"))
    problems = validate(cfg)
    for p in problems:
        log.warning("configuration: %s", p)
    db = Database(paths.database_file())
    engine = Engine(cfg, db)

    async def main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):  # Windows
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
        await engine.start()
        await stop.wait()
        await engine.stop()

    log.info("LabSync %s starting headless (config %s)", __version__, mgr.path)
    asyncio.run(main())
    db.close()
    return 0


def run_gui(args) -> int:
    try:
        from .gui.main_window import run
    except ImportError as exc:  # tkinter missing (some Linux Pythons)
        print(f"GUI unavailable ({exc}); use --headless", file=sys.stderr)
        return 2
    mgr, cfg = _load(args)
    configure_logging(paths.log_dir(), cfg.get("log_level", "INFO"), console=not getattr(sys, "frozen", False))
    return run(mgr, minimized=args.minimized)


def main(argv: list[str] | None = None) -> int:
    # A windowed (no-console) build has no stdout/stderr; keep print() and argparse from crashing.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115
    parser = argparse.ArgumentParser(prog="labsync", description="LabSync laboratory instrument integration")
    parser.add_argument("--version", action="version", version=f"LabSync {__version__}")
    parser.add_argument("--home", help="data folder (overrides LABSYNC_HOME)")
    parser.add_argument("--config", help="path to config.json")
    parser.add_argument("--headless", action="store_true", help="run without the GUI")
    parser.add_argument("--minimized", action="store_true", help="start hidden in the tray")
    sub = parser.add_subparsers(dest="command")
    pp = sub.add_parser("profiles", help="list instrument profiles")
    pp.add_argument("--markdown", action="store_true", help="print a Markdown table")
    p = sub.add_parser("parse", help="parse a captured byte stream")
    p.add_argument("file")
    p.add_argument("--profile", default="generic_astm")
    p.add_argument("--options", help="JSON object of option overrides")
    sub.add_parser("check-config", help="validate the configuration")
    args = parser.parse_args(argv)

    if args.home:
        os.environ["LABSYNC_HOME"] = args.home
    if args.command == "profiles":
        return cmd_profiles(args)
    if args.command == "parse":
        return cmd_parse(args)
    if args.command == "check-config":
        return cmd_check(args)

    lock = SingleInstance(paths.app_home() / "labsync.lock")
    if not lock.acquire():
        msg = "LabSync is already running for this data folder."
        if args.headless:
            print(msg, file=sys.stderr)
        else:
            try:
                import tkinter
                from tkinter import messagebox

                root = tkinter.Tk()
                root.withdraw()
                messagebox.showinfo("LabSync", msg)
                root.destroy()
            except Exception:
                print(msg, file=sys.stderr)
        return 3
    return run_headless(args) if args.headless else run_gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
