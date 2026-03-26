# Catalog Service

Product catalog management for the poster shop.

## Purpose

- Manage product catalog (CRUD)
- Provide product information to frontend
- Integration with inventory for stock levels
- Manage sizes and frame options

## Tech Stack

- FastAPI
- SQLAlchemy + PostgreSQL
- httpx (for inventory integration)

## Database Schema

**Schema:** `catalog_schema`

### products
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| sku | VARCHAR | Unique stock keeping unit |
| name | VARCHAR | Product name |
| description | TEXT | Product description |
| price | NUMERIC(10,2) | Base price |
| category | VARCHAR | Category name |
| image_url | VARCHAR | Product image URL |
| sizes | VARCHAR | Available sizes (comma-separated) |
| active | BOOLEAN | Is product active |

### sizes
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | VARCHAR | Size name (A4, A3, A2, A1) |
| price_delta | NUMERIC(10,2) | Price adjustment |

### frame_options
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | VARCHAR | Frame name |
| extra_price | NUMERIC(10,2) | Additional price |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | /products | List products | - |
| GET | /products/{sku} | Get product by SKU | - |
| POST | /products | Create product | Admin |
| PATCH | /products/{sku} | Update product | Admin |
| DELETE | /products/{sku} | Deactivate product | Admin |
| GET | /categories | List categories | - |
| GET | /sizes | List sizes | - |
| GET | /frames | List frame options | - |
| POST | /seed | Seed sample data | Admin |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| INVENTORY_SERVICE_URL | Inventory service URL | `http://inventory:8000` |

## Local Development

```bash
cd services/catalog
pip install -r requirements.txt
export DATABASE_URL="postgresql://localhost/postershop"
alembic upgrade head
uvicorn main:app --reload --port 8002
```

## Inventory Integration

When listing products with `include_stock=true` (default), the service fetches stock levels from the inventory service to include `available` and `in_stock` fields.

## Sample Data

Run `POST /seed` to populate with sample posters:
- Golden Sunset (Nature)
- Mountain Majesty (Nature)
- City Lights (Urban)
- Enchanted Forest (Nature)
- Deep Blue (Nature)
- Color Flow (Abstract)
- Serene Minimalism (Minimal)
- Botanical Garden (Nature)

## Events

None - this service doesn't produce or consume events.

## Dependencies

- **Inventory Service** (optional): For stock level display
