"""PyInstaller entry point (kept outside the package so relative imports resolve)."""

from labsync.app import main

if __name__ == "__main__":
    raise SystemExit(main())
