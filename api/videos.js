import { githubRequest, send, publicError } from './_lib.js';

export default async function handler(req, res) {
  if (req.method !== 'GET') return send(res, 405, { error: 'Méthode non autorisée.' });
  try {
    const response = await githubRequest('/repos/kidasniger/Kidas/releases?per_page=12');
    const items = (response.data || []).map(release => ({
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
    })).filter(release => release.assets.length > 0);
    return send(res, 200, { items });
  } catch (error) {
    const result = publicError(error);
    return send(res, result.status, result.body);
  }
}
