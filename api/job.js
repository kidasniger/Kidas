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
    if (req.query?.details === '1' || (run.status === 'completed' && run.conclusion !== 'success')) {
      try {
        const response = await githubRequest(`/repos/kidasniger/Kidas/actions/runs/${run.id}/jobs?per_page=20`);
        const jobs = Array.isArray(response.data?.jobs) ? response.data.jobs : [];
        const activeJob = jobs.find(item => item.status === 'in_progress') ||
          jobs.find(item => item.conclusion === 'failure') || jobs[0];
        if (activeJob && Array.isArray(activeJob.steps)) {
          const step = activeJob.steps.find(item => item.status === 'in_progress') ||
            activeJob.steps.find(item => item.conclusion === 'failure') ||
            (run.status === 'completed' ? activeJob.steps.find(item => item.conclusion === 'cancelled') : null);
          if (step) {
            result.currentStep = step.name;
            result.currentStepStatus = step.status;
            result.stepConclusion = step.conclusion;
          }
        }
      } catch (detailsError) {
        console.warn('[Kidas job details]', detailsError?.status || detailsError?.name || 'error');
      }
    }
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
