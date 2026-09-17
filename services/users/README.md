# Users Service

Authentication and user management service.

## Purpose

- User registration and login
- JWT token generation and validation
- Role-based access control (customer, owner, courier)
- Admin user management

## Tech Stack

- FastAPI
- SQLAlchemy + PostgreSQL
- python-jose (JWT)
- passlib + bcrypt (password hashing)

## Database Schema

**Schema:** `users_schema`

### users
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| email | VARCHAR | Unique login identifier |
| password_hash | VARCHAR | Bcrypt hash |
| role | VARCHAR | customer, owner, courier |
| first_name | VARCHAR | Optional |
| last_name | VARCHAR | Optional |
| wallet_address | VARCHAR(42) | Optional Ethereum wallet (`0x` + 40 hex); couriers set it and are paid to it (`003_wallet_address.py`) |

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /register | Register new user | - |
| POST | /login | Login, get JWT token | - |
| GET | /users/me | Get current user info | JWT |
| POST | /users/me/password | Change password | JWT |
| PUT | /users/me/wallet | Set the caller's Ethereum wallet (`{wallet_address}`, 422 unless `0x` + 40 hex) | JWT |
| GET | /admin/users | List all users | Owner |
| POST | /admin/users | Create user with role | Owner |
| PUT | /users/{id}/role | Change user role | Owner |
| DELETE | /admin/users/{id} | Delete user | Owner |
| POST | /admin/users/{id}/reset-password | Reset password | Owner |

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | PostgreSQL connection | Required |
| JWT_SECRET | Token signing key | `change_me` |
| JWT_EXPIRE_MINUTES | Token TTL | `60` |

## Local Development

```bash
cd services/users
pip install -r requirements.txt
export DATABASE_URL="postgresql://localhost/postershop"
alembic upgrade head
uvicorn main:app --reload --port 8001
```

## JWT Token Format

```json
{
  "sub": "user@example.com",
  "role": "customer",
  "exp": 1705320000
}
```

## Roles

- **customer**: Default role, can place orders and view own orders
- **owner**: Admin role, full access to all services
- **courier**: Can update shipment status; sets a `wallet_address` to receive the escrow
  courier share (`make dev-seed` sets `courier@postershop.com`'s wallet to Ganache demo
  account 3)

## Events

None - this service doesn't produce or consume events.

## Dependencies

- None (standalone auth service)
