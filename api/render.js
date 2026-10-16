import { head } from '@vercel/blob';
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
  try {
    await verifyTurnstile(req, captchaToken);
    if (!process.env.BLOB_STORE_ID) {
      const error = new Error('Le stockage Blob privé doit être connecté au projet Vercel.');
      error.status = 503;
      throw error;
    }
    const pathname = `incoming/${id}.html`;
    const blobUrl = `https://${process.env.BLOB_STORE_ID}.private.blob.vercel-storage.com/${pathname}`;
    const metadata = await head(blobUrl);
    if (Number(metadata.size) > MAX_BYTES) {
      const error = new Error('Fichier trop volumineux (50 Mo maximum).');
      error.status = 413;
      throw error;
    }
    const inputs = {
      fichier: 'kidas.html',
      blob_id: id,
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
    await githubRequest('/repos/kidasniger/Kidas/actions/workflows/render.yml/dispatches', {
      method: 'POST',
      body: { ref: 'main', inputs }
    });
    return send(res, 202, { id });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
