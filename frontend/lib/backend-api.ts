const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface BackendItem {
  item_id: string;
  url: string;
  type?: string;
  title: string;
  artist: string;
  album: string;
  cover_url: string;
  quality_str: string;
  percent: number;
  downloaded_bytes?: number;
  total_bytes?: number;
  speed_str: string;
  eta_str: string;
  stage?: string;
  status: 'queued' | 'fetching' | 'downloading' | 'processing' | 'completed' | 'failed';
  status_label: string;
  error_message?: string;
}

export interface BackendQueueState {
  active: BackendItem[];
  completed: BackendItem[];
  failed: BackendItem[];
  is_paused: boolean;
}

export const backendApi = {
  getBaseUrl() {
    return BACKEND_URL;
  },

  async addToQueue(urls: string[], qualityOverride?: number): Promise<{ success: boolean; added: any[] }> {
    const res = await fetch(`${BACKEND_URL}/api/queue/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls, quality_override: qualityOverride }),
    });
    return res.json();
  },

  async getQueue(): Promise<BackendQueueState> {
    const res = await fetch(`${BACKEND_URL}/api/queue`);
    return res.json();
  },

  async pauseQueue() {
    return fetch(`${BACKEND_URL}/api/queue/pause`, { method: 'POST' });
  },

  async resumeQueue() {
    return fetch(`${BACKEND_URL}/api/queue/resume`, { method: 'POST' });
  },

  async clearCompleted() {
    return fetch(`${BACKEND_URL}/api/queue/clear`, { method: 'POST' });
  },

  async cancelTask(taskId: string) {
    return fetch(`${BACKEND_URL}/api/queue/cancel/${taskId}`, { method: 'POST' });
  },

  async searchCatalog(query: string, limit = 15) {
    const res = await fetch(`${BACKEND_URL}/api/search?q=${encodeURIComponent(query)}&limit=${limit}`);
    return res.json();
  },

  async getReleases(limit = 24) {
    const res = await fetch(`${BACKEND_URL}/api/get-releases?limit=${limit}`);
    return res.json();
  },

  async getAlbum(albumId: string) {
    const res = await fetch(`${BACKEND_URL}/api/get-album?id=${encodeURIComponent(albumId)}`);
    return res.json();
  },

  async getArtist(artistId: string) {
    const res = await fetch(`${BACKEND_URL}/api/get-artist?id=${encodeURIComponent(artistId)}`);
    return res.json();
  },

  async getCountries() {
    const res = await fetch(`${BACKEND_URL}/api/get-countries`);
    return res.json();
  },

  async getConfig() {
    const res = await fetch(`${BACKEND_URL}/api/config`);
    return res.json();
  },

  async updateConfig(config: any) {
    const res = await fetch(`${BACKEND_URL}/api/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    return res.json();
  },

  async getAuthStatus() {
    const res = await fetch(`${BACKEND_URL}/api/auth/me`);
    return res.json();
  },

  connectWebSocket(onMessage: (data: any) => void): WebSocket | null {
    if (typeof window === 'undefined') return null;
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = BACKEND_URL.replace(/^https?:\/\//, '');
    try {
      const ws = new WebSocket(`${wsProtocol}//${host}/ws/live`);
      ws.onmessage = (e) => {
        try {
          const payload = JSON.parse(e.data);
          onMessage(payload);
        } catch (err) {
          console.warn('WebSocket parse error', err);
        }
      };
      return ws;
    } catch (e) {
      console.warn('WebSocket connection failed, falling back to polling', e);
      return null;
    }
  }
};
