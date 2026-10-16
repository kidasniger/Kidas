import { githubRequest, readBody, sameOrigin, send, publicError } from '../lib/kidas-server.js';

const REPOSITORY = 'kidasniger/Kidas';
const RENDER_WORKFLOW = 'render.yml';
const VIDEO_ARTIFACT_NAME = 'video-mp4';
const RUNS_PAGE_SIZE = 100;
const MAX_RUN_PAGES = 20;

async function findRenderRun(tag) {
  const expectedName = `Rendu ${tag}`;

  for (let page = 1; page <= MAX_RUN_PAGES; page += 1) {
    const { data } = await githubRequest(
      `/repos/${REPOSITORY}/actions/workflows/${RENDER_WORKFLOW}/runs?event=workflow_dispatch&branch=main&per_page=${RUNS_PAGE_SIZE}&page=${page}`
    );
    const runs = Array.isArray(data?.workflow_runs) ? data.workflow_runs : [];
    const match = runs.find(run =>
      run.name === expectedName && run.path === `.github/workflows/${RENDER_WORKFLOW}`
    );

    if (match) return match;
    if (runs.length < RUNS_PAGE_SIZE) return null;
  }

  const error = new Error('Le rendu associé à cette vidéo est trop ancien pour être localisé automatiquement. Aucune suppression n’a été effectuée.');
  error.status = 503;
  throw error;
}

async function deleteVideoArtifact(runId) {
  const { data } = await githubRequest(
    `/repos/${REPOSITORY}/actions/runs/${runId}/artifacts?per_page=100`
  );
  const artifacts = Array.isArray(data?.artifacts) ? data.artifacts : [];

  for (const artifact of artifacts) {
    if (artifact.name !== VIDEO_ARTIFACT_NAME) continue;
    try {
      await githubRequest(
        `/repos/${REPOSITORY}/actions/artifacts/${artifact.id}`,
        { method: 'DELETE' }
      );
    } catch (error) {
      // Missing/expired artifacts are already unavailable; all other errors
      // must stop the operation before the public Release is removed.
      if (error.status !== 404 && error.status !== 410) throw error;
    }
  }
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!sameOrigin(req)) return send(res, 403, { error: 'Origine de la demande refusée.' });

  const { releaseId, tag } = readBody(req);
  if (!/^\d+$/.test(String(releaseId || '')) || !/^[A-Za-z0-9._-]{1,100}$/.test(String(tag || ''))) {
    return send(res, 400, { error: 'Vidéo ou identifiant invalide.' });
  }

  try {
    const { data: release } = await githubRequest(
      `/repos/${REPOSITORY}/releases/${releaseId}`
    );
    if (release?.tag_name !== tag) {
      return send(res, 400, { error: 'La vidéo et le tag ne correspondent pas.' });
    }

    // Delete the Actions artifact first. If the token lacks Actions write
    // permission, keep the public Release and tag intact so the operation can
    // be retried after the token permissions are fixed.
    const run = await findRenderRun(tag);
    if (run) await deleteVideoArtifact(run.id);

    await githubRequest(
      `/repos/${REPOSITORY}/releases/${releaseId}`,
      { method: 'DELETE' }
    );

    try {
      await githubRequest(
        `/repos/${REPOSITORY}/git/refs/tags/${encodeURIComponent(tag)}`,
        { method: 'DELETE' }
      );
    } catch (error) {
      if (error.status !== 404) throw error;
    }

    return send(res, 200, { success: true, artifactRemoved: Boolean(run), releaseRemoved: true, tagRemoved: true });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
