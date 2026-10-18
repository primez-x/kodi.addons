import assert from "node:assert/strict";
import { generateKeyPairSync } from "node:crypto";
import test from "node:test";

import worker from "../src/index.js";

const secret = "test-webhook-secret";
const sha = "a".repeat(40);
const defaultRepositories = {
  "primez-x/plugin.video.plexkodiconnect": "python3-beta",
  "primez-x/plugin.audio.spotifykodiconnect": "master",
  "primez-x/skin.starlight": "main",
  "primez-x/script.starlight": "main",
  "primez-x/screensaver.starlight": "main",
  "primez-x/visualization.starlight": "armv7",
  "primez-x/service.upnext": "master",
  "primez-x/service.nexttrack": "main",
  "primez-x/service.smartsubtitles": "main",
  "primez-x/plugin.video.smarttube": "main",
  "primez-x/script.xbmc.unpausejumpback": "primez",
  "primez-x/script.service.playbackresumer": "primez",
};

const { privateKey } = generateKeyPairSync("rsa", {
  modulusLength: 2048,
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
  publicKeyEncoding: { type: "spki", format: "pem" },
});

function baseEnv(extra = {}) {
  return {
    WEBHOOK_SECRET: secret,
    GITHUB_APP_ID: "12345",
    GITHUB_APP_PRIVATE_KEY: privateKey,
    GITHUB_APP_INSTALLATION_ID: "67890",
    ...extra,
  };
}

function pushPayload(repository, branch, after = sha) {
  return {
    repository: { full_name: repository },
    ref: `refs/heads/${branch}`,
    after,
  };
}

async function signedRequest({ event = "push", payload, body, signature, delivery = "delivery-1" }) {
  const requestBody = body ?? JSON.stringify(payload);
  const signatureHeader = signature ?? await signBody(requestBody, secret);
  return new Request("https://worker.example/webhook", {
    method: "POST",
    headers: {
      "x-github-delivery": delivery,
      "x-github-event": event,
      "x-hub-signature-256": signatureHeader,
    },
    body: requestBody,
  });
}

async function signBody(body, signingSecret) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(signingSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(body));
  return `sha256=${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

async function withMockedGitHub(run) {
  const originalFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    const method = init.method || (input instanceof Request ? input.method : "GET");
    requests.push({ url, method, body: init.body });

    if (url.endsWith("/access_tokens")) {
      return new Response(JSON.stringify({ token: "ghs_test-token", expires_at: "2099-01-01T00:00:00Z" }), {
        status: 201,
        headers: { "content-type": "application/json" },
      });
    }
    if (url.endsWith("/dispatches")) {
      return new Response(null, { status: 204 });
    }
    return new Response("{}", { status: 404 });
  };

  try {
    await run(requests);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function responseBody(response) {
  return { status: response.status, body: await response.json() };
}

test("accepts a signed ping without dispatching", async () => {
  const request = await signedRequest({ event: "ping", payload: { zen: "Stay logically awesome." } });
  const response = await worker.fetch(request, baseEnv());
  const result = await responseBody(response);

  assert.equal(result.status, 200);
  assert.deepEqual(result.body, { ok: true, delivery: "delivery-1", event: "ping" });
});

test("rejects a bad signature before parsing the body", async () => {
  const request = await signedRequest({ body: "not-json", signature: "sha256=00", payload: undefined });
  const response = await worker.fetch(request, baseEnv());
  const result = await responseBody(response);

  assert.equal(result.status, 401);
  assert.deepEqual(result.body, { error: "bad_signature" });
});

test("ignores a push to a branch outside the default allowlist", async () => {
  const repository = "primez-x/plugin.video.plexkodiconnect";
  const request = await signedRequest({ payload: pushPayload(repository, "feature/test") });
  const response = await worker.fetch(request, baseEnv());
  const result = await responseBody(response);

  assert.equal(result.status, 200);
  assert.deepEqual(result.body, {
    ok: true,
    ignored: "branch",
    sourceRepository: repository,
    ref: "refs/heads/feature/test",
    delivery: "delivery-1",
  });
});

test("dispatches pushes from all eight default repositories", async () => {
  await withMockedGitHub(async (requests) => {
    for (const [repository, branch] of Object.entries(defaultRepositories)) {
      const request = await signedRequest({ payload: pushPayload(repository, branch) });
      const response = await worker.fetch(request, baseEnv());
      const result = await responseBody(response);

      assert.equal(result.status, 200);
      assert.equal(result.body.dispatched, true);
      assert.equal(result.body.sourceRepository, repository);
    }

    assert.equal(requests.filter(({ url }) => url.endsWith("/dispatches")).length, Object.keys(defaultRepositories).length);
  });
});

test("uses an environment allowlist as a full replacement and accepts custom repositories", async () => {
  const customRepository = "example-org/custom-addon";
  const env = baseEnv({ ALLOWED_REPOS_JSON: JSON.stringify({ [customRepository]: "release/v2" }) });

  await withMockedGitHub(async (requests) => {
    const customRequest = await signedRequest({ payload: pushPayload(customRepository, "release/v2") });
    const customResult = await responseBody(await worker.fetch(customRequest, env));
    assert.equal(customResult.body.dispatched, true);

    const defaultRequest = await signedRequest({
      payload: pushPayload("primez-x/plugin.video.plexkodiconnect", "python3-beta"),
    });
    const defaultResult = await responseBody(await worker.fetch(defaultRequest, env));
    assert.equal(defaultResult.body.ignored, "repository");
    assert.equal(requests.filter(({ url }) => url.endsWith("/dispatches")).length, 1);
  });
});

test("rejects malformed allowlist JSON with an explicit error", async () => {
  const env = baseEnv({ ALLOWED_REPOS_JSON: "{broken" });
  const request = await signedRequest({
    payload: pushPayload("primez-x/plugin.video.plexkodiconnect", "python3-beta"),
  });

  await withMockedGitHub(async (requests) => {
    const result = await responseBody(await worker.fetch(request, env));
    assert.equal(result.status, 500);
    assert.deepEqual(result.body, { error: "invalid_allowlist_config" });
    assert.equal(requests.length, 0);
  });
});

test("rejects invalid repository names and branch values in the allowlist", async () => {
  const badConfigs = [
    JSON.stringify({ "bad name/repository": "main" }),
    JSON.stringify({ "example-org/custom-addon": "" }),
  ];

  for (const ALLOWED_REPOS_JSON of badConfigs) {
    const request = await signedRequest({
      payload: pushPayload("example-org/custom-addon", "main"),
    });
    const result = await responseBody(await worker.fetch(request, baseEnv({ ALLOWED_REPOS_JSON })));
    assert.equal(result.status, 500);
    assert.deepEqual(result.body, { error: "invalid_allowlist_config" });
  }
});

test("rejects non-object and malformed push payloads", async () => {
  const badBodies = [
    { body: "null" },
    { payload: pushPayload("primez-x/plugin.video.plexkodiconnect", "python3-beta", "not-a-commit-sha") },
    { payload: pushPayload("primez-x/plugin.video.plexkodiconnect", "python3-beta", [sha]) },
    { payload: { repository: { full_name: 12 }, ref: "refs/heads/python3-beta", after: sha } },
  ];

  await withMockedGitHub(async (requests) => {
    for (const input of badBodies) {
      const request = await signedRequest(input);
      let response;
      await assert.doesNotReject(async () => {
        response = await worker.fetch(request, baseEnv());
      });
      const result = await responseBody(response);
      assert.equal(result.status, 400);
      assert.deepEqual(result.body, { error: "invalid_payload" });
    }

    assert.equal(requests.length, 0);
  });
});

test("dispatches the verified commit details to the configured target", async () => {
  const repository = "primez-x/plugin.video.plexkodiconnect";
  const request = await signedRequest({
    payload: pushPayload(repository, "python3-beta"),
    delivery: "delivery-verified",
  });
  const env = baseEnv({ TARGET_OWNER: "publisher", TARGET_REPO: "catalog", EVENT_TYPE: "source_updated" });

  await withMockedGitHub(async (requests) => {
    const result = await responseBody(await worker.fetch(request, env));
    assert.equal(result.body.dispatched, true);

    const dispatchRequest = requests.find(({ url }) => url.endsWith("/dispatches"));
    assert.ok(dispatchRequest);
    assert.equal(dispatchRequest.method, "POST");
    assert.deepEqual(JSON.parse(dispatchRequest.body), {
      event_type: "source_updated",
      client_payload: {
        repository,
        ref: "python3-beta",
        sha,
        delivery: "delivery-verified",
      },
    });
    assert.equal(dispatchRequest.url, "https://api.github.com/repos/publisher/catalog/dispatches");
  });
});

test("validates every required secret before signature verification", async () => {
  for (const name of ["WEBHOOK_SECRET", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_INSTALLATION_ID"]) {
    for (const value of [undefined, "", "   ", 123]) {
      const request = await signedRequest({ body: "not-json", signature: "sha256=00" });
      const result = await responseBody(await worker.fetch(request, baseEnv({ [name]: value })));
      assert.equal(result.status, 500);
      assert.deepEqual(result.body, { error: `missing_${name.toLowerCase()}`, delivery: "delivery-1" });
    }
  }
});

test("returns a structured gateway error when authentication or dispatch fails", async () => {
  const originalFetch = globalThis.fetch;
  try {
    for (const stage of ["auth", "dispatch", "network", "key"]) {
      globalThis.fetch = async (input) => {
        const url = typeof input === "string" ? input : input.url;
        if (stage === "network") throw new Error("network unavailable");
        if (url.endsWith("/access_tokens") && stage !== "auth") {
          return new Response(JSON.stringify({ token: "ghs_test", expires_at: "2099-01-01T00:00:00Z" }), {
            status: 201, headers: { "content-type": "application/json" },
          });
        }
        return new Response(JSON.stringify({ message: "upstream unavailable" }), {
          status: 503, headers: { "content-type": "application/json" },
        });
      };
      const request = await signedRequest({ payload: pushPayload("primez-x/service.nexttrack", "main") });
      const env = stage === "key" ? baseEnv({ GITHUB_APP_PRIVATE_KEY: "invalid-key" }) : baseEnv();
      const result = await responseBody(await worker.fetch(request, env));
      assert.equal(result.status, 502);
      assert.deepEqual(result.body, { error: "dispatch_failed", delivery: "delivery-1" });
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});
