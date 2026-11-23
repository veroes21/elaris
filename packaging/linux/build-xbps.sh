#!/bin/sh
# Packages the Linux release tree as a Void Linux package (.xbps) plus the repository index xbps-install reads.
# The tree keeps its own layout under /usr/lib/elaris, because Ladybird's helpers find ../share/Lagom beside themselves.
set -eu

APP_ID="org.elarisbrowser.Elaris"
PACKAGE_ROOT="/usr/lib/elaris"
# Void's portable build tools are statically linked against musl, so they run on any host.
STATIC_TOOLS_URL="https://repo-default.voidlinux.org/static/xbps-static-latest.x86_64-musl.tar.xz"

usage() {
    cat <<'EOF'
Usage: ./build-xbps.sh --version VERSION [--tree DIR] [--output DIR] [--revision N]

Packages the Linux release tree as elaris-<version>_<revision>.x86_64.xbps and
writes the repository index that xbps-install reads beside it.

    --version VERSION   release version, such as v0.1.0-alpha.1
    --tree DIR          prefix tree to package (default: build/linux/Elaris)
    --output DIR        where to write the package (default: dist)
    --revision N        package revision (default: 1)
    --xbps-tools DIR    directory holding xbps-create, xbps-rindex and xbps-query
    -h, --help          show this message

The tools come from --xbps-tools, from XBPS_TOOLS_DIR, or from PATH. When none
has them, Void's static tools are downloaded into build/tools/.
EOF
}

fail() {
    printf 'elaris: %s\n' "$1" >&2
    exit 1
}

note() {
    printf 'elaris: %s\n' "$1" >&2
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)

version=""
tree="$repo_root/build/linux/Elaris"
output="$repo_root/dist"
revision="1"
tools_dir="${XBPS_TOOLS_DIR:-}"
maintainer="${XBPS_MAINTAINER:-veroes21 <veroes21@users.noreply.github.com>}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --version)
            [ "$#" -ge 2 ] || fail "--version needs a value"
            version="$2"
            shift 2
            ;;
        --version=*)
            version="${1#--version=}"
            shift
            ;;
        --tree)
            [ "$#" -ge 2 ] || fail "--tree needs a directory"
            tree="$2"
            shift 2
            ;;
        --tree=*)
            tree="${1#--tree=}"
            shift
            ;;
        --output)
            [ "$#" -ge 2 ] || fail "--output needs a directory"
            output="$2"
            shift 2
            ;;
        --output=*)
            output="${1#--output=}"
            shift
            ;;
        --revision)
            [ "$#" -ge 2 ] || fail "--revision needs a value"
            revision="$2"
            shift 2
            ;;
        --revision=*)
            revision="${1#--revision=}"
            shift
            ;;
        --xbps-tools)
            [ "$#" -ge 2 ] || fail "--xbps-tools needs a directory"
            tools_dir="$2"
            shift 2
            ;;
        --xbps-tools=*)
            tools_dir="${1#--xbps-tools=}"
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

[ -n "$version" ] || {
    usage >&2
    fail "--version is required"
}
case "$revision" in
    ""|*[!0-9]*) fail "the revision must be a number, such as 1" ;;
esac

# A package file name is <name>-<version>_<revision>.<arch>.xbps, so a dash inside the version would split it wrong.
pkg_version=$(printf '%s' "$version" | sed -e 's/^v//' -e 's/-/./g')
[ -n "$pkg_version" ] || fail "'$version' has no version in it"
case "$pkg_version" in
    *[!0-9A-Za-z._]*) fail "'$version' cannot be a package version; use letters, digits, dots and dashes" ;;
esac

for entry in bin lib libexec share; do
    [ -d "$tree/$entry" ] || fail "$tree has no $entry directory; run ./elaris bundle first"
done
[ -x "$tree/bin/elaris" ] || fail "$tree/bin/elaris is missing; run ./elaris bundle first"

# --- the xbps tools -----------------------------------------------------------------------------------------------

find_tools_in() {
    xbps_create="$1/xbps-create"
    xbps_rindex="$1/xbps-rindex"
    xbps_query="$1/xbps-query"
    [ -x "$xbps_create" ] && [ -x "$xbps_rindex" ] && [ -x "$xbps_query" ]
}

download_tools() {
    download="$repo_root/build/tools/xbps-static"
    find_tools_in "$download/usr/bin" && return 0
    rm -rf "$download"
    mkdir -p "$download"
    archive="$repo_root/build/tools/xbps-static.tar.xz"
    note "downloading Void's static xbps tools…"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL -o "$archive" "$STATIC_TOOLS_URL"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$archive" "$STATIC_TOOLS_URL"
    else
        fail "curl or wget is needed to download Void's xbps tools; on Void install xbps, or pass --xbps-tools DIR"
    fi
    tar -C "$download" -xf "$archive"
    rm -f "$archive"
    find_tools_in "$download/usr/bin"
}

if [ -n "$tools_dir" ]; then
    find_tools_in "$tools_dir" || fail "$tools_dir does not hold xbps-create, xbps-rindex and xbps-query"
elif command -v xbps-create >/dev/null 2>&1 && command -v xbps-rindex >/dev/null 2>&1 &&
    command -v xbps-query >/dev/null 2>&1; then
    xbps_create=$(command -v xbps-create)
    xbps_rindex=$(command -v xbps-rindex)
    xbps_query=$(command -v xbps-query)
else
    download_tools || fail "could not download Void's xbps tools; install xbps or pass --xbps-tools DIR"
fi

# --- staging ------------------------------------------------------------------------------------------------------

# Built from scratch each time, so a package never carries a file the tree no longer has.
stage="$repo_root/build/xbps/root"
rm -rf "$stage"
mkdir -p "$stage$PACKAGE_ROOT" "$stage/usr/bin" "$stage/usr/share/applications" "$stage/usr/share/doc/elaris"

# bin/, lib/, libexec/ and share/ stay siblings: a helper in libexec finds its resources at ../share/Lagom.
cp -a "$tree/bin" "$tree/lib" "$tree/libexec" "$tree/share" "$stage$PACKAGE_ROOT/"
ln -s "$PACKAGE_ROOT/bin/elaris" "$stage/usr/bin/elaris"
ln -s "$PACKAGE_ROOT/share/applications/$APP_ID.desktop" "$stage/usr/share/applications/$APP_ID.desktop"

# The icon theme reads /usr/share/icons, so link each icon there instead of shipping a second copy.
icon_root="$tree/share/icons/hicolor"
if [ -d "$icon_root" ]; then
    find "$icon_root" -type f | while read -r icon; do
        relative=${icon#"$icon_root"/}
        mkdir -p "$stage/usr/share/icons/hicolor/$(dirname -- "$relative")"
        ln -s "$PACKAGE_ROOT/share/icons/hicolor/$relative" "$stage/usr/share/icons/hicolor/$relative"
    done
fi

[ -f "$tree/INSTALL-VOID.md" ] && cp "$tree/INSTALL-VOID.md" "$stage/usr/share/doc/elaris/INSTALL-VOID.md"
[ -f "$repo_root/LICENSE" ] && cp "$repo_root/LICENSE" "$stage/usr/share/doc/elaris/LICENSE"

# A fixed timestamp keeps two packages of the same tree identical when the caller asks for it.
if [ -n "${SOURCE_DATE_EPOCH:-}" ]; then
    find "$stage" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
fi

# --- packaging ----------------------------------------------------------------------------------------------------

mkdir -p "$output"
# Absolute from here on, because xbps-create runs from inside the output directory.
output=$(CDPATH= cd -- "$output" && pwd)
package="elaris-${pkg_version}_${revision}.x86_64.xbps"
rm -f "$output/$package" "$output/$package.sha256"

# xbps-create writes the package into the working directory and names it after the pkgver.
cd "$output"
"$xbps_create" \
    --architecture x86_64 \
    --pkgver "elaris-${pkg_version}_${revision}" \
    --desc "Browser written in Rust, powered by Ladybird's engine" \
    --long-desc "Elaris is a cross-platform browser written in Rust. Web content runs in Ladybird's engine.
It needs the Vulkan loader and a Mesa Vulkan driver at run time; see /usr/share/doc/elaris/INSTALL-VOID.md." \
    --homepage "https://github.com/elarisbrowser/elaris" \
    --license "GPL-3.0-only" \
    --maintainer "$maintainer" \
    --dependencies "vulkan-loader>=0" \
    --build-options "release tree from the Elaris release workflow" \
    "$stage"

[ -f "$output/$package" ] || fail "xbps-create did not write $output/$package"

# xbps-install reads this index to find the package in a directory of its own.
"$xbps_rindex" --add "$output/$package" >/dev/null

files=$("$xbps_query" --repository "$output" --files elaris 2>/dev/null || true)
for expected in /usr/bin/elaris "$PACKAGE_ROOT/bin/elaris"; do
    printf '%s\n' "$files" | grep -q "$expected" ||
        fail "the package does not list $expected; check what xbps-create staged"
done

(cd "$output" && sha256sum "$package" > "$package.sha256")

printf 'Wrote %s\n' "$output/$package"
printf 'Wrote %s\n' "$output/$package.sha256"
printf 'Install with: sudo xbps-install --repository=%s elaris\n' "$output"
