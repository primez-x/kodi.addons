# Trakt to Plex Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` for implementation. Complete the API checks before product changes.

**Goal:** Replace the skin's remaining Trakt sources with Plex sources and preserve clear, accurate feature names.

**Architecture:** PlexKodiConnect owns Plex requests, account identity, metadata conversion, and caches. Arctic Fuse consumes those interfaces through existing controls and generators. TMDb Helper continues to provide unrelated metadata.

**Tech Stack:** Kodi skin XML, Skin Variables JSON/XML generators, Python, existing PKC request and cache modules.

**Spec:** The scope, feature map, and boundaries below define the proposed behavior.

**Status:** Source audit and root review complete. Plex reviews and custom Lists remain proposed additions. The user scope question remains open. No product code changed.

**Independent review:** The review service rejected Opus, Astra, and automatic reviewer selection. No independent reviewer examined this draft. The implementation still requires the review in Task 6.

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

### Smaller scope alternative

If the user selects existing PKC capabilities only, omit both new readers. Remove the Trakt favourite badge and Trakt comments provider. Remove the Trakt Lists search shortcut. Keep existing Plex Watchlist and Discover shortcuts. Preserve awards, consensus cards, and the library calendar.

This alternative removes features. The expanded scope preserves more functionality and remains the recommendation.

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
- At the audited tips, the next feature versions are PKC `3.16.0` and skin `3.30.0`. Recalculate before implementation if either branch advances.
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

- [ ] Observe the requests used by the official Plex client. Reuse the existing account credentials privately. Use read-only queries during this task.
- [ ] Verify reviews for a library title and a cloud-only title. Check spoiler flags and account review preferences.
- [ ] Verify accessible Lists and List contents. Establish whether list-name filters are local or service-supported.
- [ ] Verify empty, inaccessible, and paginated responses. Preserve list order and distinguish the final page from a failed page.
- [ ] Save sanitized response shapes and bounded request counts. Exclude tokens, account identifiers, private list contents, and review authors from committed fixtures.
- [ ] Record unsupported title types and missing permissions as explicit capability results.

**Pass condition:** The implementation has verified request and response contracts. Product documentation alone cannot satisfy this task. If a required contract fails, revise the affected feature map before implementation.

## Task 2: Complete the shared Plex Watchlist badges

**PKC paths:** `resources/lib/watchlist.py`, `resources/lib/discover_cache.py`, `resources/lib/entrypoint.py`, and `resources/lib/widgets.py` as required by the card source.

**Skin paths:** `1080i/Includes_Objects.xml`, all five callers in `1080i/Includes_Layouts.xml`, and `1080i/Dialog_DialogCustom.xml`.

**Interfaces:** Consume `PlexWatchlistHint`, the existing `PKC.Watchlist.Item.*` state, and exact item identity. Produce one shared Plex Watchlist overlay.

- [ ] Define the failures before code: unknown state displayed as absence, stale focused state copied to other cards, account leakage, and HTTP requests per tile.
- [ ] Capture native baseline behavior for a Watchlist member, a non-member, and a generic library card without a provider hint.
- [ ] Extend the existing state projection for uncovered card sources. Reuse the current membership cache and batch identity resolution.
- [ ] Replace the shared Trakt overlay and all five callers. Keep the settings labels consistent with Plex Watchlist.
- [ ] Verify add/remove propagation, rapid focus changes, offline cache behavior, account changes, editions, and season/episode exclusion.

**Pass condition:** Every supported card displays the correct account's membership. Unknown cards remain quiet. Rendering a populated row creates no per-tile network fan-out.

## Task 3: Replace Trakt rating choices and stored values

**Paths:** `1080i/Dialog_DialogCustom.xml`, `1080i/Includes_Info.xml`, `1080i/Includes_Actions.xml`, `shortcuts/skinvariables-startup.json`, and the existing PKC metadata conversion only where necessary.

**Interfaces:** Consume PKC rating values with their source and scale. Preserve personal ratings as a separate field.

- [ ] Define expected behavior for each of three rating slots in Movies and TV Shows, including stored Trakt values and blank values.
- [ ] Add the Plex source choice and migrate Trakt values through the existing startup rules.
- [ ] Update startup defaults and reset actions for all slots. Preserve unrelated user choices.
- [ ] Display the actual source and scale. Avoid a duplicate rating when another slot selects the same provider value.
- [ ] Verify a library title, a Discover title, missing ratings, and the existing version-count option.

**Pass condition:** Fresh and existing profiles use no Trakt rating source. Rating values, provenance, and personal ratings remain distinct.

## Task 4: Add Plex reviews and Lists

**Applies:** Expanded scope only. Depends on Task 1.

**PKC paths:** `default.py`, `resources/lib/entrypoint.py`, `resources/lib/plex_discover.py`, and `resources/lib/discover_cache.py`.

**Skin paths:** `addon.xml`, `1080i/Includes_Paths.xml`, `1080i/Includes_DialogInfo.xml`, the shared overlay/settings, `shortcuts/skinvariables-shortcut-config.json`, and `shortcuts/generator/data/setup/search_path.xml`.

**Interfaces:** Add dedicated read-only directory modes `discover_reviews`, `discover_lists`, and `discover_list`. Cloud metadata keys and cloud List identifiers remain distinct from local PMS keys and playlists.

- [ ] Define failures from the verified contracts before code: wrong title, missing permissions, pagination loss, spoiler exposure, and cross-account cached data.
- [ ] Extend the existing provider request and cache modules. Keep directory handlers thin and reuse exact local-library matching.
- [ ] Declare the new PKC release as the minimum skin dependency before enabling the new directory modes.
- [ ] Return review cards with author display, rating, text, and spoiler state. Reuse `List_Reviews_Row` and the existing text dialog.
- [ ] Apply Plex review visibility preferences. Require an explicit action before revealing review text marked as a spoiler.
- [ ] Return accessible Lists and List contents in provider order. Preserve local playback targets for matched titles.
- [ ] Replace the obsolete list-search shortcut with My Plex Lists. Keep labels accurate where public list search is unavailable.
- [ ] Add a favourite-list selection from accessible Lists. Use membership for favourite badges without changing Watchlist membership.
- [ ] Verify empty rows, delayed responses, changed titles, denied Lists, multiple pages, and account changes.

**Pass condition:** Reviews and Lists use verified Plex responses. Cache reuse does not mix accounts or titles. Existing detail actions and local playback targets remain correct.

## Task 5: Finish calendar, generator, and profile migration

**Paths:** `1080i/Includes_Hubs.xml`, `1080i/Includes_NextAired.xml`, `1080i/Includes_Home.xml`, `1080i/Dialog_DialogView.xml`, `shortcuts/skinviewtypes.json`, `shortcuts/generator/data/setup/widgets_row.xml`, and the existing startup/shortcut generation paths.

- [ ] Define baseline profiles with `trakt_calendar`, a saved Trakt Lists shortcut, each watched-seed widget path, and unrelated custom widgets.
- [ ] Migrate the Trakt calendar selection to `library_nextaired`. Remove the Trakt-only toggle, icon, and calendar view branches.
- [ ] Remove both watched-seed detection rules. Replace recognized saved widgets with an available Plex Discover source and that source's real title.
- [ ] Migrate saved Trakt list shortcuts according to the chosen scope. Preserve unrelated shortcuts and custom labels where the meaning remains correct.
- [ ] Rebuild shortcuts through the existing generator. Check that a second startup makes no further migration changes.
- [ ] Remove unused Trakt feature assets and the unused icon-selector search term. Preserve historical notes and the removed-button regression assertion.

**Pass condition:** Existing profiles contain no active Trakt source from the migrated feature groups. The library calendar and unrelated customization remain functional.

## Task 6: Verify and publish the integrated change

- [ ] Run native E2E checks on Living Room for movie and TV details, all five badge layouts, rating slots, Lists/reviews where selected, Next Aired, search shortcuts, and migrated widgets.
- [ ] Save repeatable commands, a JSON report, and representative framebuffer screenshots under the evidence folder.
- [ ] Compare normal and failure-path responsiveness with the baseline. Count requests and confirm no new per-tile network work or idle poll loop.
- [ ] Inspect the final source sweep. Record historical notes, instruction examples, and negative assertions as non-runtime exceptions.
- [ ] Run `git diff --check`, parse changed XML/JSON, and run focused tests. Use the failure cases defined before implementation.
- [ ] Run each add-on's configured publish checks when preparing the release. Do not run unrelated firmware builds or broad release matrices.
- [ ] Obtain one independent review of the integrated account, cache, identity, and UI behavior. Resolve actionable findings.
- [ ] Set the required versions and news. Publish PKC first when changed, then the dependent skin through the normal repository pipeline.
- [ ] Verify published source SHAs and installed add-on versions. Preserve the user's settings and queues throughout.

## Source anchors

- Skin rating choices: `skin.arctic.fuse.3/1080i/Dialog_DialogCustom.xml:878`; startup defaults: `shortcuts/skinvariables-startup.json:75`.
- Shared badges: `skin.arctic.fuse.3/1080i/Includes_Objects.xml:169`; layout callers: `Includes_Layouts.xml:1245`, `1965`, `2023`, `2193`, `2620`.
- Comments paths and mixed-content row: `skin.arctic.fuse.3/1080i/Includes_Paths.xml:119`; `Includes_DialogInfo.xml:582`.
- Calendar switch and URL: `skin.arctic.fuse.3/1080i/Includes_Hubs.xml:1003`; `Includes_NextAired.xml:4`.
- Trakt Lists generator rules: `skin.arctic.fuse.3/shortcuts/generator/data/setup/search_path.xml:160`, `290`, `464`, `642`.
- Watched-seed detection rules: `skin.arctic.fuse.3/shortcuts/generator/data/setup/widgets_row.xml:215`, `219`.
- PKC list-item hints: `plugin.video.plexkodiconnect/resources/lib/entrypoint.py:332`; account-scoped caches: `resources/lib/discover_cache.py:91`.
- PKC identity/state: `plugin.video.plexkodiconnect/resources/lib/watchlist.py:43`, `382`; metadata ratings: `resources/lib/plex_api/base.py:374`.
