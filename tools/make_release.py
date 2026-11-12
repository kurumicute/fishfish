"""Build release packages.

    python tools/make_release.py            # exe build + both zips
    python tools/make_release.py --src-only # only the source zip

Outputs (in release/):
    NovelTerminal-win64.zip   standalone build (no Python needed) for GitHub Releases
    novel-terminal-src.zip    clean source tree for the GitHub repository
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
APP_NAME = "NovelTerminal"

# what goes into the source zip (everything else is left out)
SRC_ITEMS = ["main.py", "requirements.txt", "requirements-dev.txt", "README.md", ".gitignore",
             "install.bat", "run.bat", "build.bat", "config", "core", "ui", "database", "samples",
             "tests", "tools", "data/.gitkeep"]
SKIP_PARTS = {"__pycache__", ".venv", "build", "dist", "release"}
SKIP_SUFFIXES = {".pyc", ".db", ".db-journal"}


def _iter_files(item: Path):
    if item.is_file():
        yield item
        return
    for path in sorted(item.rglob("*")):
        if path.is_file() and not (SKIP_PARTS & set(path.relative_to(ROOT).parts)) and path.suffix not in SKIP_SUFFIXES:
            yield path


def make_source_zip() -> Path:
    RELEASE.mkdir(exist_ok=True)
    target = RELEASE / "novel-terminal-src.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in SRC_ITEMS:
            item = ROOT / name
            if not item.exists():
                continue
            for path in _iter_files(item):
                zf.write(path, Path("novel-terminal") / path.relative_to(ROOT))
    return target


def build_exe() -> Path:
    sep = ";"   # PyInstaller --add-data separator on Windows
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--name", APP_NAME,
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        # project source is also the built-in code source shown on screen -> bundle the .py files as data
        "--add-data", f"{ROOT / 'core'}{sep}core",
        "--add-data", f"{ROOT / 'ui'}{sep}ui",
        "--add-data", f"{ROOT / 'database'}{sep}database",
        "--add-data", f"{ROOT / 'config'}{sep}config",
        # pygments loads lexers / styles by name at runtime
        "--collect-submodules", "pygments.lexers",
        "--collect-submodules", "pygments.styles",
        "--hidden-import", "lxml._elementpath",
        str(ROOT / "main.py"),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)
    app_dir = ROOT / "dist" / APP_NAME
    # user-editable files next to the exe
    shutil.copytree(ROOT / "config", app_dir / "config", dirs_exist_ok=True)
    shutil.copytree(ROOT / "samples", app_dir / "samples", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    (app_dir / "data").mkdir(exist_ok=True)
    shutil.copy2(ROOT / "README.md", app_dir / "README.md")
    return app_dir


def make_exe_zip(app_dir: Path) -> Path:
    RELEASE.mkdir(exist_ok=True)
    target = RELEASE / f"{APP_NAME}-win64.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(app_dir.rglob("*")):
            if path.is_file() and path.suffix not in (".db", ".db-journal"):
                zf.write(path, Path(APP_NAME) / path.relative_to(app_dir))
    return target


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src-only", action="store_true")
    args, _ = ap.parse_known_args()
    src = make_source_zip()
    print(f"source zip : {src} ({src.stat().st_size / 1024:.0f} KB)")
    if not args.src_only:
        exe = make_exe_zip(build_exe())
        print(f"windows zip: {exe} ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
