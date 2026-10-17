# Trakt to Plex Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` for implementation. Complete the API checks before product changes.

**Goal:** Replace the skin's remaining Trakt sources with Plex sources and preserve clear, accurate feature names.

**Architecture:** PlexKodiConnect owns Plex requests, account identity, metadata conversion, and caches. Arctic Fuse consumes those interfaces through existing controls and generators. TMDb Helper continues to provide unrelated metadata.

**Tech Stack:** Kodi skin XML, Skin Variables JSON/XML generators, Python, existing PKC request and cache modules.

**Spec:** The scope, feature map, and boundaries below define the approved behavior.

**Status:** Implementation and final candidate checks pass on Living Room. PKC 3.16.0 and skin 4.0.0 are installed from normal ZIP packages. Required independent review and publication remain pending.

**Independent review:** T3 rejected Opus, Astra, Fable, and automatic selection because those models wrote older work in this thread. The current migration writers are Sol, Sonnet, and Opus. The root requested permission for a fresh review conversation. Astra is the applicable independent fallback. No independent reviewer has examined the integrated change. Task 6 remains required.

## Scope and evidence

The original request removed the Trakt detail button and required Plex sources for the remaining Trakt features. The detail button is already removed.

The audit checked skin commit `89a983c` and PKC commit `21eeb0d5`. The skin contains 51 Trakt text matches across 18 files. Historical notes, a negative test assertion, and static references are included in that count. Fourteen localization files contain no Trakt text.

Six functional groups remain: ratings, badges, comments, the calendar switch, list search, and widget path rules.

Current PKC supports Plex Discover, Watchlist, local playlists, metadata ratings, and library progress. PKC lacks dedicated readers for Plex user reviews and custom Lists. The missing readers do not establish a Plex service limitation.

Plex documents [user reviews](https://support.plex.tv/articles/user-reviews/) and [custom Lists](https://support.plex.tv/articles/lists/). Those pages establish product features. They do not establish the request contracts for a Kodi integration.

## Feature map

| Current feature | Proposed behavior | Existing support or required work |
|---|---|---|
| Trakt rating choice and startup defaults | Offer Plex-provided ratings. Migrate existing Trakt choices in all movie and TV rating slots. Preserve unrelated provider choices. | PKC already maps audience/critic ratings. Preserve the original rating provider and scale. |
| Trakt Watchlist badges | Show Plex Watchlist membership across the five existing layout callers. | Reuse PKC item identity, per-item state, and `PlexWatchlistHint`. Expand data coverage where generic library cards lack a hint. |
| Trakt favourite badges | Keep favourites separate from Watchlist. Under the expanded scope, use membership in an existing Plex List selected for favourites. | Requires the custom Lists reader and an explicit list selection. Hide the badge until a list is selected. |
| Trakt Comments | Replace comment cards with Plex review cards. Keep the existing review display and text dialog. | Requires a verified Plex reviews reader. Preserve unrelated awards and critic-consensus cards in the same row. |
| Trakt calendar toggle | Remove the Trakt branch. Keep the existing library Next Aired mode. | The remaining library calendar uses TMDb Helper schedule data for local library shows. This is not a native Plex calendar. |
| Trakt Lists search shortcut | Replace the shortcut with My Plex Lists. Browse accessible Plex Lists and their contents. | Requires the custom Lists reader. Public list search remains outside the verified feature contract. |
| Trakt watched-seed widget rules | Retire both Trakt-specific path rules. Use existing Plex Discover widget sources for replacement widgets. | Use the actual Plex hub title. Do not label a general hub as a watched-seed recommendation. |

## Global constraints

- Keep Plex access in PKC. Add no second token store or skin HTTP client.
- Keep library PMS keys separate from cloud provider keys. Resolve identities with existing GUID and external-ID helpers.
- Reuse account-scoped caches and existing Watchlist state. Add no request for each visible tile.
- Preserve separate states for unknown membership, confirmed absence, and confirmed presence.
- Keep Watchlist restricted to movies and shows. Seasons and episodes must not receive misleading Watchlist actions.
- Keep public ratings separate from personal ratings. PKC can use the user-rating field for a version count under an existing option.
- Migrate obsolete saved values directly. Preserve unrelated custom widgets, layouts, settings, and account data.
- Keep historical release notes and the test that prohibits the removed Trakt button.
- Limit migration to the skin integration. Do not remove generic Trakt support from TMDb Helper.
- Scope excludes a Trakt account-data import, cloud list creation, and changes to Plex account preferences.
- Use the existing firmware. This plan needs no Kodi core change or firmware build.
- Use Living Room for native UI checks. Check current playback and preserve queues before UI actions.
- Apply `VERSIONING.md` separately to each changed add-on. Shipped feature additions require a minor version step and matching news.
- Release versions are PKC `3.16.0` and skin `4.0.0`. The skin major follows removal of Trakt-only settings and routes under `VERSIONING.md`.
- Declare the required PKC version in the skin manifest when the skin depends on new PKC behavior. For the audited expanded scope, require PKC `3.16.0`.
- Push a changed PKC dependency first. Verify the remote SHA and published dependency before the dependent skin release.

## Review focus

1. Account changes must clear the previous account's membership and review state.
2. Rapid focus changes must not place one title's state or reviews on another title.
3. Offline, denied, stale, empty, and incomplete responses must remain distinct.
4. Library editions and ambiguous external-ID matches must preserve the correct title and playback target.
5. Existing profiles must migrate all rating slots, saved Trakt paths, and calendar state without resetting unrelated customization.

## Task 1: Verify the additional Plex API contracts

**Applies:** Expanded scope only.

**Files:** Evidence under `/home/user/p3i-build-evidence/20261017-trakt-to-plex/`. No product changes during this task.

**Interfaces:** Produce verified read-only request contracts for reviews, accessible Lists, and List contents. Record identity fields, pagination, permissions, ordering, and response shapes.

- [x] Observe the requests used by the official Plex client. Reuse the existing account credentials privately. Use read-only queries during this task.
- [ ] Verify reviews for a library title and a cloud-only title. Check spoiler flags and account review preferences.
- [x] Verify accessible Lists and List contents. Establish whether list-name filters are local or service-supported.
- [x] Verify empty, inaccessible, and paginated responses. Preserve list order and distinguish the final page from a failed page.
- [x] Save sanitized response shapes and bounded request counts. Exclude tokens, account identifiers, private list contents, and review authors from committed fixtures.
- [ ] Record unsupported title types and missing permissions as explicit capability results.

**Native findings:** Generic Kodi library lists expose only the default unique ID. PKC now projects exact library IDs through digit-length buckets. The projection uses no metadata database writes. A larger public List exposed a nullable stream conversion failure. The correction preserves every List entry, including unavailable entries.

**Contract evidence:** `/home/user/p3i-build-evidence/20261017-trakt-to-plex/api-contracts.md` records verified live reads and source-backed preference enums.

**Pass condition:** The implementation has verified request and response contracts. Product documentation alone cannot satisfy this task. If a required contract fails, revise the affected feature map before implementation.

## Task 2: Complete the shared Plex Watchlist badges

**PKC paths:** `resources/lib/watchlist.py`, `resources/lib/discover_cache.py`, `resources/lib/entrypoint.py`, and `resources/lib/widgets.py` as required by the card source.

**Skin paths:** `1080i/Includes_Objects.xml`, all five callers in `1080i/Includes_Layouts.xml`, and `1080i/Dialog_DialogCustom.xml`.

**Interfaces:** Consume `PlexWatchlistHint`, the existing `PKC.Watchlist.Item.*` state, and exact item identity. Produce one shared Plex Watchlist overlay.

- [x] Define the failures before code: unknown state displayed as absence, stale focused state copied to other cards, account leakage, and HTTP requests per tile.
- [x] Capture native baseline behavior for a Watchlist member, a non-member, and a generic library card without a provider hint.
- [x] Extend the existing state projection for uncovered card sources. Reuse the current membership cache and batch identity resolution.
- [x] Replace the shared Trakt overlay and all five callers. Keep the settings labels consistent with Plex Watchlist.
- [x] Verify add/remove propagation, rapid focus changes, offline cache behavior, account changes, editions, and season/episode exclusion.

**Verification:** Isolated checks cover mutations, account changes, incomplete snapshots, library invalidation, editions, and publication races. Native frame comparisons verify one member and adjacent non-members during eight focus changes. All five layout callers use the same per-card group. Four other layout geometries remain unverified on the device.

**Pass condition:** Every supported card displays the correct account's membership. Unknown cards remain quiet. Rendering a populated row creates no per-tile network fan-out.

## Task 3: Replace Trakt rating choices and stored values

**Paths:** `1080i/Dialog_DialogCustom.xml`, `1080i/Includes_Info.xml`, `1080i/Includes_Actions.xml`, `shortcuts/skinvariables-startup.json`, and the existing PKC metadata conversion only where necessary.

**Interfaces:** Consume PKC rating values with their source and scale. Preserve personal ratings as a separate field.

- [x] Define expected behavior for each of three rating slots in Movies and TV Shows, including stored Trakt values and blank values.
- [x] Add the Plex source choice and migrate Trakt values through the existing startup rules.
- [x] Update startup defaults and reset actions for all slots. Preserve unrelated user choices.
- [x] Display the actual source and scale. Avoid a duplicate rating when another slot selects the same provider value.
- [x] Verify a library title, a Discover title, missing ratings, and the existing version-count option.

**Pass condition:** Fresh and existing profiles use no Trakt rating source. Rating values, provenance, and personal ratings remain distinct.

## Task 4: Add Plex reviews and Lists

**Applies:** Expanded scope only. Depends on Task 1.

**PKC paths:** `default.py`, `resources/lib/entrypoint.py`, `resources/lib/plex_discover.py`, and `resources/lib/discover_cache.py`.

**Skin paths:** `addon.xml`, `1080i/Includes_Paths.xml`, `1080i/Includes_DialogInfo.xml`, the shared overlay/settings, `shortcuts/skinvariables-shortcut-config.json`, and `shortcuts/generator/data/setup/search_path.xml`.

**Interfaces:** Add dedicated read-only directory modes `discover_reviews`, `discover_lists`, and `discover_list`. Cloud metadata keys and cloud List identifiers remain distinct from local PMS keys and playlists.

- [x] Define failures from the verified contracts before code: wrong title, missing permissions, pagination loss, spoiler exposure, and cross-account cached data.
- [x] Extend the existing provider request and cache modules. Keep directory handlers thin and reuse exact local-library matching.
- [x] Declare the new PKC release as the minimum skin dependency before enabling the new directory modes.
- [x] Return review cards with author display, rating, text, and spoiler state. Reuse `List_Reviews_Row` and the existing text dialog.
- [x] Apply Plex review visibility preferences. Require an explicit action before revealing review text marked as a spoiler.
- [x] Return accessible Lists and List contents in provider order. Preserve local playback targets for matched titles.
- [x] Replace the obsolete list-search shortcut with My Plex Lists. Keep labels accurate where public list search is unavailable.
- [x] Add a favourite-list selection from accessible Lists. Use membership for favourite badges without changing Watchlist membership.
- [x] Verify empty rows, delayed responses, changed titles, denied Lists, multiple pages, and account changes.

**Verification:** Live SDK checks return two distinct review pages of 24 records. The account preference is None, so native review directories correctly remain empty. Isolated checks cover review identity and spoiler confirmation. The account has no custom Lists. A public List verifies native order, local targets, membership, and pagination. No cloud mutation occurred.

**Pass condition:** Reviews and Lists use verified Plex responses. Cache reuse does not mix accounts or titles. Existing detail actions and local playback targets remain correct.

## Task 5: Finish calendar, generator, and profile migration

**Paths:** `1080i/Includes_Hubs.xml`, `1080i/Includes_NextAired.xml`, `1080i/Includes_Home.xml`, `1080i/Dialog_DialogView.xml`, `shortcuts/skinviewtypes.json`, `shortcuts/generator/data/setup/widgets_row.xml`, and the existing startup/shortcut generation paths.

- [x] Define baseline profiles with `trakt_calendar`, a saved Trakt Lists shortcut, each watched-seed widget path, and unrelated custom widgets.
- [x] Migrate the Trakt calendar selection to `library_nextaired`. Remove the Trakt-only toggle, icon, and calendar view branches.
- [x] Remove both watched-seed detection rules. Replace recognized saved widgets with an available Plex Discover source and that source's real title.
- [x] Migrate saved Trakt list shortcuts according to the chosen scope. Preserve unrelated shortcuts and custom labels where the meaning remains correct.
- [x] Rebuild shortcuts through the existing generator. Check that a second startup makes no further migration changes.
- [x] Remove unused Trakt feature assets and the unused icon-selector search term. Preserve historical notes and the removed-button regression assertion.

**Pass condition:** Existing profiles contain no active Trakt source from the migrated feature groups. The library calendar and unrelated customization remain functional.

## Task 6: Verify and publish the integrated change

- [ ] Run native E2E checks on Living Room for movie and TV details, all five badge layouts, rating slots, Lists/reviews where selected, Next Aired, search shortcuts, and migrated widgets.
- [x] Save repeatable commands, a JSON report, and representative framebuffer screenshots under the evidence folder.
- [ ] Compare normal and failure-path responsiveness with the baseline. Count requests and confirm no new per-tile network work or idle poll loop.
- [x] Inspect the final source sweep. Record historical notes, instruction examples, and negative assertions as non-runtime exceptions.
- [x] Run `git diff --check`, parse changed XML/JSON, and run focused tests. Use the failure cases defined before implementation.
- [ ] Run each add-on's configured publish checks when preparing the release. Do not run unrelated firmware builds or broad release matrices.
- [ ] Obtain one independent review of the integrated account, cache, identity, and UI behavior. Resolve actionable findings.
- [ ] Set the required versions and news. Publish PKC first when changed, then the dependent skin through the normal repository pipeline.
- [ ] Verify published source SHAs and installed add-on versions. Preserve the user's settings and queues throughout.

## Final candidate evidence

Evidence root: `/home/user/p3i-build-evidence/20261017-trakt-to-plex/`.

| Check | Result | Artifact |
|---|---|---|
| Configured PKC tests | 532 passed | `pkc-publish-tests-r6.txt` |
| Configured skin tests | 186 passed | `skin-publish-tests-r7.txt` |
| Native directories | Empty account Lists, ten ordered public List cards, quiet reviews, fourteen Watchlist cards | `native-api-final-r10-ready.json` |
| Native UI routes | Seven checks passed | `native-ui-final-r10.json` |
| Native pagination | Two pages of 24 cards; missing List rejected | `native-pagination-final-r10.json` |
| Native favourite badges | Eight focus changes and per-card frame differences passed | `native-favourites-r15.json` |
| Native profile migration | First run changed expected values; second run changed nothing | `native-profile-migration-r1.json` |
| Final package and profile audit | 4,358 static files match; two generated skin files parse; original settings preserved | `final-package-profile-r3.json` |
| Final source checks | Changed Python compiled; changed XML/JSON parsed; diff checks passed | `final-source-check-r3.json` |
| Settled native views | Ten List cards; correct movie director and cast | `native-visual-settle-r3.json`, `plex-list-settled-r3.png`, `plex-movie-detail-settled-r3.png` |

Reproduce native checks with `python3 <evidence-root>/<script> <new-label>`:

- `native_api_check.py`
- `native_ui_check.py`
- `native_pagination_check.py`
- `native_favourites_check.py`
- `native_visual_settle_check.py`
- `final_package_profile_audit.py`

Each command uses Living Room. Each UI command checks playback first and returns Home. The final reports show no active players and empty queues.

Local source commits remain unpublished:

- PKC: `a7bbc7847f26101a04d552908a2cf02cc66ec58e` on `python3-beta`.
- Skin: `4b5687547f0e7ea9ae95d9b2c94c7e00b6be0db8` on `primez`.

Final candidate packages are in `candidate-packages/r10/packages.json`:

- PKC SHA-256: `9ef4718c75041296d5556ed5bdead9d25126ac74ef8729863a896ec9a580a071`.
- Skin SHA-256: `949bafdfa5427a75b0ab2e41fa3331d8525e886f86a98951e11959c0ffcb442c`.

The profile audit checks 308 original typed skin settings and 131 original PKC settings. No unexpected changes remain. The favourite selection and original badge choices are preserved. Two skin generator hashes may change. The add-on version migration marker changes as expected.

Remaining native coverage limits:

- Only the Landscape Row layout has a per-card pixel comparison. Shared-source checks cover all five callers.
- Live review text and spoiler dialogs remain unverified because the account disables reviews. No account preference was changed.
- The account has no owned Lists. The chooser opens and cancels; populated choices have isolated coverage.
- No Watchlist cloud mutation or playback test occurred. Isolated checks cover mutation propagation and exact local targets.
- Native directory timings range from 0.032 to 1.144 seconds. These samples do not establish a controlled before/after performance comparison.
- Normal ZIP installs report blank install origins. No pre-install origin snapshot supports a preservation claim. Confirm repository association after publication.

Earlier failed and superseded reports remain in the evidence folder. Repeated unpublished packages reused the same version. One idle Kodi restart cleared older candidate modules before final checks. No firmware build or Basement action occurred.

## Source anchors

- Skin rating choices: `skin.arctic.fuse.3/1080i/Dialog_DialogCustom.xml:878`; startup defaults: `shortcuts/skinvariables-startup.json:75`.
- Shared badges: `skin.arctic.fuse.3/1080i/Includes_Objects.xml:169`; layout callers: `Includes_Layouts.xml:1245`, `1965`, `2023`, `2193`, `2620`.
- Comments paths and mixed-content row: `skin.arctic.fuse.3/1080i/Includes_Paths.xml:119`; `Includes_DialogInfo.xml:582`.
- Calendar switch and URL: `skin.arctic.fuse.3/1080i/Includes_Hubs.xml:1003`; `Includes_NextAired.xml:4`.
- Trakt Lists generator rules: `skin.arctic.fuse.3/shortcuts/generator/data/setup/search_path.xml:160`, `290`, `464`, `642`.
- Watched-seed detection rules: `skin.arctic.fuse.3/shortcuts/generator/data/setup/widgets_row.xml:215`, `219`.
- PKC list-item hints: `plugin.video.plexkodiconnect/resources/lib/entrypoint.py:332`; account-scoped caches: `resources/lib/discover_cache.py:91`.
- PKC identity/state: `plugin.video.plexkodiconnect/resources/lib/watchlist.py:43`, `382`; metadata ratings: `resources/lib/plex_api/base.py:374`.
