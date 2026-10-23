import { head } from '@vercel/blob';
import { githubRequest, readBody, safeName, sameOrigin, send, validJobId, verifyTurnstile, publicError } from '../lib/kidas-server.js';

const MAX_BYTES = 50 * 1000 * 1000;
const FORMATS = new Set(['auto', 'portrait', 'landscape', 'square']);
const DURATIONS = new Set(['0', '10', '30', '60', '120', '300']);

export default async function handler(req, res) {
  if (req.method !== 'POST') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!sameOrigin(req)) return send(res, 403, { error: 'Origine de la demande refusée.' });
  const { id, captchaToken, scale, test, duration, format, name, watermark = true } = readBody(req);
  if (!validJobId(id)) return send(res, 400, { error: 'Identifiant temporaire invalide.' });
  if (!['0.5', '1'].includes(String(scale)) ||
      !['0', '10'].includes(String(test)) || !DURATIONS.has(String(duration)) || !FORMATS.has(String(format)) ||
      (typeof watermark !== 'boolean' && !['true', 'false'].includes(String(watermark).toLowerCase()))) {
    return send(res, 400, { error: 'Réglages de conversion invalides.' });
  }
  const watermarkEnabled = typeof watermark === 'boolean'
    ? watermark
    : String(watermark).toLowerCase() === 'true';
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
    stage = 'préparation du déclenchement du rendu';
    const inputs = {
      fichier: 'kidas.html',
      blob_id: id,
      scale: String(scale),
      test: String(test),
      duration: String(duration),
      format: String(format),
      watermark: String(watermarkEnabled),
      nom: safeName(name),
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
