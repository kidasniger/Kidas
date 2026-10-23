import { timingSafeEqual } from 'node:crypto';
import { del, list } from '@vercel/blob';
import { publicError, send } from '../lib/kidas-server.js';

const MAX_AGE_MS = 48 * 60 * 60 * 1000;
const PAGE_SIZE = 1000;
const MAX_PAGES = 5;
const PATH_PATTERN = /^incoming\/v[a-z0-9]{12,40}\.html$/;

function authorized(req) {
  const secret = process.env.CRON_SECRET;
  if (!secret) return false;
  const expected = Buffer.from(`Bearer ${secret}`);
  const supplied = Buffer.from(String(req.headers.authorization || ''));
  return expected.length === supplied.length && timingSafeEqual(expected, supplied);
}

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'Méthode non autorisée.' });
  if (!authorized(req)) return send(res, 401, { error: 'Non autorisé.' });

  try {
    const cutoff = Date.now() - MAX_AGE_MS;
    let cursor;
    let hasMore = true;
    let scanned = 0;
    const stale = [];

    for (let pageNumber = 0; pageNumber < MAX_PAGES && hasMore; pageNumber += 1) {
      const page = await list({ prefix: 'incoming/', limit: PAGE_SIZE, cursor });
      const blobs = Array.isArray(page.blobs) ? page.blobs : [];
      scanned += blobs.length;
      for (const blob of blobs) {
        const pathname = String(blob.pathname || '');
        if (!PATH_PATTERN.test(pathname)) continue;
        const uploadedAt = new Date(blob.uploadedAt).getTime();
        if (Number.isFinite(uploadedAt) && uploadedAt < cutoff) stale.push(pathname);
      }
      cursor = page.cursor;
      hasMore = Boolean(page.hasMore && cursor);
    }

    for (let i = 0; i < stale.length; i += 100) {
      await del(stale.slice(i, i + 100));
    }

    return send(res, 200, {
      success: true,
      scanned,
      deleted: stale.length,
      olderThanHours: 48,
      morePending: hasMore
    });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
