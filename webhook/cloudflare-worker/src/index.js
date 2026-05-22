import { createAppAuth } from "@octokit/auth-app";
import { request as octokitRequest } from "@octokit/request";

const DEFAULT_ALLOWED_REPOS = {
  "primez-x/plugin.video.plexkodiconnect": "python3-beta",
  "primez-x/plugin.audio.spotifykodiconnect": "master",
  "primez-x/skin.arctic.fuse.3": "omega",
};

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405);
    }

    const delivery = request.headers.get("x-github-delivery") || "";
    const event = request.headers.get("x-github-event") || "";
    const signature = request.headers.get("x-hub-signature-256") || "";
    const body = await request.arrayBuffer();

    if (!env.WEBHOOK_SECRET) {
      return json({ error: "missing_webhook_secret" }, 500);
    }

    const signatureOk = await verifyGitHubSignature(body, signature, env.WEBHOOK_SECRET);
    if (!signatureOk) {
      return json({ error: "bad_signature" }, 401);
    }

    const payloadText = new TextDecoder().decode(body);
    let payload;
    try {
      payload = JSON.parse(payloadText);
    } catch {
      return json({ error: "invalid_json" }, 400);
    }

    if (event === "ping") {
      return json({ ok: true, delivery, event });
    }

    if (event !== "push") {
      return json({ ok: true, ignored: "event", event, delivery });
    }

    const sourceRepository = payload.repository?.full_name;
    const ref = payload.ref || "";
    const sha = payload.after || "";

    const allowedRepos = parseAllowedRepos(env.ALLOWED_REPOS_JSON);
    const expectedBranch = allowedRepos[sourceRepository];
    if (!expectedBranch) {
      return json({ ok: true, ignored: "repository", sourceRepository, delivery });
    }

    if (ref !== `refs/heads/${expectedBranch}`) {
      return json({ ok: true, ignored: "branch", sourceRepository, ref, delivery });
    }

    if (!sha || /^0+$/.test(sha)) {
      return json({ ok: true, ignored: "deleted_ref", sourceRepository, ref, delivery });
    }

    await dispatchKodiPublish(env, {
      repository: sourceRepository,
      ref: expectedBranch,
      sha,
      delivery,
    });

    return json({ ok: true, dispatched: true, sourceRepository, ref, sha, delivery });
  },
};

function parseAllowedRepos(value) {
  if (!value) {
    return DEFAULT_ALLOWED_REPOS;
  }

  try {
    return JSON.parse(value);
  } catch {
    return DEFAULT_ALLOWED_REPOS;
  }
}

async function dispatchKodiPublish(env, payload) {
  const auth = createAppAuth({
    appId: env.GITHUB_APP_ID,
    privateKey: normalizePrivateKey(env.GITHUB_APP_PRIVATE_KEY),
    installationId: env.GITHUB_APP_INSTALLATION_ID,
  });

  const installationAuth = await auth({ type: "installation" });

  await octokitRequest("POST /repos/{owner}/{repo}/dispatches", {
    owner: env.TARGET_OWNER || "primez-x",
    repo: env.TARGET_REPO || "kodi.addons",
    event_type: env.EVENT_TYPE || "addon_updated",
    client_payload: payload,
    headers: {
      authorization: `Bearer ${installationAuth.token}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
    },
  });
}

function normalizePrivateKey(value) {
  return value.replace(/\\n/g, "\n");
}

async function verifyGitHubSignature(body, signatureHeader, secret) {
  if (!signatureHeader.startsWith("sha256=")) {
    return false;
  }

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, body);
  const expected = `sha256=${toHex(digest)}`;
  return timingSafeEqual(expected, signatureHeader);
}

function toHex(buffer) {
  return [...new Uint8Array(buffer)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(left, right) {
  const leftBytes = new TextEncoder().encode(left);
  const rightBytes = new TextEncoder().encode(right);
  let diff = leftBytes.length ^ rightBytes.length;
  const length = Math.max(leftBytes.length, rightBytes.length);

  for (let index = 0; index < length; index += 1) {
    diff |= (leftBytes[index] || 0) ^ (rightBytes[index] || 0);
  }

  return diff === 0;
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
