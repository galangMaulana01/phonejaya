const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const { video } = require('tiktok-scraper');

const app = express();
const PORT = process.env.PORT || 3001;

app.use(helmet());
app.use(cors());
app.use(express.json());

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'tiktok-scraper-service' });
});

// Extract video metrics from TikTok URL
app.post('/api/video/metrics', async (req, res) => {
  try {
    const { url } = req.body;
    
    if (!url) {
      return res.status(400).json({ 
        success: false, 
        error: 'URL is required' 
      });
    }

    // Validate TikTok URL
    const tiktokRegex = /(https?:\/\/)?(www\.)?(tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/;
    if (!tiktokRegex.test(url)) {
      return res.status(400).json({ 
        success: false, 
        error: 'Invalid TikTok URL' 
      });
    }

    console.log(`Fetching metrics for: ${url}`);
    
    // Use tiktok-scraper to get video metadata
    const result = await video(url, {
      noWaterMark: false,
      hdVideo: false,
    });

    // The result from tiktok-scraper video() returns metadata
    // We need to extract the video info from the collector
    if (!result || !result.collector || result.collector.length === 0) {
      return res.status(404).json({ 
        success: false, 
        error: 'Video not found or private' 
      });
    }

    const videoData = result.collector[0];
    
    // Extract metrics
    const metrics = {
      video_id: videoData.id,
      views: videoData.stats?.playCount || 0,
      likes: videoData.stats?.diggCount || 0,
      comments: videoData.stats?.commentCount || 0,
      shares: videoData.stats?.shareCount || 0,
      author_username: videoData.author?.uniqueId || '',
      author_nickname: videoData.author?.nickname || '',
      create_time: videoData.createTime ? new Date(videoData.createTime * 1000).toISOString() : null,
      desc: videoData.desc || '',
      duration: videoData.video?.duration || 0,
    };

    console.log(`Successfully fetched metrics for video: ${metrics.video_id}`);
    
    res.json({ 
      success: true, 
      data: metrics 
    });

  } catch (error) {
    console.error('Error fetching TikTok metrics:', error.message);
    
    // Handle specific errors
    if (error.message.includes('Private') || error.message.includes('private')) {
      return res.status(403).json({ 
        success: false, 
        error: 'Video is private or unavailable' 
      });
    }
    
    if (error.message.includes('Not found') || error.message.includes('not found')) {
      return res.status(404).json({ 
        success: false, 
        error: 'Video not found' 
      });
    }

    res.status(500).json({ 
      success: false, 
      error: error.message || 'Failed to fetch video metrics' 
    });
  }
});

// Extract video ID from URL (utility endpoint)
app.post('/api/video/extract-id', async (req, res) => {
  try {
    const { url } = req.body;
    
    if (!url) {
      return res.status(400).json({ 
        success: false, 
        error: 'URL is required' 
      });
    }

    // Try to extract video ID from various TikTok URL formats
    let videoId = null;
    
    // Format 1: https://www.tiktok.com/@username/video/1234567890
    const match1 = url.match(/tiktok\.com\/@[^/]+\/video\/(\d+)/);
    if (match1) videoId = match1[1];
    
    // Format 2: https://vm.tiktok.com/xxxxxx
    const match2 = url.match(/vm\.tiktok\.com\/([A-Za-z0-9]+)/);
    if (match2) videoId = match2[1];
    
    // Format 3: https://vt.tiktok.com/xxxxxx
    const match3 = url.match(/vt\.tiktok\.com\/([A-Za-z0-9]+)/);
    if (match3) videoId = match3[1];
    
    // Format 4: https://www.tiktok.com/t/xxxxxx
    const match4 = url.match(/tiktok\.com\/t\/([A-Za-z0-9]+)/);
    if (match4) videoId = match4[1];

    if (!videoId) {
      return res.status(400).json({ 
        success: false, 
        error: 'Could not extract video ID from URL' 
      });
    }

    res.json({ 
      success: true, 
      data: { video_id: videoId } 
    });

  } catch (error) {
    console.error('Error extracting video ID:', error.message);
    res.status(500).json({ 
      success: false, 
      error: 'Failed to extract video ID' 
    });
  }
});

app.listen(PORT, () => {
  console.log(`TikTok Scraper Service running on port ${PORT}`);
});

module.exports = app;