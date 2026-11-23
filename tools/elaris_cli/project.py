"""Rust application and general development commands."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import dependencies, engine, packaging, ui
from .common import (
    CPP_BUILD_DIR,
    ROOT,
    VCPKG_INSTALLED,
    bridge_files,
    prepare_ladybird_paths,
    require,
    run,
    run_step,
    vcpkg_triplet,
)

# Build directories that may hold the compiled bridge, most preferred first.
BRIDGE_LIB_DIRS = (CPP_BUILD_DIR / "lib", ROOT / "build" / "ladybird-integrated" / "lib")


def _profile(args: argparse.Namespace) -> str:
    """The Cargo profile directory the command builds into."""
    return "release" if getattr(args, "release", False) else "debug"


def _executable(profile: str) -> Path:
    return ROOT / "target" / profile / ("elaris.exe" if os.name == "nt" else "elaris")


def _run_artifacts_are_current(ui_only: bool, profile: str = "debug") -> bool:
    """Return whether a previous run's executable and (when enabled) bridge are current."""
    executable = _executable(profile)
    if not executable.is_file():
        return False

    source_roots = [ROOT / name for name in ("src", "crates", "tools", "assets", "packaging")]
    inputs = [ROOT / name for name in ("Cargo.toml", "Cargo.lock", "build.rs", "rust-toolchain.toml")]
    inputs.extend(path for source_root in source_roots if source_root.is_dir() for path in source_root.rglob("*"))
    if not ui_only:
        bridge = next((directory / f"libelaris_ladybird.{suffix}" for directory in BRIDGE_LIB_DIRS
                       for suffix in ("dylib", "so", "a")
                       if (directory / f"libelaris_ladybird.{suffix}").is_file()), None)
        if bridge is None:
            return False
        inputs.extend(bridge_files())
        inputs.extend((ROOT / "bridge" / "CMakeLists.txt", ROOT / "bridge" / "Peek.cmake"))

    newest_input = max((path.stat().st_mtime_ns for path in inputs if path.is_file()), default=0)
    if executable.stat().st_mtime_ns < newest_input:
        return False
    return ui_only or bridge.stat().st_mtime_ns >= newest_input


def setup(args: argparse.Namespace) -> None:
    if not args.skip_system_deps:
        dependencies.install_system_dependencies()
    dependencies.verify_system_dependencies()
    dependencies.install_rust_toolchain()
    run("git", "submodule", "update", "--init", "--recursive")
    prepare_ladybird_paths()
    dependencies.verify_ladybird_compiler()
    dependencies.install_ladybird_toolchain()
    ui.success("Setup is complete")
    ui.next_steps([
        ("./elaris build", "Build Ladybird and Elaris"),
        ("./elaris run", "Build if needed, then launch"),
    ])
    ui.muted("\nThe first engine build can take a while. See CONTRIBUTING.md for the full workflow.")


def build(args: argparse.Namespace) -> None:
    release = ["--release"] if _profile(args) == "release" else []
    if args.ui:
        run_step("Elaris interface", "cargo", "+stable", "build", "--locked", *release)
        return
    engine.build_for_elaris(args.jobs)
    _configure_bridge_environment(bridge_lib_dir())
    run_step("Elaris browser", "cargo", "+stable", "build", "--locked", *release, "--features", "ladybird-bridge")


def format_sources(_args: argparse.Namespace) -> None:
    require("cargo", "clang-format")
    run("cargo", "+stable", "fmt")
    files = [str(path) for path in bridge_files()]
    if files:
        run("clang-format", "-i", *files)


def bridge_lib_dir() -> str:
    if configured := os.environ.get("ELARIS_LADYBIRD_LIB_DIR"):
        return configured
    for directory in BRIDGE_LIB_DIRS:
        if any(directory.glob("libelaris_ladybird.*")):
            return str(directory)
    raise SystemExit("elaris: no built Ladybird bridge found; build it as bridge/README.md describes")


def runtime_library_dirs(bridge_dir: str) -> list[str]:
    directories = [bridge_dir]
    if (triplet := vcpkg_triplet()) and (vcpkg_lib := VCPKG_INSTALLED / triplet / "lib").is_dir():
        directories.append(str(vcpkg_lib))
    return directories


def _configure_bridge_environment(bridge_dir: str) -> None:
    os.environ["ELARIS_LADYBIRD_LIB_DIR"] = bridge_dir
    loader_variable = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
    directories = runtime_library_dirs(bridge_dir)
    if existing := os.environ.get(loader_variable):
        directories.append(existing)
    os.environ[loader_variable] = os.pathsep.join(directories)


def bundle(_args: argparse.Namespace) -> None:
    """Build an optimised Elaris and package it with Ladybird's engine and the brand icon for this platform."""
    build(argparse.Namespace(ui=False, release=True, jobs=None))
    executable = _executable("release")
    if sys.platform == "darwin":
        bundled = packaging.macos_release_bundle(executable)
        ui.success(f"Bundled {bundled.parents[2]}")
    elif sys.platform.startswith("linux"):
        prefix = ROOT / "build" / "linux" / "Elaris"
        packaging.linux_prefix_bundle(executable, prefix)
        ui.success(f"Bundled {prefix}")
        ui.info(f"Install with: {prefix}/install.sh  (see {prefix}/INSTALL-VOID.md on Void Linux)")
    else:
        raise SystemExit("elaris: bundle supports macOS and Linux")


def launch(args: argparse.Namespace) -> None:
    profile = _profile(args)
    release = ["--release"] if profile == "release" else []
    ui_only = args.ui or args.linux_ui
    if sys.platform == "darwin" and not ui_only:
        if not _run_artifacts_are_current(ui_only=False, profile=profile):
            build(args)
        _configure_bridge_environment(bridge_lib_dir())
        if release:
            executable = packaging.macos_release_bundle(_executable(profile))
        else:
            executable = packaging.macos_app_bundle(_executable(profile), "ElarisDev")
        # Launch Services starts the bundle and brings it forward, and -W waits until it quits, as a direct run does.
        app = executable.parents[2]
        extra = [*([args.url] if args.url else []), *args.rune_args]
        # Launch Services detaches the app's output, so keep it in a log beside the build.
        log = str(ROOT / "build" / "elaris-run.log")
        # Launch Services does not pass this shell's environment on, so forward the Elaris variables explicitly.
        environment = [item for name, value in sorted(os.environ.items()) if name.startswith("ELARIS_") for item in ("--env", f"{name}={value}")]
        run(
            "open", "-W", "-a", str(app), *environment,
            "--stdout", log, "--stderr", log,
            *(["--args", *extra] if extra else []),
        )
        return
    if not args.linux_ui and _run_artifacts_are_current(ui_only, profile):
        executable = _executable(profile)
        command = [str(executable)]
        if args.url:
            command.append(args.url)
        command.extend(args.rune_args)
        run(*command)
        return
    command = ["cargo", "+stable", "run", "--locked", *release]
    if args.linux_ui:
        # A separate target directory keeps this build's executable apart from the normal interface build.
        command += ["--features", "linux-ui", "--target-dir", str(ROOT / "target" / "linux-ui")]
    elif not ui_only:
        engine.build_for_elaris(args.jobs)
        _configure_bridge_environment(bridge_lib_dir())
        command += ["--features", "ladybird-bridge"]
    if args.url:
        command += ["--", args.url]
    if args.rune_args:
        if not args.url:
            command.append("--")
        command.extend(args.rune_args)
    run(*command)


def rune_dev_launcher() -> Path:
    try:
        metadata = subprocess.run(
            ["cargo", "+stable", "metadata", "--locked", "--format-version", "1"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise SystemExit("elaris: cargo is required to locate Rune's hot-reload launcher") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or str(error)
        raise SystemExit(f"elaris: could not resolve Rune's hot-reload launcher: {detail}") from error

    packages = json.loads(metadata.stdout)["packages"]
    rune = next(
        (
            package
            for package in packages
            if package["name"] == "rune"
            and (package.get("source") or "").startswith("git+https://github.com/elarisbrowser/rune?")
        ),
        None,
    )
    if rune is None:
        raise SystemExit("elaris: the pinned elarisbrowser/rune dependency was not found")

    rune_dir = Path(rune["manifest_path"]).parent
    launcher = rune_dir.parent.parent / "scripts" / "rune-dev"
    if not launcher.is_file():
        raise SystemExit(f"elaris: Rune's hot-reload launcher is missing: {launcher}")
    return launcher


def rune_dev_python() -> str:
    if sys.version_info >= (3, 11):
        return sys.executable

    candidates: list[tuple[int, Path]] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for candidate in Path(directory or ".").glob("python3.*"):
            minor = candidate.name.removeprefix("python3.")
            if minor.isdigit() and int(minor) >= 11 and candidate.is_file() and os.access(candidate, os.X_OK):
                candidates.append((int(minor), candidate.resolve()))
    if candidates:
        return str(max(candidates, key=lambda candidate: candidate[0])[1])

    current = ".".join(str(version) for version in sys.version_info[:3])
    raise SystemExit(f"elaris: Rune's hot-reload launcher needs Python 3.11+; found Python {current}")


def rune_git_shim(directory: Path) -> Path:
    # Rune's source walker reads Git submodule entries as files; omit those directory paths.
    git = shutil.which("git")
    if git is None:
        raise SystemExit("elaris: git is required by Rune's hot-reload launcher")

    shim = directory / "git"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        f"real_git = {git!r}\n"
        "args = sys.argv[1:]\n"
        "if 'ls-files' not in args or '-z' not in args:\n"
        "    os.execv(real_git, [real_git, *args])\n"
        "result = subprocess.run([real_git, *args], capture_output=True)\n"
        "output = result.stdout\n"
        "if result.returncode == 0:\n"
        "    paths = [\n"
        "        path\n"
        "        for path in output.split(b'\\0')\n"
        "        if path and (\n"
        "            os.path.islink(os.fsdecode(path))\n"
        "            or not os.path.isdir(os.fsdecode(path))\n"
        "        )\n"
        "    ]\n"
        "    output = b'\\0'.join(paths)\n"
        "    if output:\n"
        "        output += b'\\0'\n"
        "sys.stdout.buffer.write(output)\n"
        "sys.stderr.buffer.write(result.stderr)\n"
        "raise SystemExit(result.returncode)\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def rune_dx_shim(directory: Path) -> Path:
    """Enable Dioxus terminal shortcuts in Rune's local hot-reload server."""
    dx = Path(os.environ.get("RUNE_DX", Path.home() / ".cargo" / "bin" / "dx"))
    if not dx.is_file():
        raise SystemExit(f"elaris: Dioxus CLI was not found: {dx}")

    shim = directory / "dx"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        f"real_dx = {str(dx)!r}\n"
        "args = sys.argv[1:]\n"
        "for index in range(len(args) - 1):\n"
        "    if args[index:index + 2] == ['--interactive', 'false']:\n"
        "        args[index + 1] = 'true'\n"
        "        break\n"
        "os.execv(real_dx, [real_dx, *args])\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def hot_reload(args: argparse.Namespace) -> None:
    command = [
        rune_dev_python(),
        str(rune_dev_launcher()),
        "--local",
        "--manifest-path",
        str(ROOT / "Cargo.toml"),
        "--patch",
        "src/ui/**/*.rs",
    ]
    for pattern in args.patch:
        command.extend(("--patch", pattern))

    original_path = os.environ.get("PATH")
    original_dx = os.environ.get("RUNE_DX")
    with tempfile.TemporaryDirectory(prefix="elaris-rune-hot-") as directory:
        rune_git_shim(Path(directory))
        os.environ["PATH"] = os.pathsep.join(filter(None, (directory, original_path)))
        os.environ["RUNE_DX"] = str(rune_dx_shim(Path(directory)))
        try:
            run(*command)
        except KeyboardInterrupt:
            pass
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path
            if original_dx is None:
                os.environ.pop("RUNE_DX", None)
            else:
                os.environ["RUNE_DX"] = original_dx


def check(_args: argparse.Namespace) -> None:
    steps = (
        ("Formatting", "cargo", "+stable", "fmt", "--check"),
        ("Type checking", "cargo", "+stable", "check", "--locked"),
        ("Clippy lints", "cargo", "+stable", "clippy", "--locked", "--", "-D", "warnings"),
        ("Rust tests", "cargo", "+stable", "test", "--locked"),
        (
            "Developer CLI tests",
            sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tools" / "tests"), "-t", str(ROOT / "tools"),
        ),
    )
    for number, (title, *command) in enumerate(steps, start=1):
        run_step(title, *command, position=(number, len(steps)))
    ui.success("All checks passed")


def register_commands(commands) -> None:
    for name, handler, help_text in (
        ("setup", setup, "Install prerequisites and initialise Ladybird"),
        ("format", format_sources, "Format Elaris Rust and C++ source files"),
        ("build", build, "Build Ladybird, its Elaris bridge, and the browser"),
        ("run", launch, "Build if needed and launch Elaris with Ladybird"),
        ("bundle", bundle, "Build an optimised Elaris and package it with its icon"),
        ("hot", hot_reload, "Run Rune's guarded UI hot-reload workflow"),
        ("check", check, "Run formatting, Clippy, and tests"),
    ):
        subcommand = commands.add_parser(name, help=help_text)
        subcommand.set_defaults(handler=handler)
        if handler is setup:
            subcommand.add_argument(
                "--skip-system-deps",
                action="store_true",
                help="Skip package manager installs but still verify required tools",
            )
        elif handler is build:
            subcommand.add_argument("--ui", action="store_true", help="Build only the interface, without Ladybird")
            subcommand.add_argument("--release", action="store_true", help="Build Elaris optimised (cargo --release)")
            subcommand.add_argument("--jobs", help="Parallel build jobs (default: ELARIS_JOBS or 4)")
        if handler is launch:
            subcommand.add_argument(
                "--ui", action="store_true", help="Run the interface alone, without the Ladybird engine"
            )
            subcommand.add_argument(
                "--linux-ui",
                action="store_true",
                help="Run the interface with the Linux layout on any host, to preview it on macOS (implies --ui)",
            )
            subcommand.add_argument("--release", action="store_true", help="Run Elaris optimised (cargo --release)")
            subcommand.add_argument("--jobs", help="Parallel build jobs (default: ELARIS_JOBS or 4)")
            subcommand.add_argument("url", nargs="?", help="Address to open, such as example.com")
            subcommand.add_argument(
                "rune_args",
                nargs=argparse.REMAINDER,
                help="Rune options after --, such as --snap /tmp/elaris.png",
            )
        if handler is hot_reload:
            subcommand.add_argument(
                "--patch",
                action="append",
                default=[],
                metavar="GLOB",
                help="Additional Rust source glob to live patch (default: src/ui/**/*.rs)",
            )
