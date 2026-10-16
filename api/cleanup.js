import { del } from '@vercel/blob';
import { readBody, sameOrigin, send, validJobId, verifyGitHubActionsRequest, publicError } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  const { id, run_id: runId } = readBody(req);
  if (!validJobId(id)) return send(res, 400, { error: 'Identifiant temporaire invalide.' });

  try {
    // The website can clean up a failed upload from the same origin.
    // GitHub Actions must prove its identity through a short-lived OIDC token.
    if (!sameOrigin(req)) {
      await verifyGitHubActionsRequest(req, runId);
    }
    await del(`incoming/${id}.html`);
    return send(res, 200, { success: true });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
