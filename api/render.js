import { head, issueSignedToken, presignUrl } from '@vercel/blob';
import { githubRequest, readBody, safeName, sameOrigin, send, validJobId, verifyTurnstile, publicError } from '../lib/kidas-server.js';

const MAX_BYTES = 50 * 1000 * 1000;
const FORMATS = new Set(['auto', 'portrait', 'landscape', 'square']);
const FPS = new Set(['15', '24', '30']);
const DURATIONS = new Set(['0', '10', '30', '60', '120', '300']);

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!sameOrigin(req)) return send(res, 403, { error: 'Origine de la demande refusée.' });
  const { id, captchaToken, fps, scale, test, duration, format, name } = readBody(req);
  if (!validJobId(id)) return send(res, 400, { error: 'Identifiant temporaire invalide.' });
  if (!FPS.has(String(fps)) || !['0.5', '1'].includes(String(scale)) ||
      !['0', '10'].includes(String(test)) || !DURATIONS.has(String(duration)) || !FORMATS.has(String(format))) {
    return send(res, 400, { error: 'Réglages de conversion invalides.' });
  }
  let stage = 'vérification de sécurité';
  try {
    await verifyTurnstile(req, captchaToken);
    stage = 'lecture du HTML dans le stockage privé';
    if (!process.env.BLOB_STORE_ID) {
      const error = new Error('Le stockage Blob privé doit être connecté au projet Vercel.');
      error.status = 503;
      throw error;
    }
    const pathname = `incoming/${id}.html`;
    const metadata = await head(pathname);
    if (Number(metadata.size) > MAX_BYTES) {
      const error = new Error('Fichier trop volumineux (50 Mo maximum).');
      error.status = 413;
      throw error;
    }
    stage = 'création des liens temporaires de lecture et suppression';
    const validUntil = Date.now() + 110 * 60 * 1000;
    const sourceToken = await issueSignedToken({
      pathname,
      operations: ['get'],
      validUntil
    });
    const deleteToken = await issueSignedToken({
      pathname,
      operations: ['delete'],
      validUntil
    });
    const sourceUrl = await presignUrl(sourceToken, {
      operation: 'get',
      pathname,
      access: 'private',
      validUntil,
      useCache: false
    });
    const deleteUrl = await presignUrl(deleteToken, {
      operation: 'delete',
      pathname,
      access: 'private',
      validUntil
    });
    const inputs = {
      fichier: 'kidas.html',
      blob_id: id,
      source_url: sourceUrl.presignedUrl,
      delete_url: deleteUrl.presignedUrl,
      fps: String(fps),
      scale: String(scale),
      test: String(test),
      duration: String(duration),
      format: String(format),
      nom: safeName(name),
      qualite: 'standard',
      loudnorm: false,
      tag: id
    };
    stage = 'déclenchement du workflow GitHub Actions';
    await githubRequest('/repos/kidasniger/Kidas/actions/workflows/render.yml/dispatches', {
      method: 'POST',
      body: { ref: 'main', inputs }
    });
    return send(res, 202, { id });
  } catch (error) {
    const status = Number(error?.status) || 500;
    console.error('[Kidas render]', {
      stage,
      name: error?.name || 'Error',
      status,
      code: error?.code || null
    });
    if (status >= 500) {
      return send(res, 502, {
        error: `Échec pendant l’étape : ${stage}. Ouvre les journaux Functions de Vercel si l’erreur persiste.`,
        stage
      });
    }
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
