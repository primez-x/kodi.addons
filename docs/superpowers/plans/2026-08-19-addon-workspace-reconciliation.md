# Kodi Add-on Workspace Reconciliation Plan

**Goal:** Leave every authoritative Primez Kodi repository and maintained checkout clean, current, recoverable, and free of obsolete working branches without losing legacy or stashed work.

**Interpretation of “latest”:** Fetch and account for every current remote ref; fast-forward authoritative branches where possible; merge compatible upstream changes without rewriting published history; preserve intentionally separate product/test branches; and update central pinned dependencies to their newest compatible released ref. “Latest” does not mean replacing the heavily customized PKC, Spotify, or Arctic Fuse product trees with their upstream trees.

**Interpretation of “squashed”:** Never rewrite already-published branch history. Squash only unpublished topic work or a curated patch recovered from an archive branch or stash; keep upstream merge commits when they preserve provenance.

**Safety boundary:** Do not force-push, garbage-collect, or delete unpreserved work. A child source push that is wired to the repository webhook is a Pages publication, and advancing any mutable ref in `addons.json` changes the next repository build. Prepare and verify those commits locally, but do not cross the publication/deployment boundary without explicit release authority.

## 1. Preserve recovery and legacy state

- Freeze every active and legacy local branch, remote-tracking branch, worktree, tag, stash, upstream relationship, and `addons.json` repository/ref in the audit record. Give immutable tag/SHA dependencies and reference-only clones an explicit no-change rationale.
- Before changing a repository, create an out-of-tree `git bundle --all`, verify it with `git bundle verify`, and record its hash. For dirty repositories, also create a credential-scanned filesystem snapshot and a binary patch outside every source repo.
- Restore `skin.arctic.fuse.3` branch `codex/recover-arctic-fuse-3-discarded-17` at the verified surviving commit `61d8edce47f866bacbc7a58bf86e94cbc45a9b65`; push this recovery ref because it is not a published branch.
- Convert the PKC Discover stash and both Arctic Fuse stashes into named annotated archive tags. Verify each tag points to the exact stash commit, push the tags, then drop the corresponding stash entries.
- For each dirty legacy clone under `C:\Users\Matt\Documents\Addons`, tag every unique local or remote-tracking tip, capture tracked and untracked state in one named stash commit, tag that commit, and push the archive tags over SSH. Verify every old tip is reachable from a retained or pushed archive ref before removing any local ref or stash entry.
- Keep the legacy clones as archived evidence checkouts. Do not reset them, repoint their stale branches, delete them, or push their HTTPS branch tips merely to make them look current. Their authoritative current replacements are the active SSH clones.
- Evidence already shows the legacy work is not the live CoreELEC source: 21 of 28 dirty Spotify paths match the active tree and none match legacy; 24 of 28 Arctic Fuse paths match active and none match legacy; 115 of 117 NextTrack paths match active and none match legacy. Archive rather than merge these older implementations.

## 2. Reconcile low-risk repositories

- `plugin.video.plexkodiconnect`: fast-forward `python3-beta` to origin v3.12.53, inspect and remove the entire generated `tests/__pycache__/` tree, run focused service and Discover tests, and confirm the archived stash is superseded by the current Discover implementation. Finish with `status --short --untracked-files=all` and tracked `.pyc`/secret checks.
- `service.smartsubtitles`: fast-forward `main` to origin v0.5.0 and run its test suite.
- `service.nexttrack`: keep `main` at v1.0.2, verify the old compatibility branch is contained, then delete that local branch.
- PKC helper repos: retain their reference-only topology; verify published tag `3.0.2` remains the newest tag.
- `plugin.audio.YouTubeMusic4Kodi`: retain its clean single-commit placeholder `main`; it contains no Kodi add-on manifest or unpublished branches to merge.

## 3. Reconcile Spotify

- Commit the validated hidden paging-continuation guard and tests on a temporary integration branch, rebase that one unpublished commit onto origin’s v1.0.38 authentication recovery, and resolve `addon.xml` to v1.0.39 with both changelog entries.
- Run the complete available unit suite, compilation, formatting, XML/version checks, and `git diff --check`.
- Compare every source-tracked candidate file with the installed CoreELEC v1.0.39 tree after normalizing line endings. The known `main_service.py` difference is the newer queued-playback handoff retained by source plus the device’s auth overlay; document whether each difference is intentionally promoted or intentionally retired.
- Keep the verified result on `reconcile/20260819-spotify`; push that non-published candidate branch and read back its SHA. Do not fast-forward or push `master` because that promotion publishes the add-on.

## 4. Reconcile TMDb Helper while preserving branch contracts

- Merge `upstream/nexus` v6.16.3 into `nexus`; resolve the sole predicted conflict in `addon.xml` to a fork version newer than upstream and published v6.16.2.1, while retaining the CoreELEC mmap fix.
- Build `reconcile/20260819-tmdb-nexus` from `origin/nexus`, then merge that verified source candidate into `reconcile/20260819-tmdb-nexus-tests` based on `origin/nexus-tests`. Preserve only the four intended test-file differences and use the same source version and implementation.
- Verify source trees are equivalent where intended and run the database lifecycle/regression tests from `nexus-tests`.
- Once the lifecycle source and test branch tips are proven ancestors of their respective authoritative branches, delete those obsolete codex branches locally and remotely. Do not merge test-only history into `nexus`.
- Push only the two non-published candidate branches and read back their SHAs. Stop before updating `nexus` or `nexus-tests`; `nexus` is a mutable manifest ref and changes the next Pages build.

## 5. Reconcile Arctic Fuse without flattening product history

- Fast-forward local `omega` from `76b2892` to `origin/omega` at `f19c66c` first and verify the three fork-only commits. Then merge the 11 new upstream commits into `reconcile/20260819-skin-omega`, recompute the overlap inventory, and preserve those fork commits without rebasing or force-pushing.
- Treat `primez` as an independent product. Squash the two-commit `codex/coreelec-arctic-fuse-performance` branch onto `reconcile/20260819-skin-primez` based on `origin/primez`; require the resulting tree to equal `f7828e9` and retain v3.2.68 plus its shortcut rebuild regression test.
- Inventory the separate 48-commit upstream compatibility delta (67 paths, 10 overlapping Primez paths) on its own candidate. Do not merge that wholesale into the performance candidate or call `primez` stale solely because it differs from `omega`; promote only individually reviewed upstream changes that preserve Primez-specific Plex, Spotify, NextTrack, poster-wall, and seasonal behavior.
- `feature/poster-wall-tag-reorder` is already an ancestor of `primez`; after verification, delete the redundant remote branch without replaying it.
- Run XML parsing, JSON parsing, shortcut rebuild tests, repository checks, and diff sanity checks. A live CoreELEC visual pass is required before pushing `primez` because that push immediately publishes the skin.
- Push only the non-published skin candidate branches and the safe updated `omega` ref. Keep the performance branch until `primez` is actually promoted. Stop before a `primez` push or live installation.

## 6. Reconcile Up Next

- Preserve the stale `addon-nl` tip in an archive tag.
- On `reconcile/20260819-upnext`, copy only the six-line `addon.xml` Dutch `<summary lang="nl_NL">` and `<description lang="nl_NL">` block from `5d39419`. Do not import its `README.md` hunk or its `addon.xml` v1.1.3 date rewrite. Bump current `addon.xml` to v1.1.14 with a concise Dutch-metadata changelog entry.
- Run pytest/tox scopes available in the current environment plus XML/add-on checks.
- Push the candidate branch and archive tag, then delete `addon-nl` locally and remotely only after read-back verification. Stop before updating `master` because it is a mutable manifest ref.

## 7. Reconcile the central repository

- Add `public/` to `.gitignore`; it is workflow deployment output and should not make local status dirty.
- Update `script.skinvariables` from v2.2.1 to its current released v2.2.2. Keep all other dependency refs because their configured tags/SHAs are already current; the pinned TextureMaker SHA is v0.2.11 and newer than its latest tag.
- Commit this plan, its integrity packet, `.gitignore`, and the dependency update on `reconcile/20260819-kodi-addons`; push that non-published candidate branch so `docs/` is intentional and the worktree is clean.
- Local child tests and package checks must not be represented as an official central build. For pre-publication integration, use a temporary copy with a candidate-only manifest whose refs are the pushed candidate branches; write output outside the source repo and label it non-release evidence.
- Only after authorized authoritative child tips are remotely available, run the unmodified `python tools/build_repository.py` and verify XML parsing, byte-correct MD5, ZIP integrity, monotonic versions, and `source-manifest.json` SHAs. Remove the stale untracked `public/` directory after confirming it contains only generated output; never track it.
- Stop before updating `kodi.addons/main`, which deploys GitHub Pages.

## 8. Final branch and remote audit

- Fetch with prune and verify every retained local branch has an intended upstream and zero unexplained divergence.
- Verify every deleted branch is either an ancestor of a retained branch or preserved by an exact archive tag.
- Verify all active and legacy worktrees have empty porcelain status, all stashes are empty after tagged preservation, remotes use SSH, no `.pyc` or credentials are tracked, and no open PR or unexplained GitHub branch remains.
- Verify every repository/ref in `addons.json`; record immutable current tag/SHA dependencies as no-change, and distinguish the reference-only PKC helper clones from owned mutable forks.
- After explicit publication authority, promote the prepared candidates with fast-forward-only or reviewed merge updates in dependency order, verify remote SHAs, observe each workflow, rebuild/promote `kodi.addons`, and verify live `addons.xml`, `addons.xml.md5`, `source-manifest.json`, and affected ZIP URLs.
