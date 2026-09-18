// One load step: constant VUs for DURATION against one path (read | write).
// Env: BASE, PATH_KIND, VUS, DURATION, TOKEN (write only), SKU (write only)
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE;
const KIND = __ENV.PATH_KIND || 'read';
const SKU = __ENV.SKU || 'POSTER-SUNSET-A3';

export const options = {
  scenarios: {
    step: { executor: 'constant-vus', vus: Number(__ENV.VUS || 10), duration: __ENV.DURATION || '90s' },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  thresholds: { http_req_failed: ['rate<0.5'] },
};

const addr = {
  recipient_name: 'Load Test', street: 'Bulevar kralja Aleksandra 73', city: 'Beograd',
  postal_code: '11000', country: 'Serbia', phone: '+381601234567',
};

export default function () {
  if (KIND === 'read') {
    const r = http.get(`${BASE}/api/catalog/products`, { tags: { name: 'GET /api/catalog/products' } });
    check(r, { 'read 200': (x) => x.status === 200 });
  } else {
    const body = JSON.stringify({
      customer_email: __ENV.EMAIL || 'admin@postershop.com',
      shipping_address: addr,
      items: [{ sku: SKU, quantity: 1 }],
      payment_method: 'stripe',
    });
    const r = http.post(`${BASE}/api/orders/orders`, body, {
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${__ENV.TOKEN}` },
      tags: { name: 'POST /api/orders/orders' },
    });
    check(r, { 'order 201': (x) => x.status === 201 });
  }
  sleep(0.2);
}
