# Versioning Rules For Primez Add-ons

Every push to an add-on's tracked branch is one release: Kodi updates by version
number, not by commit. These rules decide the next version deterministically.
`publish_check.py` (pre-push hook, CI and publish) enforces the mechanical part.

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

- **Four-component forks** (`plugin.video.themoviedb.helper`, e.g. `6.17.3.3`): the
  first three components are the upstream version the fork is based on; the
  fourth is the fork revision. Every fork release raises only the fourth. Merging
  a newer upstream sets the first three to upstream's and the fourth to `1`.
- **Three-component forks with their own line** (PlexKodiConnect, Arctic Fuse 3,
  Up Next): apply the rules above to the fork's own version. When merging upstream,
  raise minor (or major, if upstream's change is breaking), unless upstream's version
  is already higher, in which case adopt upstream's version.

Adopting an upstream version is the one allowed jump: add a line
`Version-Jump: <reason>` (e.g. `Version-Jump: adopt upstream 6.18.0`) to the
message of the commit at the tip of the push. The version must still increase.

## Never

- Never lower a version or reuse a published one.
- Never skip versions to "make room" or to reset a large patch number — a large
  patch number is fine; move to the next minor only when a release qualifies.
- Never push to a tracked branch without a version step and a news entry.
