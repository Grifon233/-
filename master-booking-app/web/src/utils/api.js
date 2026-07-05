const API_URL = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '')
const DEMO_TG_ID = '999'

// Preserve Telegram auth query params for admin API.
function getAuthQuery() {
  const params = new URLSearchParams(window.location.search);
  if (isDemoEditingMode()) {
    const auth = new URLSearchParams();
    ['user', 'username', 'name', 'sig', 'demo'].forEach(key => {
      const value = params.get(key);
      if (value) auth.set(key, value);
    });
    return auth.toString();
  }
  // Public demo preview uses demo master ID for read-only requests.
  if (params.get('demo') === '1') {
    const auth = new URLSearchParams();
    auth.set('user', DEMO_TG_ID);
    // Don't copy sig — demo master bypasses signature check
    return auth.toString();
  }
  const auth = new URLSearchParams();
  ['user', 'user_id', 'username', 'name', 'sig', 'master_id', 'bot_id', 'auth_ts', 'vk_user', 'auth_source'].forEach(key => {
    const value = params.get(key);
    if (value) auth.set(key, value);
  });
  return auth.toString();
}

function isDemoMode() {
  return new URLSearchParams(window.location.search).get('demo') === '1';
}

function isDemoEditingMode() {
  return false;
}

async function parseApiResponse(response, fallbackMessage = 'API error') {
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(response.ok ? 'Некорректный ответ сервера' : `Ошибка сервера ${response.status}: ${text || response.statusText}`);
  }
  if (!response.ok || !data?.success) {
    const detail = data?.detail;
    const msg = Array.isArray(detail) ? detail[0]?.msg : detail;
    throw new Error(msg || data?.error?.message || fallbackMessage);
  }
  return data.data;
}

export async function api(endpoint, options = {}) {
  // Add auth query for admin endpoints (both /api/admin/ and /api/bookings/admin)
  if (endpoint.startsWith('/api/admin/') || endpoint === '/api/bookings/admin') {
    const authQuery = getAuthQuery();
    if (authQuery) {
      const separator = endpoint.includes('?') ? '&' : '?';
      endpoint = `${endpoint}${separator}${authQuery}`;
    }
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  return parseApiResponse(response);
}

export const getMaster = () => isDemoMode() && !isDemoEditingMode() ? api('/api/demo/master') : api('/api/admin/master');
export const getBookings = (params = {}) => {
  const query = new URLSearchParams(params).toString();
  if (isDemoMode()) return api('/api/demo/bookings/master');
  return api(`/api/admin/bookings${query ? '?' + query : ''}`);
};
export const getServices = () => isDemoMode() && !isDemoEditingMode() ? api('/api/demo/services') : api('/api/admin/services');
export const getMenuButtons = () => isDemoMode() && !isDemoEditingMode() ? api('/api/demo/menu-buttons') : api('/api/admin/menu-buttons');

export const updateMaster = (data) => api('/api/admin/master', { method: 'PUT', body: JSON.stringify(data) });
export const updateBooking = (id, data) => api(`/api/admin/bookings/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const createBooking = (data) => api('/api/bookings', { method: 'POST', body: JSON.stringify(data) });
export const createAdminBooking = (data) => api('/api/bookings/admin', { method: 'POST', body: JSON.stringify(data) });
export const createService = (data) => api('/api/admin/services', { method: 'POST', body: JSON.stringify(data) });
export const updateService = (id, data) => api(`/api/admin/services/${id}`, { method: 'PUT', body: JSON.stringify(data) });
export const deleteService = (id) => api(`/api/admin/services/${id}`, { method: 'DELETE' });
export const updateMenuButton = (type, data) => api(`/api/admin/menu-buttons/${type}`, { method: 'PUT', body: JSON.stringify(data) });

export async function uploadAvatar(file) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('file_type', 'avatar');

  const authQuery = getAuthQuery();
  const endpoint = authQuery ? `/api/admin/upload?${authQuery}` : '/api/admin/upload';

  const response = await fetch(`${API_URL}${endpoint}`, {
    method: 'POST',
    body: formData,
  });
  return parseApiResponse(response, 'Upload error');
}
