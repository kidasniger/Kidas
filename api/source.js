import { get } from '@vercel/blob';
import { Readable } from 'node:stream';
import { publicError, send, verifyWorkflowCapability } from '../lib/kidas-server.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'Méthode non autorisée.' });
  const id = String(req.query?.id || '');
  const expires = String(req.query?.expires || '');
  const signature = String(req.query?.signature || '');
  if (!verifyWorkflowCapability('source', id, expires, signature)) {
    return send(res, 403, { error: 'Lien temporaire invalide ou expiré.' });
  }

  try {
    const result = await get(`incoming/${id}.html`, { access: 'private', useCache: false });
    if (!result || result.statusCode !== 200) {
      return send(res, 404, { error: 'Le HTML temporaire est introuvable ou déjà supprimé.' });
    }
    res.statusCode = 200;
    res.setHeader('Content-Type', result.blob.contentType || 'text/html; charset=utf-8');
    res.setHeader('Content-Disposition', 'attachment; filename="input.html"');
    res.setHeader('Cache-Control', 'private, no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    const stream = Readable.fromWeb(result.stream);
    stream.on('error', error => {
      if (res.headersSent) res.destroy(error);
      else {
        const response = publicError(error);
        send(res, response.status, response.body);
      }
    });
    stream.pipe(res);
  } catch (error) {
    const response = publicError(error);
    return send(res, response.status, response.body);
  }
}
