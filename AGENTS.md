# Repository Guidelines

## Project Structure & Module Organization

This repository publishes a static Kodi add-on repository to GitHub Pages. The top-level `addons.json` is the manifest for source add-on repositories, pinned refs, and repository metadata. `tools/build_repository.py` downloads those sources, packages add-on ZIPs, copies repository assets, and writes generated output to `public/` by default. `.github/workflows/publish.yml` runs the builder and deploys `public/` to Pages. The webhook receiver lives in `webhook/cloudflare-worker/`, with Worker source in `src/index.js` and deployment config based on `wrangler.toml.example`.

## Build, Test, and Development Commands

- `python tools/build_repository.py`: builds the Kodi repository into `public/`.
- `$env:KODI_OUTPUT_DIR='dist'; python tools/build_repository.py`: builds into a temporary alternate output directory on PowerShell.
- `cd webhook/cloudflare-worker; npm install`: installs Worker dependencies.
- `cd webhook/cloudflare-worker; npm run dev`: starts the Cloudflare Worker locally with Wrangler.
- `cd webhook/cloudflare-worker; npm run deploy`: deploys the Worker.

The builder can use `GITHUB_TOKEN` to avoid unauthenticated GitHub API rate limits.

## Coding Style & Naming Conventions

Python code uses 4-space indentation, standard-library APIs, `pathlib.Path`, and small single-purpose functions. Keep generated XML and HTML deterministic by sorting file/package output where practical. JavaScript Worker code uses ES modules, 2-space indentation, `const`/`let`, async functions, and JSON responses with explicit status codes. Keep environment variable names uppercase, for example `WEBHOOK_SECRET`, `GITHUB_APP_ID`, and `ALLOWED_REPOS_JSON`.

## Testing Guidelines

There is no formal test suite yet. Before opening a PR, run `python tools/build_repository.py` and inspect the generated `public/addons.xml`, `public/addons.xml.md5`, `public/index.html`, and add-on ZIP paths. For Worker changes, run `npm run dev` from `webhook/cloudflare-worker/` and exercise ping, rejected signature, ignored branch, and allowed push paths where possible.

Webhook-triggered source publishes must pass the builder's version guard: the incoming source add-on's root `addon.xml` version must be greater than the currently published version in Pages `addons.xml`. Manual/local repository builds without `KODI_SOURCE_REPOSITORY` and `KODI_SOURCE_SHA` should continue to work without this guard.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subject lines such as `Add Cloudflare Worker webhook receiver`, `Bump repository add-on version`, and `Publish Arctic Fuse dependency packages`. Follow that style and keep subjects specific to the changed behavior or published package set.

Do not merge or dispatch a child add-on branch update unless that child repo commit includes the required `addon.xml` version bump. Kodi auto-update tracks generated add-on versions, not Git branch heads, and `tools/build_repository.py` intentionally fails webhook publishes when the source version does not increase.

When a `kodi.addons` publish is intended to include a new commit from a mutable child branch configured in `addons.json`, push the child commit first and verify that the remote branch resolves to the intended SHA before pushing `kodi.addons` `main` or manually dispatching the publish workflow. `push` and `workflow_dispatch` runs have no `KODI_SOURCE_REPOSITORY`/`KODI_SOURCE_SHA` payload, so `tools/build_repository.py` resolves the configured branch at runtime; verify the resulting workflow log or `source-manifest.json` records the intended SHA.

PRs should include a brief summary, any changed add-on repositories or refs, verification commands run, and notes about required secret/configuration changes. Include generated output only when it is intentionally tracked; `public/` is deployment output from the workflow.

## Security & Configuration Tips

Do not commit `wrangler.toml`, private keys, tokens, or webhook secrets. Store Worker secrets with `wrangler secret put`. Keep the GitHub App installed only on `primez-x/kodi.addons` with the minimum required repository permissions documented in `webhook/cloudflare-worker/README.md`.
