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

Run `python3 -m unittest discover -s tests` for the builder's publish-selection tests. Before opening a PR, also run `python tools/build_repository.py` and inspect the generated `public/addons.xml`, `public/addons.xml.md5`, `public/index.html`, and add-on ZIP paths. For Worker changes, run `npm run dev` from `webhook/cloudflare-worker/` and exercise ping, rejected signature, ignored branch, and allowed push paths where possible.

Webhook-triggered source publishes must pass the builder's version guard and the add-on's tests: the incoming source add-on's root `addon.xml` version must be greater than the currently published version in Pages `addons.xml`, and every command in its `tests` list in `addons.json` (argv lists run from the add-on root, optional `test_env`) must exit 0, or the run fails. Every other add-on is rebuilt from its configured ref only if that commit passes the same checks; otherwise the builder keeps the commit recorded in the published `source-manifest.json` and logs a warning. A same-version head whose shipped files match the published package is recorded in its place, so the manifest follows the branch (also after a history rewrite). Commits that are already published are not re-tested. Manual/local repository builds without `KODI_SOURCE_REPOSITORY` and `KODI_SOURCE_SHA` apply the same keep-published fallback, and build every add-on from its configured ref when the published state cannot be fetched. The workflow installs `pytest`, `polib`, `requests`, `pillow==11.1.0` and `librsvg2-2` for the add-on tests on `ubuntu-24.04`. The Starlight texture tests compare PNG bytes, so keep Pillow and the runner image pinned; other Pillow or librsvg releases encode different bytes.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subject lines such as `Add Cloudflare Worker webhook receiver`, `Bump repository add-on version`, and `Publish Arctic Fuse dependency packages`. Follow that style and keep subjects specific to the changed behavior or published package set.

Require an `addon.xml` version bump and a news entry when a child add-on changes shipped behavior. Kodi auto-update follows add-on versions. Changes limited to tests, documentation, hooks, and other non-shipped files need no version bump. Follow `VERSIONING.md` for the complete rules.

When a `kodi.addons` publish is intended to include a new commit from a mutable child branch configured in `addons.json`, push the child commit first and verify that the remote branch resolves to the intended SHA before pushing `kodi.addons` `main` or manually dispatching the publish workflow. `push` and `workflow_dispatch` runs have no `KODI_SOURCE_REPOSITORY`/`KODI_SOURCE_SHA` payload, so `tools/build_repository.py` resolves the configured branch at runtime; verify the resulting workflow log or `source-manifest.json` records the intended SHA.

PRs should include a brief summary, any changed add-on repositories or refs, verification commands run, and notes about required secret/configuration changes. Include generated output only when it is intentionally tracked; `public/` is deployment output from the workflow.

## Security & Configuration Tips

Do not commit `wrangler.toml`, private keys, tokens, or webhook secrets. Store Worker secrets with `wrangler secret put`. Keep the GitHub App installed only on `primez-x/kodi.addons` with the minimum required repository permissions documented in `webhook/cloudflare-worker/README.md`.

## Publish Rules For Add-on Repositories

Version numbers follow `VERSIONING.md`. Each release push raises one component by 1 and resets later components to 0. Non-release pushes preserve the version. The major/minor/patch rules determine the component.

Every published add-on repository carries the same rules, enforced in three places:

1. `.githooks/pre-push` runs `.githooks/publish_check.py`, a verbatim copy of `tools/publish_check.py`. Update the master, then copy the validator to every repository. Enable the hook with `git config core.hooksPath .githooks`. Release checks require valid XML, one version step, matching news, and passing configured tests on an export of the commit. `Version-Jump:` permits upstream version adoption. Non-release pushes need no version step or news; inert shipped changes require a `No-Release:` reason, and every push still runs configured tests.
2. `.github/workflows/publish-check.yml` runs `publish_check.py ci` on tracked branch pushes and pull requests. CI classifies the pushed range. Release versions must exceed the prior branch version and the published version. Non-release corrections can pass while publication is pending.
3. `tools/build_repository.py` applies the same version, news and test rules at publish time. Test commands come from the add-on's own `.primez-publish.json` (`addons.json` entries may still carry `tests`/`test_env` as a fallback for repositories without one). `.githooks/` and `.primez-publish.json` are never packaged.
