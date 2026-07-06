const express = require('express');
const rp = require('request-promise');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3002;

app.use(cors());
app.use(express.json());

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'instagram-scraper' });
});

// Normalize Instagram URL to shortcode
function extractShortcode(url) {
  // https://www.instagram.com/p/ABC123/
  // https://www.instagram.com/reel/ABC123/
  const match = url.match(/(?:instagram\.com\/(?:p|reel|tv)\/)([\w-]+)/);
  return match ? match[1] : null;
}

// Fetch Instagram post metadata
app.get('/api/video-meta', async (req, res) => {
  const { url } = req.query;
  if (!url) return res.status(400).json({ error: 'url parameter required' });

  const shortcode = extractShortcode(url);
  if (!shortcode) return res.status(400).json({ error: 'Invalid Instagram URL' });

  try {
    const response = await rp({
      uri: `https://www.instagram.com/p/${shortcode}/`,
      qs: { __a: 1, __d: 'dis' },
      json: true,
      timeout: 15000,
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.230 Mobile Safari/537.36',
      },
    });

    const media = response?.graphql?.shortcode_media || response?.items?.[0]?.shortcode_media;
    if (!media) {
      return res.status(502).json({ error: 'Could not parse Instagram response' });
    }

    const result = {
      shortcode: media.shortcode || shortcode,
      likes: media.edge_media_preview_like?.count || 0,
      comments: media.edge_media_to_comment?.count || 0,
      views: media.video_view_count || 0,
      is_video: media.is_video || false,
      caption: media.edge_media_to_caption?.edges?.[0]?.node?.text || '',
      taken_at: media.taken_at_timestamp || null,
      owner: {
        id: media.owner?.id || '',
        username: media.owner?.username || '',
        is_verified: media.owner?.is_verified || false,
        profile_pic_url: media.owner?.profile_pic_url || '',
      },
      thumbnail: media.display_url || '',
    };

    res.json({ success: true, data: result });
  } catch (err) {
    res.status(502).json({ error: 'Instagram fetch failed: ' + (err.message || err) });
  }
});

app.listen(PORT, () => {
  console.log(`Instagram scraper service running on port ${PORT}`);
});