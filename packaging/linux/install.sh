#!/bin/sh
# Installs the Elaris release tree into a prefix, then refreshes the desktop entry and its caches.
# Distribution-specific setup for Void Linux is in INSTALL-VOID.md, which ships beside this script.
set -eu

# The release links against the glibc that Ladybird's build image ships.
REQUIRED_GLIBC="2.43"

usage() {
    cat <<'EOF'
Usage: ./install.sh [--prefix DIR]

Installs Elaris from this archive into DIR/bin, DIR/lib, DIR/libexec and DIR/share.
The default prefix is ~/.local. Void Linux setup steps are in INSTALL-VOID.md.

    --prefix DIR    install under DIR instead of ~/.local
    -h, --help      show this message
EOF
}

fail() {
    printf 'elaris: %s\n' "$1" >&2
    exit 1
}

note() {
    printf 'elaris: %s\n' "$1" >&2
}

# Compares two dotted versions by their first two components, which is all a glibc floor needs.
version_at_least() {
    awk -v have="$1" -v need="$2" 'BEGIN {
        split(have, a, ".")
        split(need, b, ".")
        for (i = 1; i <= 2; i++) {
            if (a[i] + 0 > b[i] + 0) exit 0
            if (a[i] + 0 < b[i] + 0) exit 1
        }
        exit 0
    }'
}

prefix="${PREFIX:-$HOME/.local}"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || fail "--prefix needs a directory"
            prefix="$2"
            shift 2
            ;;
        --prefix=*)
            prefix="${1#--prefix=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            fail "unknown option: $1"
            ;;
    esac
done

case "$prefix" in
    /*) ;;
    *) fail "--prefix must be an absolute path" ;;
esac

source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for entry in bin lib libexec share; do
    [ -e "$source_dir/$entry" ] || fail "this archive is incomplete: $entry is missing"
done

[ "$(uname -m)" = "x86_64" ] || fail "this release is x86_64 only; build Elaris from source on $(uname -m)"

# A musl system cannot load a glibc build. glibc reports itself through getconf; ldd is the fallback, whose first
# line ends with the version there too.
libc_version=""
if reported_libc=$(getconf GNU_LIBC_VERSION 2>/dev/null) && [ "${reported_libc#glibc }" != "$reported_libc" ]; then
    libc_version=${reported_libc#glibc }
else
    libc_line=$(ldd --version 2>/dev/null | sed -n 1p || true)
    case "$libc_line" in
        *GLIBC*|*glibc*|*"GNU libc"*) libc_version=${libc_line##* } ;;
    esac
fi
[ -n "$libc_version" ] ||
    fail "this release needs glibc, but this system uses another C library; Void's musl flavour cannot run it, so use the glibc flavour or build from source"
version_at_least "$libc_version" "$REQUIRED_GLIBC" ||
    fail "this release needs glibc $REQUIRED_GLIBC or newer, but this system has ${libc_version:-an unknown version}; build Elaris from source on this distribution"

mkdir -p "$prefix"
# Merges into an existing install rather than replacing it, so no other files under the prefix are lost.
cp -a "$source_dir/bin" "$source_dir/lib" "$source_dir/libexec" "$source_dir/share" "$prefix/"

desktop_file="$prefix/share/applications/org.elarisbrowser.Elaris.desktop"
entry_on_path=no
case ":$PATH:" in
    *":$prefix/bin:"*) entry_on_path=yes ;;
esac
if [ -f "$desktop_file" ] && [ "$entry_on_path" = no ]; then
    # The shipped entry runs `elaris` from PATH, so name the installed path when the prefix is not on PATH.
    escaped_prefix=$(printf '%s' "$prefix" | sed 's/[&|\\]/\\&/g')
    sed -i "s|^Exec=elaris |Exec=${escaped_prefix}/bin/elaris |" "$desktop_file"
fi

command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database "$prefix/share/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -f -t "$prefix/share/icons/hicolor" >/dev/null 2>&1 || true

# Elaris needs the Vulkan loader and a driver at run time; report what is missing rather than fail the install.
vulkan_libraries=$(ldconfig -p 2>/dev/null || true)
if ! printf '%s\n' "$vulkan_libraries" | grep -q 'libvulkan\.so\.1'; then
    note "Vulkan is missing. On Void: sudo xbps-install -S vulkan-loader mesa-dri"
elif ! printf '%s\n' "$vulkan_libraries" | grep -q 'libvulkan_'; then
    note "no Vulkan driver found. On Void: mesa-vulkan-radeon (AMD), mesa-vulkan-nouveau (NVIDIA), or xbps-query -Rs mesa-vulkan"
fi

printf 'Installed Elaris in %s\n' "$prefix"
if [ "$entry_on_path" = yes ]; then
    printf 'Run: elaris https://example.com\n'
else
    printf 'Run: %s/bin/elaris https://example.com\n' "$prefix"
    printf 'Add %s/bin to PATH to use the elaris command; the launcher entry uses the full path.\n' "$prefix"
fi
