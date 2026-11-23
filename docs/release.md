# Release procedure

The `Release` workflow (`.github/workflows/release.yml`) builds the macOS and Linux bundles, each with Ladybird's
engine, and attaches them to a **draft pre-release**. Nothing is public until someone checks the artifacts and
publishes the draft by hand.

## Cut a release

1. Set the version in `Cargo.toml`, then merge it to `main` with CI green.
2. Tag the commit with a version such as `v0.1.0-alpha.1` and push the tag.
3. Wait for the `Release` workflow. `verify` runs formatting, Clippy and tests, then the `macos` and `linux` jobs
   build, smoke-test and package each platform.
4. Download each artifact's `.sha256` file and check it, then run the browser from its archive on a clean machine.
5. Publish the draft on GitHub, with the release notes listing the known limitations below.

`workflow_dispatch` runs the same jobs for a chosen branch and uploads the artifacts without creating a release.

## Before tagging: third-party notices

`THIRD_PARTY_NOTICES.md` covers the Rust crates and the bundled C++ components of both platforms. The Linux bundle is
built in the container, so its vcpkg metadata is staged out of the container's volumes first:

1. Build the x86_64 bundle with `./elaris linux-build --arch amd64`, or `./elaris linux-test --arch amd64`.
2. Stage its library list and vcpkg metadata into `build/notices-inputs/x64-linux-dynamic` (read-only from the build
   volumes; see the commit that added the Linux notices for the exact `docker run` command).
3. Regenerate the notices on the host with `./elaris bundle` run on macOS and `python3 tools/notices.py`, then check
   that `python3 tools/notices.py --check` passes.

## Versions

Releases use SemVer pre-release tags such as `v0.1.0-alpha.1`. `Cargo.toml` carries the same version, and the release
artifacts and `BUILD-INFO.txt` use the tag. The macOS app bundle keeps the plain `0.1.0` in `Info.plist`, because Apple's
bundle version fields accept only numbers and dots.

## What each artifact contains

| Platform | File | Contents |
| --- | --- | --- |
| macOS, Apple Silicon | `Elaris-<version>-macos-arm64.dmg` | `Elaris.app`: the browser, Ladybird's helper processes, its resources, and the libraries it links, ad-hoc signed |
| Linux, x86_64 | `Elaris-<version>-linux-x86_64.tar.gz` | A prefix tree: `bin/elaris`, `libexec/` helpers, `lib/` libraries, `share/` resources, desktop entry and icons, plus `install.sh` and `INSTALL-VOID.md` beside the tree |
| Void Linux, x86_64 | `elaris-<version>_1.x86_64.xbps` and `x86_64-repodata` | The same tree as a Void package: the engine in `/usr/lib/elaris` with `bin/`, `lib/`, `libexec/` and `share/`, `/usr/bin/elaris`, and links for the desktop entry and icons |

Each archive comes with a `.sha256` checksum and a `BUILD-INFO.txt` that records the Elaris commit, the pinned Ladybird
commit, the Rune revision, and the toolchain used.

The Void package keeps the tree's own layout under `/usr/lib/elaris`, so Ladybird's helpers still find `../share/Lagom`
beside themselves; `/usr/bin/elaris` and the desktop entry and icons in `/usr/share` are links into that tree.
`packaging/linux/build-xbps.sh` builds the package and its index from `build/linux/Elaris`, taking Void's statically
linked `xbps-create` and `xbps-rindex` from `PATH`, from `--xbps-tools`, or by downloading them into `build/tools/`.

## Limitations of this release process

- Apple builds are ad-hoc signed. They are not notarized, so Gatekeeper will ask for approval on first launch.
- macOS builds target Apple Silicon only. Intel Macs are not supported for the alpha, and Linux ARM64 is not built.
- The minimum macOS version is 14.4, the lowest version Ladybird supports.
- Linux needs a Vulkan driver at run time, which the system's GPU driver or Mesa provides.
- The Linux x86_64 build runs in Ladybird's CI image, which is Ubuntu 26.04 with glibc 2.43. The bundle therefore needs
  glibc 2.43 or newer at run time, so older distributions such as Ubuntu 24.04, Debian 12 and RHEL 9 cannot run it yet.
  The target is all major distributions, which needs the Linux build moved to an older glibc base. Local verification
  was done on arm64 under Docker, so the first run of the workflow is the first x86_64 check.
- The Linux archive is a glibc build, so Void Linux's musl flavour cannot run it. `install.sh` checks the C library,
  architecture and Vulkan at install time, and `INSTALL-VOID.md` names the Void packages the browser needs
  (`vulkan-loader` and a Mesa Vulkan driver). Neither has been run on a Void installation yet.
- The Void package and its repository index are unsigned, so it is installed from a local directory rather than a
  remote repository, and the `.sha256` is the only integrity check. The package depends on `vulkan-loader` but cannot
  depend on a GPU-specific Mesa driver. It has been installed with Void's static xbps tools into a scratch root, but
  not yet on a real Void system with a desktop session.
- Linux support targets both Wayland and X11 sessions. Neither has been tested on a real desktop yet.
- The pinned Ladybird and Rune revisions are recorded in `BUILD-INFO.txt`. Both must be pinned before tagging.
