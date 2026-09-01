// Shared API Client — unified fetch wrapper with auth/error handling
const API_BASE = window.location.origin;
const TOKEN_KEY = 'dou_token_v2';
const ROLE_KEY = 'dou_role_v2';

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export const api = {
  getToken: () => localStorage.getItem(TOKEN_KEY) || null,
  setToken: (t) => localStorage.setItem(TOKEN_KEY, t),
  clearToken: () => { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(ROLE_KEY); },
  getRole: () => localStorage.getItem(ROLE_KEY) || null,
  setRole: (r) => localStorage.setItem(ROLE_KEY, r),

  request(method, path, body = null) {
    const headers = { 'Content-Type': 'application/json' };
    const token = this.getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const opts = { method, headers };
    if (body) opts.body = typeof body === 'string' ? body : JSON.stringify(body);
    return fetch(`${API_BASE}${path}`, opts).then(async (res) => {
      if (res.status === 401) {
        this.clearToken();
        window.dispatchEvent(new CustomEvent('auth:expired'));
        throw new ApiError('Session expired — please log in again.', 401, null);
      }
      const text = await res.text();
      let data = null;
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
      if (!res.ok) {
        const msg = (data && (data.message || data.detail)) || `HTTP ${res.status}`;
        throw new ApiError(msg, res.status, data);
      }
      return data;
    });
  },

  get: (path) => api.request('GET', path),
  post: (path, body) => api.request('POST', path, body),
  patch: (path, body) => api.request('PATCH', path, body),
  put: (path, body) => api.request('PUT', path, body),
  del: (path) => api.request('DELETE', path),
  delete: (path) => api.request('DELETE', path),

  async login(phone, password) {
    const data = await api.post('/auth/login', { phone, password });
    if (data.access_token) { api.setToken(data.access_token); api.setRole(data.role); }
    return data;
  },
  logout() {
    const token = this.getToken();
    if (token) fetch(`${API_BASE}/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    api.clearToken();
  },
  async me() { return api.get('/fleet/me'); },
};
