# Kodi Repository Webhook Receiver

This Cloudflare Worker forwards signed source-repository pushes to the central [Primez publish workflow](../../.github/workflows/publish.yml).
The Worker sends an `addon_updated` repository dispatch to `primez-x/kodi.addons` by default.
GitHub Actions builds the packages, and GitHub Pages serves the downloads.

Routine add-on updates use the existing receiver.
Deploy the receiver when Worker code or configuration changes.
If a source webhook is unavailable, use the [manual publish command](../../README.md#publish-an-add-on-update).

## Accepted requests

The handler in [`src/index.js`](src/index.js) accepts `POST` requests only.
The handler checks the HMAC signature before parsing the JSON payload.

| Request | Response |
| --- | --- |
| Non-POST request | `405 method_not_allowed` |
| Missing Worker webhook secret | `500 missing_webhook_secret` |
| Invalid signature | `401 bad_signature` |
| Invalid JSON or push metadata | `400` with an error name |
| Signed GitHub ping | `200` with `ok: true` |
| Other signed event | `200` with `ignored: "event"` |
| Repository or branch outside the allowlist | `200` with an `ignored` reason |
| Deleted branch | `200` with `ignored: "deleted_ref"` |
| Accepted tracked-branch push | `200` with `dispatched: true` |

An accepted push needs a repository name, a matching `refs/heads/` branch, and a 40-character hexadecimal commit SHA.
The dispatch carries the repository, branch, SHA, and GitHub delivery ID.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `WEBHOOK_SECRET` | Verify GitHub's `X-Hub-Signature-256` header | Required secret |
| `GITHUB_APP_ID` | GitHub App identifier | Required secret |
| `GITHUB_APP_PRIVATE_KEY` | PEM private key for App authentication | Required secret |
| `GITHUB_APP_INSTALLATION_ID` | Installation on the target repository | Required secret |
| `TARGET_OWNER` | Dispatch target owner | `primez-x` |
| `TARGET_REPO` | Dispatch target repository | `kodi.addons` |
| `EVENT_TYPE` | Repository dispatch event name | `addon_updated` |
| `ALLOWED_REPOS_JSON` | Complete repository-to-branch allowlist | Eleven pairs in `src/index.js` |

The source default allowlist matches the eleven maintained packages in the [repository guide](../../README.md#maintained-packages).
An unset `ALLOWED_REPOS_JSON` selects the source defaults.
A custom JSON object replaces the complete default map.
An empty object accepts no repositories.
Malformed JSON, repository names, or branch names return `500 invalid_allowlist_config` and reject the push.

Source defaults describe this checkout.
A deployed Worker uses the code and configuration from the last Worker deployment.

## Initial setup

Use Node.js 22 or newer and npm for the locked Wrangler dependency.

1. Create a GitHub App with **Contents: read and write** repository permission.
2. Install the App only on `primez-x/kodi.addons`.
3. Disable webhook handling in the App; source repositories send webhooks directly to the Worker.
4. Record the App ID and installation ID.
5. Generate the App private key.

[GitHub's repository-dispatch API](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event) requires **Contents: write** for installation tokens.
The source repositories do not need personal access tokens or Actions secrets for this receiver.

From `webhook/cloudflare-worker/`, install the locked dependencies and copy the configuration example:

```bash
npm ci
cp wrangler.toml.example wrangler.toml
```

Authenticate Wrangler with the Cloudflare account that owns the Worker.
Set the webhook secret, App ID, and installation ID through the private prompts:

```bash
npx wrangler secret put WEBHOOK_SECRET
npx wrangler secret put GITHUB_APP_ID
npx wrangler secret put GITHUB_APP_INSTALLATION_ID
```

The Cloudflare runtime needs the App key in PKCS#8 PEM format with a `BEGIN PRIVATE KEY` header.
If the downloaded key has a `BEGIN RSA PRIVATE KEY` header, convert the key locally:

```bash
node -e "const fs=require('fs');const crypto=require('crypto');const key=crypto.createPrivateKey(fs.readFileSync(process.argv[1],'utf8'));fs.writeFileSync(process.argv[2],key.export({format:'pem',type:'pkcs8'}));" /path/to/github-app.private-key.pem /path/to/github-app.private-key.pkcs8.pem
npx wrangler secret put GITHUB_APP_PRIVATE_KEY < /path/to/github-app.private-key.pkcs8.pem
```

Replace `/path/to/` with a private directory outside this repository.
Keep `wrangler.toml`, private keys, tokens, and webhook secrets out of Git.
For the supported secret commands, see the [Wrangler documentation](https://developers.cloudflare.com/workers/wrangler/commands/).

After the configuration and credentials are ready, deploy the Worker:

```bash
npm run deploy
```

## Source webhooks

For each required source repository, open **Settings > Webhooks > Add webhook**.

- **Payload URL:** the deployed Worker URL.
- **Content type:** `application/json`.
- **Secret:** the same value as the Worker's `WEBHOOK_SECRET`.
- **Events:** **Just the push event**.
- **Active:** enabled.

Use the tracked branch names in `src/index.js` or the configured custom allowlist.
Check GitHub's recent deliveries after a source push.
An ignored request also returns `200`; confirm `dispatched: true` when checking an accepted push.
Then confirm the central workflow records the intended source SHA in `source-manifest.json`.

## Local checks

Run the handler checks with:

```bash
npm test
```

Run the signed-request harness with:

```bash
npm run test:runtime -- --log /tmp/kodi-worker-runtime.log
```

The harness starts local Wrangler and checks ping, invalid signature, ignored branch, and accepted push requests.
The harness mocks GitHub authentication and dispatch, so the harness does not publish to GitHub.
The log must be outside the repository.

For interactive request checks, start the local Worker with:

```bash
npm run dev
```

Use local test credentials for interactive requests.
An unsigned request cannot exercise the accepted-push path.

## Source layout

- `src/index.js`: signature checks, payload checks, allowlist, and GitHub dispatch.
- `test/index.test.js`: handler and configuration checks.
- `test/runtime.mjs`: signed requests through local Wrangler with mocked GitHub calls.
- `package-lock.json`: locked dependencies.
- `wrangler.toml.example`: public configuration template.
