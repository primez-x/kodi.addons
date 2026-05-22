# Primez Kodi Add-ons

This repository publishes a Kodi add-on repository at:

https://primez-x.github.io/kodi.addons/

Install the repository add-on in Kodi from:

https://primez-x.github.io/kodi.addons/repository.primez.addons/repository.primez.addons-1.0.0.zip

## How it works

- `addons.json` lists the source add-on repositories and branches to publish.
- `tools/build_repository.py` downloads each source repository archive, packages it as a Kodi add-on zip, and generates `addons.xml` plus `addons.xml.md5`.
- `.github/workflows/publish.yml` deploys the generated static repository to GitHub Pages.
- Each source add-on repo can trigger this repository with `repository_dispatch` after a push.

## Required one-time GitHub setup

1. In this repository, open **Settings > Pages** and set the source to **GitHub Actions**.
2. Create a fine-grained personal access token that can access only `primez-x/kodi.addons` with **Contents: read and write**.
3. Add that token as an Actions secret named `KODI_REPO_DISPATCH_TOKEN` in each source add-on repository.

The source add-on repositories are public, so this central publisher does not need a separate read token for them.

## Tracked add-ons

- `primez-x/plugin.video.plexkodiconnect` from `python3-beta`
- `primez-x/plugin.audio.spotifykodiconnect` from `master`
- `primez-x/skin.arctic.fuse.3` from `omega`

Run the **Publish Kodi repository** workflow manually any time you want to rebuild the repository without waiting for a source add-on push.
