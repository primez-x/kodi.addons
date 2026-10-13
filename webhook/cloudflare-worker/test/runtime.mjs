import assert from "node:assert/strict";
import { createHmac, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { promises as fs } from "node:fs";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const workerRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = path.resolve(workerRoot, "../..");
const secret = `runtime-secret-${randomBytes(12).toString("hex")}`;
const token = `runtime-token-${randomBytes(12).toString("hex")}\r\n`;
const privateKey = `runtime-key-${randomBytes(12).toString("hex")}`;
const nonce = randomBytes(12).toString("hex");
const authMarker = `KODI_RUNTIME_AUTH_${nonce}`;
const dispatchMarker = `KODI_RUNTIME_DISPATCH_${nonce}`;
const repository = "primez-x/plugin.video.plexkodiconnect";
const branch = "python3-beta";
const sha = "a".repeat(40);
const expectedDispatch = {
  route: "POST /repos/{owner}/{repo}/dispatches",
  owner: "runtime-target-owner",
  repo: "runtime-target-repo",
  event_type: "runtime-test-event",
  client_payload: {
    repository,
    ref: branch,
    sha,
    delivery: "runtime-allowed-push",
  },
};

function parseLogPath(args) {
  const logIndex = args.indexOf("--log");
  if (logIndex !== -1 && (args.length !== 2 || logIndex !== 0 || !args[1])) {
    throw new Error("Use --log followed by one path");
  }
  if (logIndex === -1 && args.length !== 0) {
    throw new Error("Use --log followed by one path");
  }

  const destination = logIndex === -1
    ? path.join(os.tmpdir(), "kodi-worker-runtime.log")
    : path.resolve(args[1]);
  const relative = path.relative(repositoryRoot, destination);
  if (relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative))) {
    throw new Error("Choose a log path outside the repository");
  }
  return destination;
}

function tomlString(value) {
  return JSON.stringify(value);
}

function signedHeaders(event, delivery, body, invalid = false) {
  const signature = invalid
    ? "sha256=00"
    : `sha256=${createHmac("sha256", secret).update(body).digest("hex")}`;
  return {
    "content-type": "application/json",
    "x-github-delivery": delivery,
    "x-github-event": event,
    "x-hub-signature-256": signature,
  };
}

async function postEvent(baseUrl, event, delivery, payload, options = {}) {
  const body = options.body ?? JSON.stringify(payload);
  return fetch(baseUrl, {
    method: "POST",
    headers: signedHeaders(event, delivery, body, options.invalidSignature),
    body,
    signal: AbortSignal.timeout(5000),
  });
}

async function readJson(response) {
  return { status: response.status, body: await response.json() };
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function reservePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return address.port;
}

async function writeFixtures(fixtureDir) {
  const mockAuthPath = path.join(fixtureDir, "mock-auth.mjs");
  const mockRequestPath = path.join(fixtureDir, "mock-request.mjs");
  const configPath = path.join(fixtureDir, "wrangler.toml");
  const authSource = `const marker = ${JSON.stringify(authMarker)};
const token = ${JSON.stringify(token)};
const privateKey = ${JSON.stringify(privateKey)};
export function createAppAuth(options) {
  if (marker.length === 0 || options.appId !== "12345" || options.privateKey !== privateKey || options.installationId !== "67890") {
    throw new Error("local auth mock rejected configuration");
  }
  return async () => ({ token });
}
`;
  const requestSource = `const marker = ${JSON.stringify(dispatchMarker)};
const token = ${JSON.stringify(token)};
export async function request(route, options) {
  if (route !== "POST /repos/{owner}/{repo}/dispatches" || options.headers.authorization !== ("Bearer " + token)) {
    throw new Error("local dispatch mock rejected request");
  }
  console.log(marker + " " + JSON.stringify({
    route,
    owner: options.owner,
    repo: options.repo,
    event_type: options.event_type,
    client_payload: options.client_payload,
  }));
  return { status: 204 };
}
`;
  const config = `name = "kodi-webhook-runtime"
main = ${tomlString(path.join(workerRoot, "src/index.js"))}
compatibility_date = "2026-05-22"

[vars]
WEBHOOK_SECRET = ${tomlString(secret)}
GITHUB_APP_ID = "12345"
GITHUB_APP_PRIVATE_KEY = ${tomlString(privateKey)}
GITHUB_APP_INSTALLATION_ID = "67890"
TARGET_OWNER = "runtime-target-owner"
TARGET_REPO = "runtime-target-repo"
EVENT_TYPE = "runtime-test-event"

[alias]
"@octokit/auth-app" = ${tomlString(path.join(fixtureDir, "mock-auth.mjs"))}
"@octokit/request" = ${tomlString(path.join(fixtureDir, "mock-request.mjs"))}
`;
  await Promise.all([
    fs.writeFile(mockAuthPath, authSource),
    fs.writeFile(mockRequestPath, requestSource),
    fs.writeFile(configPath, config),
  ]);
  return { configPath };
}

function redactLog(value) {
  return [secret, token, privateKey].reduce((result, sensitive) => {
    return result.split(sensitive).join("[REDACTED]");
  }, value);
}

async function main() {
  const logPath = parseLogPath(process.argv.slice(2));
  const fixtureDir = await fs.mkdtemp(path.join(os.tmpdir(), "kodi-worker-runtime-"));
  const resultLines = [];
  let capturedOutput = "";
  let child;
  let childClosed;
  let spawnError;
  let testError;

  const appendOutput = (chunk) => {
    capturedOutput = (capturedOutput + chunk.toString("utf8")).slice(-4 * 1024 * 1024);
  };
  const closeState = new Promise((resolve) => {
    childClosed = resolve;
  });

  try {
    const fixtures = await writeFixtures(fixtureDir);
    const port = await reservePort();
    const wranglerPath = path.join(workerRoot, "node_modules/wrangler/bin/wrangler.js");
    const statePath = path.join(fixtureDir, "state");
    await fs.mkdir(statePath);
    const args = [
      wranglerPath,
      "dev",
      "--config", fixtures.configPath,
      "--ip", "127.0.0.1",
      "--port", String(port),
      "--persist-to", statePath,
      "--local",
      "--latest=false",
      "--show-interactive-dev-session=false",
    ];
    const childEnv = {
      PATH: process.env.PATH,
      HOME: path.join(fixtureDir, "home"),
      XDG_CONFIG_HOME: path.join(fixtureDir, "config-home"),
      CI: "1",
      NO_UPDATE_NOTIFIER: "1",
      WRANGLER_SEND_METRICS: "false",
      FORCE_COLOR: "0",
    };
    await Promise.all([fs.mkdir(childEnv.HOME), fs.mkdir(childEnv.XDG_CONFIG_HOME)]);
    child = spawn(process.execPath, args, {
      cwd: workerRoot,
      env: childEnv,
      stdio: ["ignore", "pipe", "pipe"],
      detached: process.platform !== "win32",
    });
    child.stdout.on("data", appendOutput);
    child.stderr.on("data", appendOutput);
    child.once("error", (error) => {
      spawnError = error;
      appendOutput(`\nChild process error: ${error.message}\n`);
    });
    child.once("close", (code, signal) => childClosed({ code, signal }));

    const baseUrl = `http://127.0.0.1:${port}/`;
    const readyDeadline = Date.now() + 30000;
    let ready = false;
    while (Date.now() < readyDeadline) {
      if (spawnError) throw new Error("Wrangler could not start");
      if (child.exitCode !== null || child.signalCode !== null) throw new Error("Wrangler exited before local startup");
      try {
        const response = await fetch(baseUrl, { signal: AbortSignal.timeout(500) });
        if (response.status === 405) {
          ready = true;
          break;
        }
      } catch {
        await wait(100);
      }
    }
    assert.equal(ready, true, "local Worker failed to become ready");

    const ping = await readJson(await postEvent(
      baseUrl,
      "ping",
      "runtime-ping",
      { zen: "runtime ping" },
    ));
    assert.equal(ping.status, 200);
    assert.deepEqual(ping.body, { ok: true, delivery: "runtime-ping", event: "ping" });
    resultLines.push("PASS signed ping");

    const badSignature = await readJson(await postEvent(
      baseUrl,
      "push",
      "runtime-bad-signature",
      undefined,
      { body: "not-json", invalidSignature: true },
    ));
    assert.equal(badSignature.status, 401);
    assert.deepEqual(badSignature.body, { error: "bad_signature" });
    resultLines.push("PASS rejected signature");

    const ignoredBranch = await readJson(await postEvent(
      baseUrl,
      "push",
      "runtime-ignored-branch",
      { repository: { full_name: repository }, ref: "refs/heads/feature/runtime", after: sha },
    ));
    assert.equal(ignoredBranch.status, 200);
    assert.equal(ignoredBranch.body.ignored, "branch");
    resultLines.push("PASS ignored branch");

    const allowedPush = await readJson(await postEvent(
      baseUrl,
      "push",
      expectedDispatch.client_payload.delivery,
      { repository: { full_name: repository }, ref: `refs/heads/${branch}`, after: sha },
    ));
    assert.equal(allowedPush.status, 200);
    assert.equal(allowedPush.body.dispatched, true);
    assert.equal(allowedPush.body.sourceRepository, repository);
    resultLines.push("PASS allowed push reached local dispatch mock");

    const dispatchDeadline = Date.now() + 2000;
    let dispatchLines = [];
    while (Date.now() < dispatchDeadline) {
      dispatchLines = capturedOutput.split(/\r?\n/).filter((line) => line.includes(dispatchMarker));
      if (dispatchLines.length > 0) break;
      await wait(25);
    }
    assert.equal(dispatchLines.length, 1, "one local dispatch mock call must be recorded");
    const recordText = dispatchLines[0].slice(dispatchLines[0].indexOf(dispatchMarker) + dispatchMarker.length).trim();
    assert.deepEqual(JSON.parse(recordText), expectedDispatch);
  } catch (error) {
    testError = error;
  } finally {
    if (child && child.exitCode === null && child.signalCode === null) {
      try {
        if (process.platform === "win32") child.kill("SIGINT");
        else process.kill(-child.pid, "SIGINT");
      } catch (error) {
        if (error.code !== "ESRCH") testError ??= error;
      }
      const stopped = await Promise.race([closeState.then(() => true), wait(5000).then(() => false)]);
      if (!stopped && child.exitCode === null && child.signalCode === null) {
        try {
          if (process.platform === "win32") child.kill("SIGTERM");
          else process.kill(-child.pid, "SIGTERM");
        } catch (error) {
          if (error.code !== "ESRCH") testError ??= error;
        }
        await Promise.race([closeState, wait(5000)]);
        if (child.exitCode === null && child.signalCode === null) {
          try {
            if (process.platform === "win32") child.kill("SIGKILL");
            else process.kill(-child.pid, "SIGKILL");
          } catch (error) {
            if (error.code !== "ESRCH") testError ??= error;
          }
          await closeState;
        }
      }
    }

    try {
      await fs.rm(fixtureDir, { recursive: true, force: true });
    } catch (error) {
      testError ??= error;
    }
    try {
      await fs.mkdir(path.dirname(logPath), { recursive: true });
      const detail = testError ? `FAIL ${testError.message}` : "PASS local runtime verification";
      const text = redactLog([
        "Command: npm run test:runtime",
        ...resultLines,
        detail,
        "",
        capturedOutput,
      ].join("\n"));
      await fs.writeFile(logPath, text);
    } catch (error) {
      testError ??= error;
    }
  }

  if (testError) {
    console.error(`FAIL ${testError.message}`);
    console.error(`Redacted log: ${logPath}`);
    process.exitCode = 1;
    return;
  }
  for (const line of resultLines) console.log(line);
  console.log(`Redacted log: ${logPath}`);
}

await main();
