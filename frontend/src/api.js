/**
 * API Client for PosterShop Microservices
 */

import { retryAfterText } from './lib/studio';

const API_BASE = '/api';

// The one Error every 429 becomes. The message leads with the server's own
// `detail` when the body has one (designs: "Daily limit of 10 generations
// reached"), else "Too many attempts" (slowapi on users login/register sends
// {"error": ...}, nothing worth showing); then the Retry-After header as a
// human wait — "… — try again in 6 h 7 min (at 02:00)." — or ", please wait a
// moment." when the header is missing or unparseable.
async function rateLimitError(response) {
  const retryAfter = response.headers.get('Retry-After');
  const body = await response.json().catch(() => ({}));
  const detail = typeof body?.detail === 'string' && body.detail.trim()
    ? body.detail.trim().replace(/\.$/, '')
    : 'Too many attempts';
  const wait = retryAfterText(retryAfter);
  return new Error(wait ? `${detail} — ${wait}.` : `${detail}, please wait a moment.`);
}

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (response.status === 429) {
    throw await rateLimitError(response);
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

let refreshPromise = null;

async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('shop_refresh_token');
  if (!refreshToken) {
    throw new Error('No refresh token');
  }

  const response = await fetch(`${API_BASE}/users/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    throw new Error('Refresh failed');
  }

  const data = await response.json();
  localStorage.setItem('shop_token', data.access_token);
  localStorage.setItem('shop_refresh_token', data.refresh_token);
  return data.access_token;
}

export async function authFetchJSON(url, options = {}) {
  const token = localStorage.getItem('shop_token');
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response = await fetch(url, { ...options, headers });

  // Handle rate limiting (D-12)
  if (response.status === 429) {
    throw await rateLimitError(response);
  }

  // Handle 401 with refresh (D-05, D-06)
  if (response.status === 401 && localStorage.getItem('shop_refresh_token')) {
    try {
      if (!refreshPromise) {
        refreshPromise = refreshAccessToken().finally(() => {
          refreshPromise = null;
        });
      }
      const newToken = await refreshPromise;
      headers['Authorization'] = `Bearer ${newToken}`;
      response = await fetch(url, { ...options, headers });
    } catch {
      // Refresh failed -- silent redirect to login (D-04)
      localStorage.removeItem('shop_token');
      localStorage.removeItem('shop_refresh_token');
      localStorage.removeItem('shop_user');
      window.location.href = '/login';
      throw new Error('Session expired');
    }
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  if (response.status === 204) return null;
  return response.json();
}

// ============== Catalog API ==============
export const catalogApi = {
  getProducts: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`${API_BASE}/catalog/products${query ? `?${query}` : ''}`);
  },
  getProduct: (sku) => fetchJSON(`${API_BASE}/catalog/products/${sku}`),
  createProduct: (data) => authFetchJSON(`${API_BASE}/catalog/products`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateProduct: (sku, data) => authFetchJSON(`${API_BASE}/catalog/products/${sku}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),
  deleteProduct: (sku) => authFetchJSON(`${API_BASE}/catalog/products/${sku}`, {
    method: 'DELETE',
  }),
  getCategories: () => fetchJSON(`${API_BASE}/catalog/categories`),
  getSizes: () => fetchJSON(`${API_BASE}/catalog/sizes`),
  // Pass a size and each colour comes back with that format's variant,
  // priced for it — an A1 frame is not an A4 frame with a surcharge.
  getFrames: (size) =>
    fetchJSON(`${API_BASE}/catalog/frames${size ? `?size=${encodeURIComponent(size)}` : ''}`),

  // --- owner-only: the sellable units and the option vocabulary -------------
  createVariant: (productSku, data) =>
    authFetchJSON(`${API_BASE}/catalog/products/${productSku}/variants`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateVariant: (sku, data) =>
    authFetchJSON(`${API_BASE}/catalog/variants/${sku}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteVariant: (sku) =>
    authFetchJSON(`${API_BASE}/catalog/variants/${sku}`, { method: 'DELETE' }),

  createSize: (data) =>
    authFetchJSON(`${API_BASE}/catalog/sizes`, { method: 'POST', body: JSON.stringify(data) }),
  updateSize: (id, data) =>
    authFetchJSON(`${API_BASE}/catalog/sizes/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSize: (id, force = false) =>
    authFetchJSON(`${API_BASE}/catalog/sizes/${id}${force ? '?force=true' : ''}`, {
      method: 'DELETE',
    }),

  createFrame: (data) =>
    authFetchJSON(`${API_BASE}/catalog/frames`, { method: 'POST', body: JSON.stringify(data) }),
  updateFrame: (id, data) =>
    authFetchJSON(`${API_BASE}/catalog/frames/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFrame: (id, force = false) =>
    authFetchJSON(`${API_BASE}/catalog/frames/${id}${force ? '?force=true' : ''}`, {
      method: 'DELETE',
    }),
  createFrameVariant: (frameId, data) =>
    authFetchJSON(`${API_BASE}/catalog/frames/${frameId}/variants`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateFrameVariant: (sku, data) =>
    authFetchJSON(`${API_BASE}/catalog/frame-variants/${sku}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteFrameVariant: (sku) =>
    authFetchJSON(`${API_BASE}/catalog/frame-variants/${sku}`, { method: 'DELETE' }),
  seed: () => authFetchJSON(`${API_BASE}/catalog/seed`, { method: 'POST' }),
};

// ============== Inventory API ==============
export const inventoryApi = {
  getStock: () => authFetchJSON(`${API_BASE}/inventory/stock`),
  getStockBySku: (sku) => authFetchJSON(`${API_BASE}/inventory/stock/${sku}`),
  createStock: (data) => authFetchJSON(`${API_BASE}/inventory/stock`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateStock: (sku, data) => authFetchJSON(`${API_BASE}/inventory/stock/${sku}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  restock: (sku, quantity) => authFetchJSON(`${API_BASE}/inventory/stock/${sku}/restock`, {
    method: 'POST',
    body: JSON.stringify({ quantity }),
  }),
  getReservations: () => fetchJSON(`${API_BASE}/inventory/reservations`),
  seed: () => authFetchJSON(`${API_BASE}/inventory/seed`, { method: 'POST' }),
};

// ============== Orders API ==============
export const ordersApi = {
  getOrders: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return authFetchJSON(`${API_BASE}/orders/orders${query ? `?${query}` : ''}`);
  },
  getOrder: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}`),
  createOrder: (data) => authFetchJSON(`${API_BASE}/orders/orders`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  payOrder: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/pay`, { method: 'POST' }),
  cancelOrder: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/cancel`, { method: 'POST' }),
  startProduction: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/produce`, { method: 'POST' }),
  shipOrder: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/ship`, { method: 'POST' }),
  deliverOrder: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/deliver`, { method: 'POST' }),
  getOrderStats: () => authFetchJSON(`${API_BASE}/orders/orders/stats/by-status`),
  getOutboxStats: () => authFetchJSON(`${API_BASE}/orders/outbox/stats`),
  createCheckout: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/checkout`, { method: 'POST' }),
  // Ether escrow (ESC-05). createEscrow is idempotent: it deploys the per-order
  // contract once and hands back the unsigned pay() invoice + chain config the
  // browser signs with ethers; verifyEscrow reads the chain and marks the order
  // PAID; confirmEscrowDelivery is the customer's authenticated release button.
  createEscrow: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/escrow`, { method: 'POST' }),
  getEscrow: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/escrow`),
  verifyEscrow: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/escrow/verify`, { method: 'POST' }),
  confirmEscrowDelivery: (id) => authFetchJSON(`${API_BASE}/orders/orders/${id}/escrow/confirm-delivery`, {
    method: 'POST',
  }),
};

// ============== Production API ==============
export const productionApi = {
  getJobs: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`${API_BASE}/production/jobs${query ? `?${query}` : ''}`);
  },
  getJob: (id) => fetchJSON(`${API_BASE}/production/jobs/${id}`),
  getJobByOrder: (orderId) => fetchJSON(`${API_BASE}/production/jobs/order/${orderId}`),
  // authFetchJSON, not fetchJSON: POST /jobs/{id}/retry now requires a service
  // or owner token. The admin dashboard is the only UI caller and runs as owner.
  retryJob: (id) => authFetchJSON(`${API_BASE}/production/jobs/${id}/retry`, { method: 'POST' }),
  getJobStats: () => fetchJSON(`${API_BASE}/production/jobs/stats/summary`),
};

// ============== Logistics API ==============
export const logisticsApi = {
  // authFetchJSON, not fetchJSON: the three shipment reads now require a courier
  // or owner token, because they return the customer's delivery address.
  // updateShipmentStatus was ALREADY 401-ing before this change — PUT
  // /shipments/{id}/status has required that role since before 260912-n7c, and
  // this module was calling it without a token, so the admin dashboard's advance
  // button was dead. Switching it here is a repair, not just a follow-on.
  getShipments: () => authFetchJSON(`${API_BASE}/logistics/shipments`),
  getShipment: (id) => authFetchJSON(`${API_BASE}/logistics/shipments/${id}`),
  // courierWallet is optional: the courier dashboard sends it on pick-up
  // (in_transit) so orders can bind the courier on an escrow contract; the
  // existing two-argument callers keep sending the bare {status} body.
  updateShipmentStatus: (id, status, courierWallet) => authFetchJSON(`${API_BASE}/logistics/shipments/${id}/status`, {
    method: 'PUT',
    body: JSON.stringify(courierWallet ? { status, courier_wallet: courierWallet } : { status }),
  }),
};

// ============== Payments API ==============
export const paymentsApi = {
  getSessions: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`${API_BASE}/payments/v1/checkout/sessions${query ? `?${query}` : ''}`);
  },
  getSession: (id) => fetchJSON(`${API_BASE}/payments/v1/checkout/sessions/${id}`),
  completeSession: (id) => fetchJSON(`${API_BASE}/payments/v1/checkout/sessions/${id}/complete`, {
    method: 'POST',
  }),
  // Public reads (no token): whether escrow is on and which chain to sign for,
  // plus Ganache's deterministic demo accounts (404 when not exposed).
  getEscrowConfig: () => fetchJSON(`${API_BASE}/payments/v1/escrow/config`),
  getEscrowDemoAccounts: () => fetchJSON(`${API_BASE}/payments/v1/escrow/demo-accounts`),
};

// ============== Designs API (AI poster studio) ==============
// Every call carries the customer bearer; the service scopes rows by the JWT subject.
// Images are NOT fetched here: <img src={image_url}> loads /api/designs/images/<key>.png
// directly (public, immutable).
export const designsApi = {
  createGeneration: ({ prompt, personalise = false }) =>
    authFetchJSON(`${API_BASE}/designs/generations`, {
      method: 'POST',
      body: JSON.stringify({ prompt, personalise }),
    }),
  getGeneration: (id) => authFetchJSON(`${API_BASE}/designs/generations/${id}`),
  listGenerations: (limit = 50) => authFetchJSON(`${API_BASE}/designs/generations?limit=${limit}`),
  // Owner only: every customer's generations, newest first (admin /designs page).
  // params: { limit?, customer?, status? } — pass only the filters that are set.
  adminGenerations: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return authFetchJSON(`${API_BASE}/designs/admin/generations${query ? `?${query}` : ''}`);
  },
  printGeneration: (id) =>
    authFetchJSON(`${API_BASE}/designs/generations/${id}/print`, { method: 'POST' }),
  listSavedPrompts: () => authFetchJSON(`${API_BASE}/designs/saved-prompts`),
  createSavedPrompt: ({ title, prompt }) =>
    authFetchJSON(`${API_BASE}/designs/saved-prompts`, {
      method: 'POST',
      body: JSON.stringify({ title, prompt }),
    }),
  // DELETE answers 204 with no body; fetchJSON/authFetchJSON return null for 204.
  deleteSavedPrompt: (id) =>
    authFetchJSON(`${API_BASE}/designs/saved-prompts/${id}`, { method: 'DELETE' }),
  getQuota: () => authFetchJSON(`${API_BASE}/designs/me/quota`),
  getStyleProfile: () => authFetchJSON(`${API_BASE}/designs/me/style-profile`),
  refreshStyleProfile: () =>
    authFetchJSON(`${API_BASE}/designs/me/style-profile/refresh`, { method: 'POST' }),
};

// ============== Infrastructure API ==============
export const infraApi = {
  getCluster: () => authFetchJSON(`${API_BASE}/infra/cluster`),
  getDeployments: () => authFetchJSON(`${API_BASE}/infra/deployments`),
  getDeployment: (name) => authFetchJSON(`${API_BASE}/infra/deployments/${name}`),
  scaleDeployment: (name, replicas) => authFetchJSON(`${API_BASE}/infra/deployments/${name}/scale`, {
    method: 'POST',
    body: JSON.stringify({ replicas }),
  }),
  restartDeployment: (name) => authFetchJSON(`${API_BASE}/infra/deployments/${name}/restart`, {
    method: 'POST',
  }),
  getPods: (deployment) => {
    const params = deployment ? `?deployment=${deployment}` : '';
    return authFetchJSON(`${API_BASE}/infra/pods${params}`);
  },
  deletePod: (name) => fetch(`${API_BASE}/infra/pods/${name}`, { method: 'DELETE' }),
  getPodLogs: (name, tail = 100) => authFetchJSON(`${API_BASE}/infra/pods/${name}/logs?tail=${tail}`),
  getHPAs: () => authFetchJSON(`${API_BASE}/infra/hpa`),
  updateHPA: (name, data) => authFetchJSON(`${API_BASE}/infra/hpa/${name}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),
  queryLogs: (service, correlationId, range) => {
    const params = new URLSearchParams({ service, range: range || '1h' });
    if (correlationId && correlationId.trim()) {
      params.set('correlation_id', correlationId.trim());
    }
    return authFetchJSON(`${API_BASE}/infra/logs/query?${params}`);
  },
};

// ============== Users API ==============
export const usersApi = {
  // Auth (unauthenticated -- use fetchJSON)
  login: (email, password) => fetchJSON(`${API_BASE}/users/login`, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }),
  register: async (data) => {
    const response = await fetch(`${API_BASE}/users/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      if (response.status === 429) {
        throw await rateLimitError(response);
      }
      const error = await response.json().catch(() => ({ detail: 'Registration failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();  // Returns { access_token, refresh_token, token_type }
  },

  // Authenticated endpoints -- use authFetchJSON (no manual token param)
  getMe: () => authFetchJSON(`${API_BASE}/users/users/me`),
  // Courier payout wallet (ESC-04); 422 on anything but 0x + 40 hex.
  setWallet: (wallet_address) => authFetchJSON(`${API_BASE}/users/users/me/wallet`, {
    method: 'PUT',
    body: JSON.stringify({ wallet_address }),
  }),

  // Logout endpoints
  logout: (refreshToken) => authFetchJSON(`${API_BASE}/users/auth/logout`, {
    method: 'POST',
    body: JSON.stringify({ refresh_token: refreshToken }),
  }),
  logoutAll: () => authFetchJSON(`${API_BASE}/users/auth/logout-all`, {
    method: 'POST',
  }),

  // Admin endpoints -- use authFetchJSON (no manual token param)
  getUsers: () => authFetchJSON(`${API_BASE}/users/admin/users`),
  createUser: (data) => authFetchJSON(`${API_BASE}/users/admin/users`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  deleteUser: (id) => fetch(`${API_BASE}/users/admin/users/${id}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${localStorage.getItem('shop_token')}` },
  }).then(r => { if (!r.ok) throw new Error('Failed to delete'); return r; }),
  changeUserRole: (id, newRole) => authFetchJSON(`${API_BASE}/users/users/${id}/role`, {
    method: 'PUT',
    body: JSON.stringify({ new_role: newRole }),
  }),
};

// ============== Health Checks ==============
export const healthApi = {
  checkAll: async () => {
    const services = [
      { name: 'Users', url: `${API_BASE}/users/healthz` },
      { name: 'Catalog', url: `${API_BASE}/catalog/healthz` },
      { name: 'Orders', url: `${API_BASE}/orders/healthz` },
      { name: 'Production', url: `${API_BASE}/production/healthz` },
      { name: 'Logistics', url: `${API_BASE}/logistics/healthz` },
      { name: 'Inventory', url: `${API_BASE}/inventory/healthz` },
      { name: 'Payments', url: `${API_BASE}/payments/healthz` },
      { name: 'Designs', url: `${API_BASE}/designs/healthz` },
    ];
    
    const results = await Promise.all(
      services.map(async (service) => {
        try {
          const start = Date.now();
          await fetchJSON(service.url);
          return { ...service, status: 'healthy', latency: Date.now() - start };
        } catch (e) {
          return { ...service, status: 'unhealthy', error: e.message };
        }
      })
    );
    
    return results;
  },
};

