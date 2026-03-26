# PosterShop Frontend

React SPA providing both the customer-facing shop and admin panel.

## Tech Stack

- **React 19** - UI framework
- **Vite** - Build tool
- **TailwindCSS** - Styling
- **React Query** - Data fetching & caching
- **React Router** - Routing
- **Lucide React** - Icons

## Routes

### Shop (Light Theme)
| Route | Description |
|-------|-------------|
| `/shop` | Product catalog |
| `/shop/product/:sku` | Product detail |
| `/shop/checkout` | Cart checkout |
| `/shop/orders` | Order tracking (guest) |
| `/shop/orders/:id` | Order detail |
| `/shop/login` | User login |
| `/shop/register` | User registration |
| `/shop/my-orders` | User order history |

### Admin Panel (Dark Theme)
| Route | Description |
|-------|-------------|
| `/` | Dashboard |
| `/catalog` | Product management |
| `/inventory` | Stock management |
| `/orders` | Order management |
| `/production` | Print job management |
| `/logistics` | Shipment tracking |
| `/outbox` | Event outbox monitoring |
| `/users` | User management |
| `/infrastructure` | K8s cluster dashboard |

## Development

```bash
# Install dependencies
npm install

# Start dev server (port 5173)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

## API Integration

All API calls go through `/api/<service>/...` which nginx proxies to backend services.

Configuration in `src/api.js`:
```javascript
const API_BASE = '/api';

// Example: catalog products
fetchJSON(`${API_BASE}/catalog/products`)
```

## Docker Build

```bash
# Development (local)
docker build -t frontend .

# Production (for EKS - amd64)
docker build --platform linux/amd64 -t frontend .
```

## Environment

The frontend is served by nginx with proxy configuration for API routing. No environment variables needed at build time - API routing is handled by nginx.
