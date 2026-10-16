# Versioning Rules For Primez Add-ons

Every push to an add-on's tracked branch that changes a shipped file is one release: Kodi updates by version
number, not by commit. These rules decide the next version deterministically.
`publish_check.py` (pre-push hook, CI and publish) enforces the mechanical part.

## Pushes that are not releases

A push that does not change what the deployed add-on does is not a release and
must **not** bump the version, so Kodi is not offered an update that changes
nothing. Two kinds:

- **Only non-shipped files changed**: tests, CI and hooks (`.github`, `.githooks`),
  `docs`, any Markdown (`CLAUDE.md`, `AGENTS.md`, READMEs), dev tool configs
  (`Makefile`, `tox.ini`, `.pylintrc`, `requirements*.txt`, …) and
  `.primez-publish.json`. The full list is `NON_SHIPPED_PATTERNS` in
  `publish_check.py`, kept equal to the publish's `DEFAULT_EXCLUDES`, so none of
  these are in the zip. Detected automatically.
- **Shipped files changed without any effect**: comments, formatting, renaming a
  local variable, removing dead code. Add `No-Release: <reason>` to the message
  of the commit at the tip of the push. Anything a user or another add-on could
  notice (behaviour, strings, layout, art, settings) is a release, whatever the
  size.

The pre-push hook and CI accept a non-release without a version step or news entry
(its tests still run); the publish keeps the published package, and the change
ships with the next real release. Changing `addon.xml`'s version always makes the
push a release.

## One step per push

A push raises the version by exactly one step from the branch tip it replaces:
raise **one** component by 1 and reset every component to its right to 0. Keep
the same number of components.

| From      | Patch     | Minor     | Major     | Rejected                     |
|-----------|-----------|-----------|-----------|------------------------------|
| `1.4.2`   | `1.4.3`   | `1.5.0`   | `2.0.0`   | `1.4.4`, `1.5.2`, `1.4.2.1`  |

A push may contain several commits; only the version at its tip counts, and the
first line of `<news>` must name that version (in the add-on's existing format,
e.g. `v1.4.3` or `version 1.4.3 (beta only):`). Bundle related changes into one
push rather than releasing each commit.

## Which component to raise

Pick the **highest** level that any change in the push qualifies for.

**Major (`x`)** — users or other add-ons must do something, or something breaks:
- raises the minimum Kodi or Python version, or drops a platform;
- removes a feature, setting, view or skin window, or renames an add-on id;
- removes or renames a window property, plugin route or setting another add-on
  (skin ↔ PlexKodiConnect / Spotify / TMDb Helper / Up Next / Next Track) reads;
- needs a database reset, full resync, re-pairing or settings reset.

**Minor (`y`)** — new or changed behaviour a user can see, nothing breaks:
- a new feature, setting, widget, view, menu entry or skin option;
- a deliberate behaviour change (different default, different selection logic);
- a new window property, plugin route or setting other add-ons may use;
- a dependency version bump in `addon.xml`, or merging upstream changes that bring
  features.

**Patch (`z`)** — everything else:
- bug fixes, performance and reliability work, crash/log fixes;
- refactors, tests, CI/tooling, packaging and documentation;
- translation updates and small visual polish within existing layouts.

When unsure between two levels, take the higher one.

## Forks of upstream add-ons

- **Four-component forks** (`plugin.video.themoviedb.helper`, e.g. `6.17.3.3`; also
  `script.xbmc.unpausejumpback`, `script.service.playbackresumer`): the
  first three components are the upstream version the fork is based on; the
  fourth is the fork revision. Every fork release raises only the fourth. Merging
  a newer upstream sets the first three to upstream's and the fourth to `1`.
- **Three-component forks with their own line** (PlexKodiConnect, Arctic Fuse 3,
  Up Next): apply the rules above to the fork's own version. When merging upstream,
  raise minor (or major, if upstream's change is breaking), unless upstream's version
  is already higher, in which case adopt upstream's version.
- **Adopting an official add-on**: publish the upstream version with fork revision `1`
  (`3.0.8` becomes `3.0.8.1`) and declare `Version-Jump`. Kodi updates an add-on from
  the official repository only from its install source, so each box reinstalls the
  add-on once from this repository; later releases then arrive as normal updates.

Adopting an upstream version is the one allowed jump: add a line
`Version-Jump: <reason>` (e.g. `Version-Jump: adopt upstream 6.18.0`) to the
message of the commit at the tip of the push. The version must still increase.

## Never

- Never lower a version or reuse a published one.
- Never skip versions to "make room" or to reset a large patch number — a large
  patch number is fine; move to the next minor only when a release qualifies.
- Never push a change that affects the deployed add-on without a version step and
  a news entry, and never use `No-Release` to skip one.
- Never bump the version for a push that does not change the deployed add-on.
