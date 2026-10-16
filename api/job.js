import { githubRequest, send, validJobId, publicError } from '../lib/kidas-server.js';

function releaseSummary(release) {
  return {
    id: release.id,
    tag_name: release.tag_name,
    name: release.name,
    created_at: release.created_at,
    html_url: release.html_url,
    assets: (release.assets || [])
      .filter(asset => asset.name.toLowerCase().endsWith('.mp4'))
      .map(asset => ({
        name: asset.name,
        size: asset.size,
        browser_download_url: asset.browser_download_url
      }))
  };
}

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'Méthode non autorisée.' });
  const id = String(req.query?.id || '');
  if (!validJobId(id)) return send(res, 400, { error: 'Identifiant de rendu invalide.' });
  try {
    const runs = await githubRequest('/repos/kidasniger/Kidas/actions/runs?event=workflow_dispatch&per_page=100');
    const run = (runs.data.workflow_runs || []).find(item => item.display_title === `Rendu ${id}`);
    if (!run) return send(res, 200, { found: false });
    const result = {
      found: true,
      runId: run.id,
      status: run.status,
      conclusion: run.conclusion,
      html_url: run.html_url,
      release: null
    };
    if (run.status === 'completed' && run.conclusion === 'success') {
      try {
        const release = await githubRequest(`/repos/kidasniger/Kidas/releases/tags/${encodeURIComponent(id)}`);
        result.release = releaseSummary(release.data);
      } catch (error) {
        if (error.status !== 404) throw error;
      }
    }
    return send(res, 200, result);
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
