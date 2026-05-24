# Kodi Repository Webhook Receiver

This Cloudflare Worker receives GitHub repository webhooks from the source add-on repositories and triggers `primez-x/kodi.addons` with a `repository_dispatch` event.

No source repository needs a PAT or Actions secret.

## Security model

- Source repos send normal GitHub repository webhooks signed with `WEBHOOK_SECRET`.
- The Worker validates `X-Hub-Signature-256` before reading the payload.
- The Worker only accepts push events from the allowlisted repositories and branches.
- The Worker uses a GitHub App installation token to call `repository_dispatch` on `primez-x/kodi.addons`.
- The GitHub App should be installed only on `primez-x/kodi.addons` and granted **Contents: read and write**.

GitHub documents `repository_dispatch` as requiring **Contents: write** for fine-grained tokens, including GitHub App installation tokens.

## GitHub App setup

1. Create a GitHub App, for example `Primez Kodi Publisher`.
2. Disable webhook handling for the app itself. The Worker receives repository webhooks directly from the source repos.
3. Give the app **Contents: read and write** repository permission.
4. Install the app only on `primez-x/kodi.addons`.
5. Generate a private key.
6. Note the app ID and the installation ID.

## Worker setup

Copy the example config:

```bash
cp wrangler.toml.example wrangler.toml
npm install
```

Set Worker secrets:

```bash
wrangler secret put WEBHOOK_SECRET
wrangler secret put GITHUB_APP_ID
wrangler secret put GITHUB_APP_PRIVATE_KEY
wrangler secret put GITHUB_APP_INSTALLATION_ID
```

Deploy:

```bash
npm run deploy
```

## Source repository webhooks

For each source add-on repository, go to **Settings > Webhooks > Add webhook**:

- Payload URL: your Worker URL
- Content type: `application/json`
- Secret: the same value as `WEBHOOK_SECRET`
- Events: **Just the push event**
- Active: checked

Add the webhook to:

- `primez-x/plugin.video.plexkodiconnect`
- `primez-x/plugin.audio.spotifykodiconnect`
- `primez-x/skin.arctic.fuse.3`
- `primez-x/service.nexttrack`

The Worker ignores pushes to any branch other than the branch configured in `ALLOWED_REPOS_JSON`.
