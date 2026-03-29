/**
 * API Client for PosterShop Microservices
 */

const API_BASE = '/api';

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After');
    throw new Error(retryAfter ? `Too many attempts, please wait ${retryAfter} seconds.` : 'Too many attempts, please wait.');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

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
    const retryAfter = response.headers.get('Retry-After');
    const waitMsg = retryAfter ? `Too many attempts, please wait ${retryAfter} seconds.` : 'Too many attempts, please wait.';
    throw new Error(waitMsg);
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

  return response.json();
}

// ============== Catalog API ==============
export const catalogApi = {
  getProducts: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`${API_BASE}/catalog/products${query ? `?${query}` : ''}`);
  },
  getProduct: (sku) => fetchJSON(`${API_BASE}/catalog/products/${sku}`),
  createProduct: (data) => fetchJSON(`${API_BASE}/catalog/products`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateProduct: (sku, data) => fetchJSON(`${API_BASE}/catalog/products/${sku}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),
  deleteProduct: (sku) => fetch(`${API_BASE}/catalog/products/${sku}`, {
    method: 'DELETE',
  }).then(r => { if (!r.ok) throw new Error('Failed to delete'); return r; }),
  getCategories: () => fetchJSON(`${API_BASE}/catalog/categories`),
  getSizes: () => fetchJSON(`${API_BASE}/catalog/sizes`),
  getFrames: () => fetchJSON(`${API_BASE}/catalog/frames`),
  seed: () => fetchJSON(`${API_BASE}/catalog/seed`, { method: 'POST' }),
};

// ============== Inventory API ==============
export const inventoryApi = {
  getStock: () => fetchJSON(`${API_BASE}/inventory/stock`),
  getStockBySku: (sku) => fetchJSON(`${API_BASE}/inventory/stock/${sku}`),
  createStock: (data) => fetchJSON(`${API_BASE}/inventory/stock`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  updateStock: (sku, data) => fetchJSON(`${API_BASE}/inventory/stock/${sku}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),
  restock: (sku, quantity) => fetchJSON(`${API_BASE}/inventory/stock/${sku}/restock`, {
    method: 'POST',
    body: JSON.stringify({ quantity }),
  }),
  getReservations: () => fetchJSON(`${API_BASE}/inventory/reservations`),
  seed: () => fetchJSON(`${API_BASE}/inventory/seed`, { method: 'POST' }),
};

// ============== Orders API ==============
export const ordersApi = {
  getOrders: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`${API_BASE}/orders/orders${query ? `?${query}` : ''}`);
  },
  getOrder: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}`),
  createOrder: (data) => fetchJSON(`${API_BASE}/orders/orders`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  payOrder: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}/pay`, { method: 'POST' }),
  cancelOrder: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}/cancel`, { method: 'POST' }),
  startProduction: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}/produce`, { method: 'POST' }),
  shipOrder: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}/ship`, { method: 'POST' }),
  deliverOrder: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}/deliver`, { method: 'POST' }),
  getOrderStats: () => fetchJSON(`${API_BASE}/orders/orders/stats/by-status`),
  getOutboxStats: () => fetchJSON(`${API_BASE}/orders/outbox/stats`),
  createCheckout: (id) => fetchJSON(`${API_BASE}/orders/orders/${id}/checkout`, { method: 'POST' }),
};

// ============== Production API ==============
export const productionApi = {
  getJobs: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchJSON(`${API_BASE}/production/jobs${query ? `?${query}` : ''}`);
  },
  getJob: (id) => fetchJSON(`${API_BASE}/production/jobs/${id}`),
  getJobByOrder: (orderId) => fetchJSON(`${API_BASE}/production/jobs/order/${orderId}`),
  retryJob: (id) => fetchJSON(`${API_BASE}/production/jobs/${id}/retry`, { method: 'POST' }),
  getJobStats: () => fetchJSON(`${API_BASE}/production/jobs/stats/summary`),
};

// ============== Logistics API ==============
export const logisticsApi = {
  getShipments: () => fetchJSON(`${API_BASE}/logistics/shipments`),
  getShipment: (id) => fetchJSON(`${API_BASE}/logistics/shipments/${id}`),
  updateShipmentStatus: (id, status) => fetchJSON(`${API_BASE}/logistics/shipments/${id}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
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
};

// ============== Infrastructure API ==============
export const infraApi = {
  getCluster: () => fetchJSON(`${API_BASE}/infra/cluster`),
  getDeployments: () => fetchJSON(`${API_BASE}/infra/deployments`),
  getDeployment: (name) => fetchJSON(`${API_BASE}/infra/deployments/${name}`),
  scaleDeployment: (name, replicas) => fetchJSON(`${API_BASE}/infra/deployments/${name}/scale`, {
    method: 'POST',
    body: JSON.stringify({ replicas }),
  }),
  restartDeployment: (name) => fetchJSON(`${API_BASE}/infra/deployments/${name}/restart`, {
    method: 'POST',
  }),
  getPods: (deployment) => {
    const params = deployment ? `?deployment=${deployment}` : '';
    return fetchJSON(`${API_BASE}/infra/pods${params}`);
  },
  deletePod: (name) => fetch(`${API_BASE}/infra/pods/${name}`, { method: 'DELETE' }),
  getPodLogs: (name, tail = 100) => fetchJSON(`${API_BASE}/infra/pods/${name}/logs?tail=${tail}`),
  getHPAs: () => fetchJSON(`${API_BASE}/infra/hpa`),
  updateHPA: (name, data) => fetchJSON(`${API_BASE}/infra/hpa/${name}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  }),
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
        const retryAfter = response.headers.get('Retry-After');
        throw new Error(retryAfter ? `Too many attempts, please wait ${retryAfter} seconds.` : 'Too many attempts, please wait.');
      }
      const error = await response.json().catch(() => ({ detail: 'Registration failed' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();  // Returns { access_token, refresh_token, token_type }
  },

  // Authenticated endpoints -- use authFetchJSON (no manual token param)
  getMe: () => authFetchJSON(`${API_BASE}/users/users/me`),

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

