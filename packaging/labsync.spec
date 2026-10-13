# PyInstaller spec for LabSync. Build from the repository root:
#   pyinstaller packaging/labsync.spec --noconfirm
# Produces dist/LabSync/ (Windows, Linux) or dist/LabSync.app (macOS).
# ruff: noqa
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from labsync._version import __version__  # noqa: E402

datas = [(str(SRC / "labsync" / "resources"), "labsync/resources")]
datas += collect_data_files("sv_ttk")

hiddenimports = collect_submodules("keyring.backends") + ["labsync.tools.simulator"]
if sys.platform == "win32":
    hiddenimports += ["pystray._win32", "win32timezone"]

icon = str(SRC / "labsync" / "resources" / ("icon.ico" if sys.platform == "win32" else "icon.png"))
if sys.platform == "darwin" and (ROOT / "packaging" / "macos" / "LabSync.icns").exists():
    icon = str(ROOT / "packaging" / "macos" / "LabSync.icns")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["numpy", "matplotlib", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LabSync",
    console=False,
    icon=icon,
)
# Console twin for scripting and commissioning: labsync-cli profiles | parse | check-config | --headless
cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="labsync-cli",
    console=True,
    icon=icon,
)
coll = COLLECT(exe, cli, a.binaries, a.datas, name="LabSync")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LabSync.app",
        icon=icon,
        bundle_identifier="com.labsync.app",
        version=__version__,
        info_plist={
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSLocalNetworkUsageDescription": "LabSync listens for laboratory analyzers on the local network.",
        },
    )
