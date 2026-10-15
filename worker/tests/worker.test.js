import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const SOURCE = "<!doctype html><html><head></head><body><h1>Publicité</h1></body></html>";
const ORIGIN = "https://kidasniger.github.io";
const originalFetch = globalThis.fetch;
let githubRuns = [];
let dispatchBody = null;
let turnstileSuccess = true;

class MemoryBucket {
  constructor() { this.values = new Map(); }
  async put(key, value, options = {}) {
    const body = typeof value === "string" ? value : new TextDecoder().decode(value);
    this.values.set(key, { body, uploaded: new Date(), httpMetadata: options.httpMetadata || {} });
  }
  async get(key) {
    const item = this.values.get(key);
    if (!item) return null;
    return {
      uploaded: item.uploaded,
      text: async () => item.body,
      json: async () => JSON.parse(item.body),
      arrayBuffer: async () => new TextEncoder().encode(item.body).buffer,
    };
  }
  async delete(keyOrKeys) {
    for (const key of Array.isArray(keyOrKeys) ? keyOrKeys : [keyOrKeys]) this.values.delete(key);
  }
  async list({ prefix = "" } = {}) {
    return {
      objects: [...this.values.entries()]
        .filter(([key]) => key.startsWith(prefix))
        .map(([key, value]) => ({ key, uploaded: value.uploaded })),
      truncated: false,
      cursor: undefined,
    };
  }
}

const bucket = new MemoryBucket();
const env = {
  GITHUB_TOKEN: "github-test-token",
  KIDAS_JOB_SECRET: "internal-test-secret",
  TURNSTILE_SECRET: "turnstile-test-secret",
  ALLOWED_ORIGINS: ORIGIN,
  KIDAS_JOBS: bucket,
  SUBMISSION_LIMIT: { limit: async () => ({ success: true }) },
  STATUS_LIMIT: { limit: async () => ({ success: true }) },
};

function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Origin")) headers.set("Origin", ORIGIN);
  return new Request("https://api.example.test" + path, { ...options, headers });
}

function renderForm({ name = "advert.html", html = SOURCE, turnstile = "turnstile-response" } = {}) {
  const form = new FormData();
  form.set("file", new File([html], name, { type: "text/html" }));
  form.set("consent", "yes");
  form.set("cf-turnstile-response", turnstile);
  form.set("fps", "30");
  form.set("scale", "1");
  form.set("test", "0");
  form.set("duration", "60");
  form.set("format", "landscape");
  return form;
}

function mockNetwork() {
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    if (url.includes("/turnstile/v0/siteverify")) {
      return Response.json({
        success: turnstileSuccess,
        action: "render",
        hostname: "kidasniger.github.io",
      });
    }
    if (url.endsWith("/actions/workflows/render.yml/dispatches")) {
      dispatchBody = JSON.parse(init.body);
      return new Response(null, { status: 204 });
    }
    if (url.includes("/actions/runs?")) return Response.json({ workflow_runs: githubRuns });
    if (url.includes("/releases/tags/")) {
      return Response.json({
        assets: [{
          name: "advert.mp4",
          browser_download_url: "https://github.com/kidasniger/Kidas/releases/download/kidas-test/advert.mp4",
          size: 12345,
        }],
      });
    }
    throw new Error("Unexpected network request: " + url);
  };
}

afterEach(() => {
  globalThis.fetch = originalFetch;
  githubRuns = [];
  dispatchBody = null;
  turnstileSuccess = true;
  bucket.values.clear();
});

test("health indicates whether the service is configured without revealing secrets", async () => {
  const response = await worker.fetch(request("/health"), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.configured, true);
  assert.equal(body.ok, true);
  assert.equal(JSON.stringify(body).includes(env.GITHUB_TOKEN), false);
});

test("rejects requests from an origin that is not allowlisted", async () => {
  const response = await worker.fetch(request("/health", { headers: { Origin: "https://evil.example" } }), env);
  assert.equal(response.status, 403);
});

test("rejects a failed Turnstile verification", async () => {
  mockNetwork();
  turnstileSuccess = false;
  const response = await worker.fetch(request("/api/jobs", { method: "POST", body: renderForm() }), env);
  assert.equal(response.status, 403);
  assert.equal(bucket.values.size, 0);
  assert.equal(dispatchBody, null);
});

test("rejects files that are not HTML", async () => {
  mockNetwork();
  const response = await worker.fetch(request("/api/jobs", {
    method: "POST",
    body: renderForm({ name: "ad.exe" }),
  }), env);
  assert.equal(response.status, 400);
  assert.equal(dispatchBody, null);
});

test("stores source in private R2 storage and dispatches a render without a visitor token", async () => {
  mockNetwork();
  const response = await worker.fetch(request("/api/jobs", { method: "POST", body: renderForm() }), env);
  const body = await response.json();
  assert.equal(response.status, 202);
  assert.match(body.id, /^[0-9a-f-]{36}$/i);
  assert.equal(body.status, "queued");
  assert.equal(dispatchBody.ref, "main");
  assert.equal(dispatchBody.inputs.job_id, body.id);
  assert.equal(dispatchBody.inputs.fps, "30");
  assert.equal(dispatchBody.inputs.format, "landscape");
  assert.equal(bucket.values.get(`jobs/${body.id}/source.html`).body, SOURCE);
  assert.equal([...bucket.values.keys()].some((key) => key.startsWith("uploads/")), false);
});

test("protects the internal source endpoint and permits the render runner", async () => {
  const id = "123e4567-e89b-42d3-a456-426614174000";
  await bucket.put(`jobs/${id}/source.html`, SOURCE);
  const denied = await worker.fetch(request(`/internal/jobs/${id}/source`), env);
  assert.equal(denied.status, 401);
  const allowed = await worker.fetch(request(`/internal/jobs/${id}/source`, {
    headers: { Authorization: "Bearer internal-test-secret" },
  }), env);
  assert.equal(allowed.status, 200);
  assert.equal(await allowed.text(), SOURCE);
});

test("reports queued workflow status", async () => {
  mockNetwork();
  const id = "123e4567-e89b-42d3-a456-426614174000";
  await bucket.put(`jobs/${id}/metadata.json`, JSON.stringify({ id, tag: `kidas-${id}` }));
  githubRuns = [];
  const response = await worker.fetch(request(`/api/jobs/${id}`), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.status, "queued");
});

test("publishes the successful result and deletes the private source", async () => {
  mockNetwork();
  const id = "123e4567-e89b-42d3-a456-426614174000";
  const tag = `kidas-${id}`;
  await bucket.put(`jobs/${id}/source.html`, SOURCE);
  await bucket.put(`jobs/${id}/metadata.json`, JSON.stringify({ id, tag }));
  githubRuns = [{
    display_title: `Rendu ${tag}`,
    status: "completed",
    conclusion: "success",
    html_url: "https://github.com/kidasniger/Kidas/actions/runs/123",
  }];
  const response = await worker.fetch(request(`/api/jobs/${id}`), env);
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.status, "completed");
  assert.equal(body.videos[0].url.endsWith("/advert.mp4"), true);
  assert.equal(bucket.values.has(`jobs/${id}/source.html`), false);
  assert.equal(bucket.values.has(`jobs/${id}/metadata.json`), false);
  assert.equal(bucket.values.has(`jobs/${id}/result.json`), true);
});

test("reuses the saved final result without calling GitHub again", async () => {
  const id = "123e4567-e89b-42d3-a456-426614174000";
  const result = { id, status: "completed", videos: [] };
  await bucket.put(`jobs/${id}/result.json`, JSON.stringify(result));
  globalThis.fetch = async () => { throw new Error("GitHub should not be called"); };
  const response = await worker.fetch(request(`/api/jobs/${id}`), env);
  assert.deepEqual(await response.json(), result);
});
