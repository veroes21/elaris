# Installing Elaris on Void Linux

Elaris publishes two things for Linux: a Void package, `elaris-<version>_1.x86_64.xbps`, and the
`Elaris-<version>-linux-x86_64.tar.gz` archive it is built from. Both carry Ladybird's engine, its helper processes and
the libraries they link.

## Requirements

- **glibc, x86_64.** The archive links glibc 2.43 or newer, so it runs on Void's glibc flavour only; the **musl**
  flavour cannot run it. Check with `ldd --version | head -1`, and build from source on musl.
- **Vulkan.** Install the loader and the Mesa driver that matches your GPU:

  ```sh
  sudo xbps-install -S vulkan-loader mesa-dri
  sudo xbps-install -S mesa-vulkan-radeon    # AMD
  sudo xbps-install -S mesa-vulkan-nouveau   # NVIDIA through nouveau
  xbps-query -Rs mesa-vulkan                 # Intel and other drivers
  ```

## Install the package

The release publishes the package, its `.sha256` checksum and the repository index `x86_64-repodata`. Keep all three in
one directory and let xbps install from it:

```sh
mkdir elaris-repo && cd elaris-repo
# copy elaris-<version>_1.x86_64.xbps, elaris-<version>_1.x86_64.xbps.sha256 and x86_64-repodata here
sha256sum -c elaris-<version>_1.x86_64.xbps.sha256
sudo xbps-install --repository="$PWD" elaris
```

`xbps-install` pulls in `vulkan-loader`; the Mesa driver is the one you chose above. The package installs the engine
in `/usr/lib/elaris`, puts `/usr/bin/elaris` on your `PATH`, and links the launcher entry and the icons to the tree, so
the browser and the application menu both work and xbps keeps track of every installed file.

Install a newer package the same way, from the directory holding its index, and remove it with:

```sh
sudo xbps-remove -R elaris
```

The package and its index are not signed, so check the `.sha256` before installing.

## Install the tarball

```sh
tar xf Elaris-<version>-linux-x86_64.tar.gz
cd Elaris
./install.sh                              # into ~/.local
sudo ./install.sh --prefix /opt/elaris    # system-wide; add /opt/elaris/bin to PATH
```

The installer copies `bin/`, `lib/`, `libexec/` and `share/`, refreshes the desktop database, points the launcher
entry at the installed binary when the prefix is not on `PATH`, and warns about a missing Vulkan loader or driver.
It merges into an existing install instead of deleting it.

## Run

```sh
elaris https://example.com
```

Elaris also appears as **Elaris** in the application menu. It keeps data in `$XDG_DATA_HOME/Elaris` and settings in
`$XDG_CONFIG_HOME/elaris/config.toml`.

## Notes

- Pre-alpha: expect rough edges.
- On tiling window managers Elaris uses system decorations and keeps the toolbar visible. See the README for
  `ELARIS_LINUX_TITLEBAR` and `ELARIS_LINUX_DECORATIONS`.
- The downloads are not signed. Verify the `.sha256` file published beside them before running.
