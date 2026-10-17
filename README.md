# Primez Kodi Add-ons

This repository packages the Primez Kodi add-ons and publishes the packages to [GitHub Pages](https://primez-x.github.io/kodi.addons/).
Kodi installs and updates the add-ons through `repository.primez.addons`.

## Install in Kodi

1. Enable **Unknown sources** in Kodi's system add-on settings.
2. Download the [Primez repository ZIP](https://primez-x.github.io/kodi.addons/repository.primez.addons/repository.primez.addons-1.0.0.zip).
3. Select **Add-ons > Install from zip file** and choose the downloaded ZIP.
4. Select **Install from repository > Primez Kodi Add-ons**.
5. Install the required add-ons from their categories.

Kodi resolves the packaged dependencies through the repository.
Keep automatic updates enabled for the installed add-ons.

## Maintained packages

[`addons.json`](addons.json) defines the source repositories and tracked branches.

| Package | Purpose | Tracked branch |
| --- | --- | --- |
| [PlexKodiConnect](https://github.com/primez-x/plugin.video.plexkodiconnect) | Plex media in Kodi's native library | `python3-beta` |
| [SpotifyKodiConnect](https://github.com/primez-x/plugin.audio.spotifykodiconnect) | Spotify playback and library access | `master` |
| [Starlight](https://github.com/primez-x/starlight) | High tech space themed Kodi skin, built on Arctic Fuse 3 | `main` |
| [Arctic Fuse 3 images](https://github.com/primez-x/resource.images.arctic.fuse.3) | Shared skin artwork | `main` |
| [TMDb Helper](https://github.com/primez-x/plugin.video.themoviedb.helper) | Metadata, browsing, and player integration | `nexus` |
| [Up Next](https://github.com/primez-x/service.upnext) | Next-episode prompts | `master` |
| [Next Track](https://github.com/primez-x/service.nexttrack) | Next-track prompts and queue control | `main` |
| [Smart Subtitles](https://github.com/primez-x/service.smartsubtitles) | Automatic subtitle selection | `main` |
| [SmartTube](https://github.com/primez-x/plugin.video.smarttube) | YouTube playback without API keys, with SponsorBlock | `main` |
| [Unpause Jumpback](https://github.com/primez-x/script.xbmc.unpausejumpback) | Jumps back after pause or fast-forward | `primez` |
| [Playback Resumer](https://github.com/primez-x/script.service.playbackresumer) | Resume points and resume after restart | `primez` |

The manifest also pins these support packages:

- PlexKodiConnect Movies and TV Shows: `croneter` repositories at `3.0.2`.
- `resource.font.robotocjksc`: `v0.0.3`.
- `script.module.infotagger`: `v0.0.8`.
- `script.module.jurialmunkey`: `v0.2.35`.
- `script.skinvariables`: `v2.2.2`.
- `script.texturemaker`: the commit recorded in `addons.json`.

## Publish an add-on update

1. Match the tracked branch in all three places: the add-on's `.primez-publish.json` `branch`,
   the central `addons.json` `ref`, and the Worker's `DEFAULT_ALLOWED_REPOS` branch.
   If `ALLOWED_REPOS_JSON` overrides the Worker defaults, update that branch map too.
2. Enable the local publish hook:

   ```bash
   git config core.hooksPath .githooks
   ```

3. For a change to shipped behavior, advance `addon.xml` by one version step.
4. Add the new version to the first `<news>` line.
5. Commit and push the add-on changes.
6. Confirm the remote tracked branch resolves to the pushed commit.
7. Check the central **Publish Kodi repository** workflow and the published source manifest.

Follow [VERSIONING.md](VERSIONING.md) for version steps, fork versions, and declared exceptions.
README-only changes do not need a version bump because Markdown files are excluded from add-on packages.
The pre-push hook and CI still run the add-on's configured checks.

A configured source webhook forwards the push through the Cloudflare receiver to this repository.
The receiver submits `repository_dispatch` with the source repository, branch, and commit SHA.
GitHub Actions then builds and publishes the repository.
Routine add-on updates do not require a Cloudflare deployment.

If the source webhook is absent or rejected, run **Publish Kodi repository** manually from [Actions](https://github.com/primez-x/kodi.addons/actions).
The GitHub CLI command is:

```bash
gh workflow run publish.yml --repo primez-x/kodi.addons --ref main
```

Push the source commit before a manual publish.
Manual runs resolve the configured branches at build time.
Confirm the intended SHA in the workflow log or [source-manifest.json](https://primez-x.github.io/kodi.addons/source-manifest.json).

## Workflow triggers and package checks

[`.github/workflows/publish.yml`](.github/workflows/publish.yml) starts from three triggers:

- A push to `main` that changes `addons.json`, `tools/**`, the publish workflow, or `README.md`.
- An `addon_updated` repository dispatch.
- A manual workflow run.

A version bump gives Kodi a newer package version; the push or dispatch starts the workflow.
The builder checks version steps, the news entry, and commands from the add-on's `.primez-publish.json`.
The builder also accepts `tests` and `test_env` from `addons.json` for sources without that policy file.

A webhook source candidate must pass the publish checks.
Other source candidates retain the published commit when a version or test check fails.
An unchanged package at the same version advances the recorded source SHA without offering a Kodi update.
Already published commits are not tested again.

## Build and check locally

Use Python 3.12 to match the GitHub Actions workflow.
Install the add-on test dependencies:

```bash
python3 -m pip install pytest polib requests
python3 -m unittest discover -s tests
python3 tools/build_repository.py
```

The builder writes `public/` by default.
Set `KODI_OUTPUT_DIR` to choose another destination:

```bash
KODI_OUTPUT_DIR=/tmp/kodi-repository python3 tools/build_repository.py
```

Set `GITHUB_TOKEN` when local builds need authenticated GitHub API access.
Inspect `addons.xml`, `addons.xml.md5`, `source-manifest.json`, `index.html`, and the generated ZIPs.
Keep generated output out of source commits.

## Source layout and shared code

- `addons.json`: package sources, refs, and repository metadata.
- `tools/build_repository.py`: source selection, checks, packaging, and static output.
- `tools/publish_check.py`: master publish guard copied to each add-on's `.githooks/`.
- `tools/service_common/`: master helper modules for Up Next and Next Track.
- `tools/sync_service_common.py`: copy shared helpers or check for source differences.
- `tests/`: repository builder tests.
- `webhook/cloudflare-worker/`: source-push receiver and local request checks.

Check the shared helpers with:

```bash
python3 tools/sync_service_common.py --check
```

The sync tool expects the add-on clones in a sibling `kodi-addons-dev/` directory by default.
Use `--addons-dir` for another clone directory.
After a master publish-guard change, copy the guard to every maintained add-on repository.

## Publisher setup

Initial setup requires GitHub Pages with **GitHub Actions** as the source.
Automatic source publishes also require the receiver, GitHub App credentials, and signed source webhooks.
See the [webhook guide](webhook/cloudflare-worker/README.md) for setup, configuration, and request checks.
The workflow publishes the static downloads; the receiver handles the source-push notification.
