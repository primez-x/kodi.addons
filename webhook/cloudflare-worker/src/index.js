import { createAppAuth } from "@octokit/auth-app";
import { request as octokitRequest } from "@octokit/request";

// Keep this map in JSON object syntax for the builder branch check.
const DEFAULT_ALLOWED_REPOS = {
  "primez-x/plugin.video.plexkodiconnect": "python3-beta",
  "primez-x/plugin.audio.spotifykodiconnect": "master",
  "primez-x/skin.arctic.fuse.3": "primez",
  "primez-x/starlight": "main",
  "primez-x/resource.images.arctic.fuse.3": "main",
  "primez-x/plugin.video.themoviedb.helper": "nexus",
  "primez-x/service.upnext": "master",
  "primez-x/service.nexttrack": "main",
  "primez-x/service.smartsubtitles": "main",
  "primez-x/plugin.video.smarttube": "main",
  "primez-x/script.xbmc.unpausejumpback": "primez",
  "primez-x/script.service.playbackresumer": "primez"
};

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return json({ error: "method_not_allowed" }, 405);
    }

    const delivery = request.headers.get("x-github-delivery") || "";
    const event = request.headers.get("x-github-event") || "";
    const signature = request.headers.get("x-hub-signature-256") || "";

    for (const name of ["WEBHOOK_SECRET", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_INSTALLATION_ID"]) {
      if (typeof env[name] !== "string" || !env[name].trim()) {
        return json({ error: `missing_${name.toLowerCase()}`, delivery }, 500);
      }
    }
    const body = await request.arrayBuffer();

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
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return json({ error: "invalid_payload" }, 400);
    }

    if (event === "ping") {
      return json({ ok: true, delivery, event });
    }

    if (event !== "push") {
      return json({ ok: true, ignored: "event", event, delivery });
    }

    const sourceRepository = payload.repository?.full_name;
    const ref = payload.ref;
    const sha = payload.after;
    if (
      !isValidRepositoryName(sourceRepository)
      || typeof ref !== "string"
      || typeof sha !== "string"
      || !/^[a-f0-9]{40}$/i.test(sha)
    ) {
      return json({ error: "invalid_payload" }, 400);
    }

    let allowedRepos;
    try {
      allowedRepos = parseAllowedRepos(env.ALLOWED_REPOS_JSON);
    } catch {
      return json({ error: "invalid_allowlist_config" }, 500);
    }

    const expectedBranch = Object.hasOwn(allowedRepos, sourceRepository)
      ? allowedRepos[sourceRepository]
      : undefined;
    if (!expectedBranch) {
      return json({ ok: true, ignored: "repository", sourceRepository, delivery });
    }

    if (ref !== `refs/heads/${expectedBranch}`) {
      return json({ ok: true, ignored: "branch", sourceRepository, ref, delivery });
    }

    if (!sha || /^0+$/.test(sha)) {
      return json({ ok: true, ignored: "deleted_ref", sourceRepository, ref, delivery });
    }

    try {
      await dispatchKodiPublish(env, {
        repository: sourceRepository,
        ref: expectedBranch,
        sha,
        delivery,
      });
    } catch {
      console.error(JSON.stringify({ error: "dispatch_failed", delivery }));
      return json({ error: "dispatch_failed", delivery }, 502);
    }

    return json({ ok: true, dispatched: true, sourceRepository, ref, sha, delivery });
  },
};

function parseAllowedRepos(value) {
  if (value === undefined) {
    return DEFAULT_ALLOWED_REPOS;
  }

  if (typeof value !== "string") {
    throw new TypeError("ALLOWED_REPOS_JSON must be a JSON string");
  }

  let parsed;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new TypeError("ALLOWED_REPOS_JSON must contain valid JSON");
  }

  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new TypeError("ALLOWED_REPOS_JSON must contain a repository map");
  }

  const allowedRepos = Object.create(null);
  for (const [repository, branch] of Object.entries(parsed)) {
    if (!isValidRepositoryName(repository) || !isValidBranchName(branch)) {
      throw new TypeError("ALLOWED_REPOS_JSON contains an invalid repository or branch");
    }
    allowedRepos[repository] = branch;
  }
  return allowedRepos;
}

function isValidRepositoryName(value) {
  if (typeof value !== "string") {
    return false;
  }

  const parts = value.split("/");
  if (parts.length !== 2) {
    return false;
  }

  const [owner, repository] = parts;
  return /^[A-Za-z0-9-]{1,39}$/.test(owner)
    && !owner.startsWith("-")
    && !owner.endsWith("-")
    && /^[A-Za-z0-9._-]{1,100}$/.test(repository)
    && repository !== "."
    && repository !== ".."
    && !repository.endsWith(".");
}

function isValidBranchName(value) {
  if (typeof value !== "string" || value.length === 0 || value === "@") {
    return false;
  }

  if (
    value.startsWith("/")
    || value.endsWith("/")
    || value.endsWith(".")
    || value.includes("//")
    || value.includes("..")
    || value.includes("@{")
    || /[ ~^:?*\\\[\u0000-\u0020\u007f]/.test(value)
  ) {
    return false;
  }

  return value.split("/").every((part) => part.length > 0 && !part.startsWith(".") && !part.endsWith(".lock"));
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
