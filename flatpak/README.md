# Flatpak packaging

Self-hosted build — not distributed via Flathub (Flathub does not accept
AI-generated projects).

## Releasing

`.github/workflows/build-windows.yml` builds this automatically on every
`vX.Y.Z` tag push (the same trigger `release.py` already uses for the Windows
build) and attaches `PlayDate-<version>-Linux.flatpak` to the GitHub Release —
no manual flatpak build needed per release. That job patches the manifest's
git source to build from the CI checkout itself rather than a fixed tag, so
nothing there needs updating by hand either.

## Local build (for testing changes to this manifest)

```bash
flatpak install --user flathub org.gnome.Platform//50 org.gnome.Sdk//50
flatpak-builder --user --install --force-clean build-dir io.github.robbyratpoison.PlayDate.yml
flatpak run io.github.robbyratpoison.PlayDate
```

This builds from the `playdate` module's pinned git tag (currently
`v1.5.21`), so it won't include uncommitted local changes. To test local
changes before they're committed/tagged, temporarily swap that module's
`sources` entry for:

```yaml
      - type: dir
        path: ..
        dest: src
        skip:
          - flatpak
          - .git
          - .venv
          - __pycache__
          - webview_storage
```

then revert before committing — same swap the CI job does automatically.

## Bundle for distribution

```bash
flatpak build-bundle repo PlayDate.flatpak io.github.robbyratpoison.PlayDate
```

## Permissions

Requests broad host access (`--filesystem=home`, `--talk-name=org.freedesktop.Flatpak`
for `flatpak-spawn --host`) rather than narrow portal-based access — the app's
whole job is bridging into Steam/GOG/Epic libraries and Wine prefixes that can
live anywhere under `$HOME`, the same tradeoff Lutris/Heroic/Bottles make.
This can be tightened in a later release without any architectural change —
Flatpak permissions are just `finish-args` entries, and users see/approve the
diff on update.

## Known limitations

- Wine/Proton/winetricks/7z must already be installed on the host — nothing
  is bundled. Detection and execution go through `runners/sandbox.py`
  (`flatpak-spawn --host`), see that file for why.
- BLAEO Chrome scraping isn't used by this codebase (plain `requests`/HTML
  scraping instead), so no headless browser dependency needed here.
