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
| active | BOOLEAN | Is product active |

A product is a **family** (one motif). It is not orderable itself — the
sellable units are its variants, which carry the SKU, the price and the stock.

### product_variants
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| product_id | INTEGER | Family this variant belongs to |
| sku | VARCHAR | Unique, e.g. `POSTER-SUNSET-A2` — what inventory stocks |
| size | VARCHAR | Format (A4, A3, A2, A1) |
| price | NUMERIC(10,2) | Price of this format |
| active | BOOLEAN | Is this variant sellable |

### frame_variants
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| frame_option_id | INTEGER | Colour this variant belongs to |
| sku | VARCHAR | Unique, e.g. `FRAME-BLACK-A2` |
| size | VARCHAR | Format the frame is made for |
| price | NUMERIC(10,2) | Price for that format |
| active | BOOLEAN | Is this variant sellable |

A frame is priced **per format**, not as a flat surcharge: an A1 frame needs
roughly twice the moulding of an A4. That interaction between two options is why
frames are variants rather than one `extra_price` on the colour.

### sizes
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | VARCHAR | Size name (A4, A3, A2, A1) |
| sort_order | INTEGER | Display order, smallest first |

### frame_options
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | VARCHAR | Frame colour name |
| sku_prefix | VARCHAR | SKU stem for its variants, e.g. `FRAME-BLACK` |

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
| GET | /frames | List frame colours; `?size=A2` prices them for that format | - |
| POST | /internal/resolve-prices | Authoritative price per SKU | Service/Admin |
| POST | /products/{sku}/variants | Add a format to a family (SKU derived) | Admin |
| PATCH | /variants/{sku} | Change a format's price, or take it off sale | Admin |
| DELETE | /variants/{sku} | Deactivate a format | Admin |
| POST | /sizes | Add a format to the vocabulary | Admin |
| PATCH | /sizes/{id} | Rename or reorder a format | Admin |
| DELETE | /sizes/{id} | Remove a format; refuses while in use unless `?force=true` | Admin |
| POST | /frames | Add a frame colour | Admin |
| PATCH | /frames/{id} | Rename a colour or change its SKU prefix | Admin |
| DELETE | /frames/{id} | Remove a colour; `?force=true` also removes its prices | Admin |
| POST | /frames/{id}/variants | Price a colour for one format | Admin |
| PATCH | /frame-variants/{sku} | Change that price, or take it off sale | Admin |
| DELETE | /frame-variants/{sku} | Deactivate one colour-and-format | Admin |
| POST | /seed | Seed sample data; `?force=true` rebuilds | Admin |

A variant may only use a format the `sizes` vocabulary defines. That check is
what keeps the catalogue and the warehouse from drifting apart again.

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
