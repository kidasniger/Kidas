const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const ALLOWED_FPS = new Set(["15", "24", "30"]);
const ALLOWED_SCALE = new Set(["0.5", "1"]);
const ALLOWED_TEST = new Set(["0", "10"]);
const ALLOWED_DURATION = new Set(["0", "10", "30", "60", "120", "300"]);
const ALLOWED_FORMAT = new Set(["auto", "portrait", "landscape", "square"]);
const JOB_ID_RE = /^[0-9a-f-]{36}$/i;
const GITHUB_API = "https://api.github.com";
const REPO = "kidasniger/Kidas";
const WORKFLOW = "render.yml";

function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function headersFor(request, env) {
  const headers = new Headers({
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Vary": "Origin",
  });
  const origin = request.headers.get("Origin");
  if (origin && allowedOrigins(env).includes(origin)) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Content-Type");
    headers.set("Access-Control-Max-Age", "86400");
  }
  return headers;
}

function json(request, env, data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: headersFor(request, env),
  });
}

function originAllowed(request, env) {
  const origin = request.headers.get("Origin");
  return !origin || allowedOrigins(env).includes(origin);
}

function requireConfiguration(env) {
  return Boolean(
    env.GITHUB_TOKEN &&
    env.KIDAS_JOB_SECRET &&
    env.TURNSTILE_SECRET &&
    env.KIDAS_JOBS &&
    env.SUBMISSION_LIMIT &&
    env.STATUS_LIMIT &&
    allowedOrigins(env).length
  );
}

async function verifyTurnstile(token, request, env) {
  if (typeof token !== "string" || token.length < 10 || token.length > 2048) {
    return false;
  }
  const form = new FormData();
  form.set("secret", env.TURNSTILE_SECRET);
  form.set("response", token);
  const ip = request.headers.get("CF-Connecting-IP");
  if (ip) form.set("remoteip", ip);

  const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body: form,
  });
  if (!response.ok) return false;

  const result = await response.json();
  if (!result.success || result.action !== "render") return false;
  const expectedHosts = new Set(
    allowedOrigins(env).map((origin) => {
      try { return new URL(origin).hostname; } catch { return ""; }
    }).filter(Boolean)
  );
  return expectedHosts.has(result.hostname);
}

async function github(path, env, options = {}) {
  const response = await fetch(GITHUB_API + path, {
    ...options,
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      "X-GitHub-Api-Version": "2022-11-28",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(`GitHub API returned ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

function safeJobId(value) {
  return typeof value === "string" && JOB_ID_RE.test(value);
}

async function submitJob(request, env) {
  if (!requireConfiguration(env)) {
    return json(request, env, { error: "Le service de rendu n'est pas encore configuré." }, 503);
  }
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const allowed = await env.SUBMISSION_LIMIT.limit({ key: ip });
  if (!allowed.success) {
    return json(request, env, { error: "Trop de demandes rapprochées. Réessaie dans une minute." }, 429);
  }

  let form;
  try {
    form = await request.formData();
  } catch {
    return json(request, env, { error: "Formulaire d'envoi invalide." }, 400);
  }

  if (form.get("consent") !== "yes") {
    return json(request, env, { error: "Confirme que tu disposes des droits nécessaires sur les contenus importés." }, 400);
  }
  try {
    if (!await verifyTurnstile(form.get("cf-turnstile-response"), request, env)) {
      return json(request, env, { error: "Vérification anti-robot refusée. Actualise le contrôle puis réessaie." }, 403);
    }
  } catch {
    return json(request, env, { error: "La vérification anti-robot est momentanément indisponible." }, 502);
  }

  const file = form.get("file");
  if (!file || typeof file.arrayBuffer !== "function" || typeof file.name !== "string") {
    return json(request, env, { error: "Sélectionne un fichier HTML." }, 400);
  }
  if (!/\.html?$/i.test(file.name)) {
    return json(request, env, { error: "Seuls les fichiers .html et .htm sont acceptés." }, 400);
  }
  if (file.size <= 0 || file.size > MAX_UPLOAD_BYTES) {
    return json(request, env, { error: "Le fichier doit peser entre 1 octet et 10 Mio." }, 413);
  }

  let html;
  try {
    html = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
  } catch {
    return json(request, env, { error: "Le fichier doit être un document texte UTF-8 valide." }, 400);
  }
  if (!/<html\b/i.test(html) || !/<(?:body|head|script|svg|canvas|div|style)\b/i.test(html)) {
    return json(request, env, { error: "Le fichier ne semble pas être une page HTML exploitable." }, 400);
  }

  const fps = String(form.get("fps") || "30");
  const scale = String(form.get("scale") || "1");
  const test = String(form.get("test") || "0");
  const duration = String(form.get("duration") || "0");
  const format = String(form.get("format") || "auto");
  if (!ALLOWED_FPS.has(fps) || !ALLOWED_SCALE.has(scale) ||
      !ALLOWED_TEST.has(test) || !ALLOWED_DURATION.has(duration) || !ALLOWED_FORMAT.has(format)) {
    return json(request, env, { error: "Réglages de rendu invalides." }, 400);
  }

  const id = crypto.randomUUID();
  const tag = `kidas-${id}`;
  const createdAt = new Date().toISOString();
  const sourceKey = `jobs/${id}/source.html`;
  const metadataKey = `jobs/${id}/metadata.json`;
  const metadata = {
    id,
    tag,
    createdAt,
    originalName: file.name.replace(/[\\/\\\\]/g, "_").slice(0, 160),
    status: "queued",
  };

  try {
    await env.KIDAS_JOBS.put(sourceKey, html, {
      httpMetadata: { contentType: "text/html; charset=utf-8" },
      customMetadata: { createdAt },
    });
    await env.KIDAS_JOBS.put(metadataKey, JSON.stringify(metadata), {
      httpMetadata: { contentType: "application/json; charset=utf-8" },
      customMetadata: { createdAt },
    });
    await github(`/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, env, {
      method: "POST",
      body: JSON.stringify({
        ref: "main",
        inputs: {
          fichier: "kidas.html",
          job_id: id,
          fps,
          scale,
          test,
          duration,
          format,
          tag,
        },
      }),
    });
  } catch (error) {
    await Promise.allSettled([
      env.KIDAS_JOBS.delete(sourceKey),
      env.KIDAS_JOBS.delete(metadataKey),
    ]);
    console.error("Kidas job submission failed", error.status || "network");
    return json(request, env, {
      error: "Impossible de lancer le rendu. Le service est peut-être temporairement indisponible.",
    }, 502);
  }

  return json(request, env, {
    id,
    status: "queued",
    statusUrl: `/api/jobs/${id}`,
    message: "Projet accepté. Le rendu va démarrer.",
  }, 202);
}

async function jobStatus(request, env, id) {
  if (!safeJobId(id)) {
    return json(request, env, { error: "Identifiant de tâche invalide." }, 400);
  }
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const limit = await env.STATUS_LIMIT.limit({ key: `${ip}:${id}` });
  if (!limit.success) {
    return json(request, env, { error: "Trop de vérifications. Réessaie dans un instant." }, 429);
  }

  const resultKey = `jobs/${id}/result.json`;
  const savedResult = await env.KIDAS_JOBS.get(resultKey);
  if (savedResult) {
    return json(request, env, await savedResult.json());
  }
  const metadata = await env.KIDAS_JOBS.get(`jobs/${id}/metadata.json`);
  if (!metadata) {
    return json(request, env, { error: "Tâche introuvable ou expirée." }, 404);
  }
  const { tag } = await metadata.json();

  let runs;
  try {
    runs = await github(`/repos/${REPO}/actions/runs?event=workflow_dispatch&per_page=100`, env);
  } catch (error) {
    console.error("Kidas status lookup failed", error.status || "network");
    return json(request, env, { error: "Impossible de consulter la progression pour le moment." }, 502);
  }
  const run = (runs.workflow_runs || []).find((item) =>
    item.display_title === `Rendu ${tag}` || item.name === `Rendu ${tag}`
  );
  if (!run) {
    return json(request, env, {
      id,
      status: "queued",
      message: "En attente du démarrage du moteur de rendu.",
    });
  }
  if (run.status !== "completed") {
    return json(request, env, {
      id,
      status: run.status === "queued" || run.status === "waiting" ? "queued" : "processing",
      logsUrl: run.html_url,
      message: run.status === "queued" ? "Dans la file d'attente." : "Rendu de la vidéo en cours.",
    });
  }

  let finalResult;
  if (run.conclusion === "success") {
    try {
      const release = await github(`/repos/${REPO}/releases/tags/${tag}`, env);
      const videos = (release.assets || [])
        .filter((asset) => typeof asset.name === "string" && asset.name.toLowerCase().endsWith(".mp4"))
        .map((asset) => ({
          name: asset.name,
          url: asset.browser_download_url,
          size: asset.size,
        }));
      finalResult = {
        id,
        status: videos.length ? "completed" : "failed",
        conclusion: videos.length ? "success" : "missing_video",
        videos,
        logsUrl: run.html_url,
        message: videos.length ? "Vidéo prête à être téléchargée." : "Le rendu est terminé, mais aucun MP4 n'a été publié.",
      };
    } catch {
      finalResult = {
        id, status: "failed", conclusion: "missing_release", logsUrl: run.html_url,
        message: "Le rendu est terminé, mais la publication de la vidéo est introuvable.",
      };
    }
  } else {
    finalResult = {
      id, status: "failed", conclusion: run.conclusion || "failure", logsUrl: run.html_url,
      message: "Le rendu a échoué. Consulte le journal pour connaître la cause.",
    };
  }

  await env.KIDAS_JOBS.put(resultKey, JSON.stringify(finalResult), {
    httpMetadata: { contentType: "application/json; charset=utf-8" },
    customMetadata: { createdAt: new Date().toISOString() },
  });
  await Promise.allSettled([
    env.KIDAS_JOBS.delete(`jobs/${id}/source.html`),
    env.KIDAS_JOBS.delete(`jobs/${id}/metadata.json`),
  ]);
  return json(request, env, finalResult);
}

async function internalSource(request, env, id) {
  if (!env.KIDAS_JOB_SECRET || request.headers.get("Authorization") !== `Bearer ${env.KIDAS_JOB_SECRET}`) {
    return new Response("Unauthorized", { status: 401, headers: { "Cache-Control": "no-store" } });
  }
  if (!safeJobId(id)) return new Response("Invalid job id", { status: 400 });
  const object = await env.KIDAS_JOBS.get(`jobs/${id}/source.html`);
  if (!object) return new Response("Source expired or not found", { status: 404 });
  return new Response(await object.text(), {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

async function cleanupExpired(env) {
  const expiry = Date.now() - 72 * 60 * 60 * 1000;
  let cursor;
  do {
    const page = await env.KIDAS_JOBS.list({ prefix: "jobs/", cursor, limit: 1000 });
    const expired = page.objects
      .filter((object) => object.uploaded && object.uploaded.getTime() < expiry)
      .map((object) => object.key);
    if (expired.length) await env.KIDAS_JOBS.delete(expired);
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "OPTIONS") {
      if (!originAllowed(request, env)) return new Response(null, { status: 403 });
      return new Response(null, { status: 204, headers: headersFor(request, env) });
    }
    if (!originAllowed(request, env)) {
      return json(request, env, { error: "Origine non autorisée." }, 403);
    }
    if (path === "/health" && request.method === "GET") {
      return json(request, env, {
        ok: true,
        service: "Kidas Public Render API",
        configured: requireConfiguration(env),
      }, requireConfiguration(env) ? 200 : 503);
    }
    if (path === "/api/jobs" && request.method === "POST") {
      return submitJob(request, env);
    }
    const statusMatch = path.match(/^\/api\/jobs\/([^/]+)$/);
    if (statusMatch && request.method === "GET") {
      if (!requireConfiguration(env)) {
        return json(request, env, { error: "Le service de rendu n'est pas encore configuré." }, 503);
      }
      return jobStatus(request, env, statusMatch[1]);
    }
    const sourceMatch = path.match(/^\/internal\/jobs\/([^/]+)\/source$/);
    if (sourceMatch && request.method === "GET") {
      if (!env.KIDAS_JOBS) return new Response("Service unavailable", { status: 503 });
      return internalSource(request, env, sourceMatch[1]);
    }
    return json(request, env, { error: "Route introuvable." }, 404);
  },

  async scheduled(_controller, env, ctx) {
    ctx.waitUntil(cleanupExpired(env));
  },
};
