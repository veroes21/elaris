"""Assemble Elaris's app bundles: a macOS .app and a Linux prefix tree, each with Ladybird's engine and the brand icon."""

import filecmp
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

from . import ui
from .common import ENGINE, ROOT, VCPKG_INSTALLED, run, vcpkg_triplet

ASSETS = ROOT / "assets"
PACKAGING = ROOT / "packaging"
LINUX_ASSETS = PACKAGING / "linux"
# Compiled from the brand kit's Icon Composer document, so the designer's layers and gradient carry over.
APP_ICON_SOURCE = ASSETS / "brand-kit" / "apple" / "Icon Exports" / "Icon.icon"
APP_ID = "org.elarisbrowser.Elaris"
ENGINE_BUILD = ROOT / "build" / "cpp-ladybird"
LADYBIRD_APP = ENGINE_BUILD / "bin" / "Ladybird.app"
# Ladybird's packager rewrites rpaths, copies linked libraries, and re-signs; Elaris reuses it rather than repeat it.
LADYBIRD_MACOS_TOOL = ENGINE / "Meta" / "package-macos-test-bundle.py"
# Elaris's app icon replaces Ladybird's own, so the engine's copies of these two are left behind.
LADYBIRD_APP_ICON_FILES = ("Assets.car", "app_icon.icns")
# Ladybird's own app binary; Elaris ships only the helper processes.
LADYBIRD_APP_BINARY = "Ladybird"


def _copy_if_changed(source: Path, destination: Path) -> bool:
    """Copy `source` over `destination` when their contents differ. Returns whether it copied.

    The copy takes a fresh modification time on purpose: Launch Services caches an app's icon by file time,
    so a copy that kept the source's older time can keep showing a stale icon in the Dock.
    """
    if destination.exists() and filecmp.cmp(source, destination, shallow=False):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    shutil.copymode(source, destination)
    return True


def _macos_app_icon() -> Path:
    """Compile the icon into Assets.car (macOS 26+) and Icon.icns (older systems), cached under build/."""
    output = ROOT / "build" / "icons" / "macos"
    compiled = [output / "Assets.car", output / "Icon.icns"]
    newest_source = max(path.stat().st_mtime_ns for path in APP_ICON_SOURCE.rglob("*") if path.is_file())
    if all(path.is_file() and path.stat().st_mtime_ns >= newest_source for path in compiled):
        return output

    output.mkdir(parents=True, exist_ok=True)
    run(
        "xcrun", "actool", str(APP_ICON_SOURCE),
        "--compile", str(output),
        "--output-partial-info-plist", str(output / "partial-info.plist"),
        "--app-icon", "Icon",
        "--platform", "macosx",
        "--target-device", "mac",
        "--minimum-deployment-target", "26.0",
        "--development-region", "en",
        "--enable-on-demand-resources", "NO",
        "--output-format", "human-readable-text",
        "--errors", "--warnings",
    )
    return output


def _macos_bundle_metadata(contents: Path) -> None:
    """Copy the Info.plist and the compiled icon into an app's Contents."""
    icon = _macos_app_icon()
    for source, destination in (
        (PACKAGING / "macos" / "Info.plist", contents / "Info.plist"),
        (icon / "Assets.car", contents / "Resources" / "Assets.car"),
        (icon / "Icon.icns", contents / "Resources" / "Icon.icns"),
    ):
        _copy_if_changed(source, destination)


def macos_app_bundle(executable: Path, name: str = "ElarisDev") -> Path:
    """A development .app around the executable. Ladybird's helpers stay in the build tree, which the bridge falls
    back to when no packaged helpers sit beside the executable. Returns the bundled executable."""
    contents = ROOT / "build" / f"{name}.app" / "Contents"
    bundled_executable = contents / "MacOS" / executable.name
    copied = _copy_if_changed(executable, bundled_executable)
    _macos_bundle_metadata(contents)
    if copied:
        # Replacing any file in a signed bundle invalidates its signature, and macOS kills the app for that.
        subprocess.run(["codesign", "--force", "--sign", "-", str(contents.parent)], check=True)
        # Launch Services also keys its icon cache on the bundle folder's time, so refresh it with the contents.
        contents.parent.touch()
    return bundled_executable


def _ladybird_macos_tool():
    """Load Ladybird's macOS bundle packager from the pinned engine checkout."""
    spec = importlib.util.spec_from_file_location("ladybird_package_macos_test_bundle", LADYBIRD_MACOS_TOOL)
    if spec is None or spec.loader is None:
        raise SystemExit(f"elaris: Ladybird's macOS packager is missing at {LADYBIRD_MACOS_TOOL}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# What the last full bundle was assembled from: the engine's helpers and Elaris's executable.
RELEASE_BUNDLE_STAMP = ROOT / "build" / "Elaris.app.stamp"


def _bundle_inputs(executable: Path) -> tuple[str, str]:
    """When the engine's helpers and Elaris's executable last changed."""
    helpers = (LADYBIRD_APP / "Contents" / "MacOS").iterdir()
    engine = max(helper.stat().st_mtime_ns for helper in helpers if helper.is_file())
    return str(engine), str(executable.stat().st_mtime_ns)


def macos_release_bundle(executable: Path) -> Path:
    """build/Elaris.app with Ladybird's helpers, resources and libraries, relocatable and signed.

    A full assembly copies and verifies every engine library, which takes about half a minute, so it runs only
    when the engine changed. When only Elaris changed, its executable is swapped in and the bundle re-signed;
    when nothing changed, the bundle is reused as is. Returns the bundled executable.
    """
    if not (LADYBIRD_APP / "Contents" / "MacOS" / LADYBIRD_APP_BINARY).is_file():
        raise SystemExit("elaris: Ladybird's app bundle is missing; run ./elaris build first")
    tool = _ladybird_macos_tool()

    app = ROOT / "build" / "Elaris.app"
    contents = app / "Contents"
    bundled_executable = contents / "MacOS" / executable.name
    engine, elaris = _bundle_inputs(executable)
    previous = RELEASE_BUNDLE_STAMP.read_text().split() if RELEASE_BUNDLE_STAMP.is_file() else []
    if bundled_executable.is_file() and len(previous) == 2 and previous[0] == engine:
        if previous[1] != elaris:
            ui.info("Updating Elaris in Elaris.app…")
            shutil.copy2(executable, bundled_executable)
            tool.fix_rpaths(app)
            tool.resign(app, ENGINE_BUILD)
            RELEASE_BUNDLE_STAMP.write_text(f"{engine} {elaris}")
        return bundled_executable

    ui.info("Bundling Elaris.app with Ladybird's engine (about 30 seconds)…")
    RELEASE_BUNDLE_STAMP.unlink(missing_ok=True)
    if app.exists():
        shutil.rmtree(app)
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    shutil.copy2(executable, bundled_executable)
    for helper in (LADYBIRD_APP / "Contents" / "MacOS").iterdir():
        if helper.is_file() and helper.name != LADYBIRD_APP_BINARY:
            shutil.copy2(helper, macos / helper.name)
    shutil.copytree(
        LADYBIRD_APP / "Contents" / "Resources",
        contents / "Resources",
        ignore=shutil.ignore_patterns(*LADYBIRD_APP_ICON_FILES),
    )
    _macos_bundle_metadata(contents)

    # Libraries come from the directories the built executables were linked against, which is what dyld searched.
    search_directories = []
    for binary in (executable, macos / "WebContent"):
        for entry in tool.rpath_entries(binary):
            directory = Path(entry)
            if entry.startswith("/") and directory.is_dir() and directory not in search_directories:
                search_directories.append(directory)
    tool.fix_rpaths(app)
    copied = tool.copy_linked_libraries(app, search_directories)
    tool.fix_rpaths(app)
    tool.resign(app, ENGINE_BUILD)
    tool.verify(app)
    ui.info(f"copied {len(copied)} libraries into {app.name}/Contents/lib")
    RELEASE_BUNDLE_STAMP.write_text(f"{engine} {elaris}")
    return bundled_executable


def _elf_needed(binary: Path) -> list[str]:
    result = subprocess.run(["readelf", "-d", str(binary)], capture_output=True, text=True, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"elaris: could not read the libraries {binary} needs: {detail}")
    output = result.stdout
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", output)


def _linux_search_directories() -> list[Path]:
    """The directories the engine's libraries were built into: Lagom's and vcpkg's."""
    directories = [ENGINE_BUILD / "lib", VCPKG_INSTALLED / vcpkg_triplet() / "lib"]
    return [directory for directory in directories if directory.is_dir()]


def _copy_linux_libraries(binaries: list[Path], library_directory: Path) -> list[str]:
    """Copy each library the binaries need that a build directory has, transitively. Libraries the system provides
    (the C library, libstdc++, the graphics stack) are left to the system."""
    search_directories = _linux_search_directories()
    library_directory.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    pending = list(binaries)
    seen = {binary.resolve() for binary in pending}
    while pending:
        binary = pending.pop()
        for name in _elf_needed(binary):
            source = next((directory / name for directory in search_directories if (directory / name).is_file()), None)
            if source is None:
                continue
            destination = library_directory / name
            if not destination.exists():
                shutil.copyfile(source.resolve(), destination)
                shutil.copymode(source.resolve(), destination)
                copied.append(name)
            if destination.resolve() not in seen:
                seen.add(destination.resolve())
                pending.append(destination)
    return copied


def linux_prefix_bundle(executable: Path, prefix: Path) -> Path:
    """A prefix tree (bin/, lib/, libexec/, share/) that copying into ~/.local or /usr installs whole.

    Ladybird's layout is what its helpers search: they live in libexec/, their resources in share/Lagom, and each
    binary finds the libraries in ../lib through its RUNPATH. Returns the installed executable.
    """
    if not (ENGINE_BUILD / "libexec" / "WebContent").is_file():
        raise SystemExit("elaris: Ladybird's helper processes are missing; run ./elaris build first")
    if shutil.which("patchelf") is None:
        raise SystemExit("elaris: patchelf is required to bundle Linux libraries; install it and rerun ./elaris bundle")

    # Assembled from scratch each time, so no stale library or helper survives a rebuild.
    if prefix.exists():
        shutil.rmtree(prefix)
    installed = prefix / "bin" / executable.name
    installed.parent.mkdir(parents=True)
    shutil.copy2(executable, installed)
    helpers = sorted(path for path in (ENGINE_BUILD / "libexec").iterdir() if path.is_file())
    (prefix / "libexec").mkdir()
    for helper in helpers:
        shutil.copy2(helper, prefix / "libexec" / helper.name)
    library_directory = prefix / "lib"
    _copy_linux_libraries([installed, *(prefix / "libexec" / helper.name for helper in helpers)], library_directory)

    shutil.copytree(ENGINE_BUILD / "share" / "Lagom", prefix / "share" / "Lagom")
    applications = prefix / "share" / "applications"
    applications.mkdir(parents=True)
    shutil.copy2(LINUX_ASSETS / f"{APP_ID}.desktop", applications / f"{APP_ID}.desktop")
    icon_root = LINUX_ASSETS / "icons"
    for source in icon_root.rglob("*"):
        if source.is_file():
            destination = prefix / "share" / "icons" / source.relative_to(icon_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    # Shipped beside the tree rather than inside it: install.sh copies only bin/, lib/, libexec/ and share/.
    installer = prefix / "install.sh"
    shutil.copy2(LINUX_ASSETS / "install.sh", installer)
    installer.chmod(0o755)
    shutil.copy2(LINUX_ASSETS / "INSTALL-VOID.md", prefix / "INSTALL-VOID.md")

    run_path = {installed: "$ORIGIN/../lib"}
    run_path.update({prefix / "libexec" / helper.name: "$ORIGIN/../lib" for helper in helpers})
    run_path.update({library: "$ORIGIN" for library in library_directory.iterdir() if library.is_file()})
    for binary, origin in run_path.items():
        subprocess.run(["patchelf", "--set-rpath", origin, str(binary)], check=True)
    _verify_linux_prefix(prefix)
    return installed


def _verify_linux_prefix(prefix: Path) -> None:
    """Fail if a binary's RUNPATH still names the build tree, since the bundle must run from anywhere."""
    for binary in sorted(path for path in prefix.rglob("*") if path.is_file() and not path.is_symlink()):
        if subprocess.run(["readelf", "-h", str(binary)], capture_output=True).returncode != 0:
            continue
        output = subprocess.run(["readelf", "-d", str(binary)], capture_output=True, text=True).stdout
        for runpath in re.findall(r"\((?:RUNPATH|RPATH)\)\s+Library (?:runpath|rpath): \[([^\]]*)\]", output):
            if any(entry.startswith("/") for entry in runpath.split(":")):
                raise SystemExit(f"elaris: {binary.relative_to(prefix)} still has an absolute RUNPATH: {runpath}")
