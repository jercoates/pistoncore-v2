// pistoncore/frontend/js/api.js
//
// All backend API calls go through this module.
// The frontend never calls HA directly — always through the backend.
//
// Usage:
//   const pistons = await API.getPistons();
//   const result  = await API.savePiston(id, pistonJson);
//
// All methods return the parsed response body on success.
// On error they throw an APIError with a human-readable message.

const API_BASE = window.location.origin; // same host, port 7777

class APIError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'APIError';
    this.status = status;
  }
}

async function _fetch(path, options = {}) {
  const url = `${API_BASE}${path}`;
  const headers = { 'Content-Type': 'application/json', ...options.headers };

  // Include API key if configured (set by setup page)
  const apiKey = sessionStorage.getItem('pistoncore_api_key');
  if (apiKey) headers['X-API-Key'] = apiKey;

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (e) {
    throw new APIError('Could not reach the PistonCore backend. Is it running?', 0);
  }

  if (response.status === 204) return null; // No Content (DELETE)

  let body;
  try {
    body = await response.json();
  } catch {
    throw new APIError(`Server returned an unexpected response (${response.status}).`, response.status);
  }

  if (!response.ok) {
    const detail = body?.detail || `Request failed (${response.status}).`;
    throw new APIError(detail, response.status);
  }

  return body;
}

const API = {

  // ── Health ──────────────────────────────────────────────
  async health() {
    return _fetch('/health');
  },

  // ── Pistons ─────────────────────────────────────────────
  async getPistons() {
    return _fetch('/pistons');
  },

  async getPiston(id) {
    return _fetch(`/pistons/${id}`);
  },

  async createPiston(piston) {
    return _fetch('/pistons', {
      method: 'POST',
      body: JSON.stringify(piston),
    });
  },

  async savePiston(id, piston) {
    // PUT /pistons/{id} — saves JSON to Docker volume, runs Stage 1 validation
    return _fetch(`/pistons/${id}`, {
      method: 'PUT',
      body: JSON.stringify(piston),
    });
  },

  async deletePiston(id) {
    return _fetch(`/pistons/${id}`, { method: 'DELETE' });
  },

  async importPiston(piston) {
    // POST /pistons/import — saves Snapshot JSON, returns saved piston with new ID.
    // device_map may be empty (Snapshot) or populated (Backup).
    // Frontend handles role mapping after this call.
    return _fetch('/pistons/import', {
      method: 'POST',
      body: JSON.stringify(piston),
    });
  },

  async compilePiston(id) {
    // Returns YAML strings without writing to HA
    return _fetch(`/pistons/${id}/compile`, { method: 'POST' });
  },

  async deployPiston(id) {
    // Compiles + sends to companion for HA file write
    return _fetch(`/pistons/${id}/deploy`, { method: 'POST' });
  },

  // ── Globals ─────────────────────────────────────────────
  async getGlobals() {
    return _fetch('/globals');
  },

  async createGlobal(fields) {
    // fields: { name, var_type, value, description }
    // For device type: value is an array of entity ID strings.
    // For all other types: value is a plain string.
    return _fetch('/globals', {
      method: 'POST',
      body: JSON.stringify(fields),
    });
  },

  async updateGlobal(id, fields) {
    // PUT /globals/{id} — partial update, missing fields are preserved by backend.
    // fields: { name, var_type, value, description }
    // For device type: value is an array of entity ID strings.
    return _fetch(`/globals/${id}`, {
      method: 'PUT',
      body: JSON.stringify(fields),
    });
  },

  async deleteGlobal(id) {
    return _fetch(`/globals/${id}`, { method: 'DELETE' });
  },

  // ── Config ──────────────────────────────────────────────
  async getConfig() {
    return _fetch('/config');
  },

  async saveConfig(config) {
    return _fetch('/config', {
      method: 'PUT',
      body: JSON.stringify(config),
    });
  },

  // ── HA Devices (wizard) ──────────────────────────────────
  async getDevices() {
    return _fetch('/devices');
  },

  async refreshDevices() {
    return _fetch('/devices/refresh');
  },

  async getCapabilities(entityId) {
    return _fetch(`/device/${encodeURIComponent(entityId)}/capabilities`);
  },

  async getServices(entityId) {
    return _fetch(`/device/${encodeURIComponent(entityId)}/services`);
  },
};

// Make APIError available globally for instanceof checks
window.APIError = APIError;
window.API = API;
