# Primez Kodi Add-ons

This repository publishes a Kodi add-on repository to GitHub Pages:

https://primez-x.github.io/kodi.addons/

Install the repository add-on in Kodi from:

https://primez-x.github.io/kodi.addons/repository.primez.addons/repository.primez.addons-1.0.0.zip

## How it works

- `addons.json` lists the source add-on repositories and branches to publish.
- `tools/build_repository.py` downloads each source repository archive, packages it as a Kodi add-on zip, and generates `addons.xml` plus `addons.xml.md5`.
- `.github/workflows/publish.yml` deploys the generated static repository to GitHub Pages.
- Source repository webhooks call a tiny receiver, which validates the GitHub signature and triggers this repository with `repository_dispatch`.

## Required one-time GitHub setup

1. In this repository, open **Settings > Pages** and set the source to **GitHub Actions**.
2. Deploy the webhook receiver in `webhook/cloudflare-worker`.
3. Create a GitHub App installed only on `primez-x/kodi.addons` with **Contents: read and write**. The webhook receiver uses that app to mint short-lived installation tokens.
4. Add repository webhooks to the source add-on repositories. Point them at the receiver URL, use the receiver's webhook secret, select only the **Pushes** event, and leave them active.

No source add-on repository needs a PAT or an Actions secret.

## Tracked add-ons

- `primez-x/plugin.video.plexkodiconnect` from `python3-beta`
- `primez-x/plugin.audio.spotifykodiconnect` from `master`
- `primez-x/skin.arctic.fuse.3` from `omega`
- `primez-x/service.nexttrack` from `main`

## Published support packages

The repository also publishes pinned Jurial dependency packages needed by Arctic Fuse 3 so Kodi can install the Primez skin without relying on the Jurial repository for these packages:

- `jurialmunkey/resource.font.robotocjksc` from `v0.0.3`
- `jurialmunkey/script.module.infotagger` from `v0.0.8`
- `jurialmunkey/script.module.jurialmunkey` from `v0.2.35`
- `jurialmunkey/script.skinvariables` from `v2.2.1`
- `jurialmunkey/script.texturemaker` from commit `a535b1c2924c121c0b1e1a3ea88685f027ec17fe`
- `jurialmunkey/plugin.video.themoviedb.helper` from `v6.15.6`

Run the **Publish Kodi repository** workflow manually any time you want to rebuild the repository without waiting for a source add-on push.
