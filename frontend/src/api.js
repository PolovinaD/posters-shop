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

// ============== Users API ==============
export const usersApi = {
  // Auth
  login: (email, password) => fetchJSON(`${API_BASE}/users/login`, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  }),
  register: (data) => fetchJSON(`${API_BASE}/users/register`, {
    method: 'POST',
    body: JSON.stringify(data),
  }),
  getMe: (token) => fetchJSON(`${API_BASE}/users/users/me`, {
    headers: { Authorization: `Bearer ${token}` },
  }),
  
  // Admin endpoints (require owner token)
  getUsers: (token) => fetchJSON(`${API_BASE}/users/admin/users`, {
    headers: { Authorization: `Bearer ${token}` },
  }),
  createUser: (token, data) => fetchJSON(`${API_BASE}/users/admin/users`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(data),
  }),
  deleteUser: (token, id) => fetch(`${API_BASE}/users/admin/users/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  }).then(r => { if (!r.ok) throw new Error('Failed to delete'); return r; }),
  changeUserRole: (token, id, newRole) => fetchJSON(`${API_BASE}/users/users/${id}/role`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}` },
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

