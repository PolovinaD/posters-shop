# Architecture Documentation

## System Overview

The shop-platform is a microservices-based e-commerce system for selling custom posters. It demonstrates event-driven architecture patterns including the transactional outbox pattern for reliable messaging.

---

## Service Dependency Diagram

```mermaid
graph TB
    subgraph "Frontend"
        FE[Frontend<br/>React + Vite]
    end
    
    subgraph "API Gateway"
        ALB[AWS ALB<br/>Path-based routing]
    end
    
    subgraph "Core Services"
        USERS[Users Service<br/>Auth, JWT]
        CATALOG[Catalog Service<br/>Products]
        ORDERS[Orders Service<br/>Order lifecycle]
        INVENTORY[Inventory Service<br/>Stock management]
    end
    
    subgraph "Processing Services"
        PRODUCTION[Production Service<br/>Job processing]
        LOGISTICS[Logistics Service<br/>Shipping]
        PAYMENTS[Payments Service<br/>Stripe mock]
        NOTIFICATIONS[Notifications Service<br/>Transactional email<br/>stateless, no DB]
    end
    
    subgraph "Infrastructure"
        INFRA[Infra Service<br/>K8s management]
    end
    
    subgraph "Data Layer"
        PG[(PostgreSQL<br/>Schema per service)]
    end
    
    FE --> ALB
    ALB --> USERS
    ALB --> CATALOG
    ALB --> ORDERS
    ALB --> INVENTORY
    ALB --> PRODUCTION
    ALB --> LOGISTICS
    ALB --> PAYMENTS
    ALB --> INFRA
    
    ORDERS -->|sync| INVENTORY
    ORDERS -->|sync| PAYMENTS
    ORDERS -.->|outbox| PRODUCTION
    ORDERS -.->|outbox| NOTIFICATIONS
    NOTIFICATIONS -->|SES via IRSA| SES[AWS SES]
    PRODUCTION -->|sync| ORDERS
    PRODUCTION -->|sync| LOGISTICS
    LOGISTICS -->|sync| ORDERS
    CATALOG -->|sync| INVENTORY
    
    USERS --> PG
    CATALOG --> PG
    ORDERS --> PG
    INVENTORY --> PG
    PRODUCTION --> PG
    LOGISTICS --> PG
```

**Notifications has no edge to PostgreSQL.** It is stateless by design: no schema, no
Alembic migrations, no `models.py`. Its only persistent-looking state is an in-memory
set of processed `event_id` values, which is per-replica and lost on restart.

**Notifications is not ALB-exposed.** Its chart sets `ingress.enabled: false`, so it
receives no ALB routing rule and appears in no routing table below. The orders outbox
worker reaches it over cluster-internal DNS (`http://notifications:8000`).

---

## Order Lifecycle State Machine

```mermaid
stateDiagram-v2
    [*] --> created: Order placed
    created --> reserved: Stock reserved
    created --> cancelled: Cancel
    created --> failed: Reservation failed
    
    reserved --> paid: Payment success
    reserved --> cancelled: Cancel / Payment failed
    reserved --> failed: Error
    
    paid --> producing: Production started
    paid --> cancelled: Cancel before production
    
    producing --> shipped: Production complete
    producing --> failed: Production error
    
    shipped --> delivered: Delivery confirmed
    
    delivered --> [*]
    cancelled --> [*]
    failed --> [*]
```

---

## Checkout & Payment Flow

```mermaid
sequenceDiagram
    participant Customer
    participant Frontend
    participant Orders
    participant Inventory
    participant Payments
    participant Production
    participant Notifications
    
    Customer->>Frontend: Add to cart & checkout
    Frontend->>Orders: POST /orders
    Orders->>Inventory: Reserve stock (15min TTL)
    Inventory-->>Orders: Reservation confirmed
    Orders-->>Frontend: Order created (reserved)
    
    Frontend->>Orders: POST /orders/{id}/checkout
    Orders->>Payments: Create checkout session
    Payments-->>Orders: Session URL
    Orders-->>Frontend: Redirect to payment
    
    Customer->>Payments: Complete payment
    Payments->>Orders: Webhook: checkout.session.completed
    Orders->>Inventory: Commit reservation
    Inventory-->>Orders: Stock committed
    
    Note over Orders: Emit ORDER_PAID to outbox
    
    Orders-->>Payments: 200 OK
    
    loop Outbox Worker (2s poll)
        Orders->>Production: POST /events/order-paid
        Production-->>Orders: 200 OK (event processed)
        Orders->>Notifications: POST /events/order-paid
        Notifications-->>Orders: 200 OK (confirmation email sent)
    end
    
    Production->>Orders: POST /orders/{id}/produce
    
    Note over Production: CPU-intensive work
    
    Production->>Logistics: POST /ship
    Logistics-->>Production: Shipment created
    Production->>Orders: POST /orders/{id}/ship
    
    Note over Orders: Emit ORDER_SHIPPED to outbox (same TX)
    
    Orders->>Notifications: POST /events/order-shipped
    Notifications-->>Orders: 200 OK (shipping email sent)
```

`ORDER_PAID` fans out to both production and notifications from a single outbox row.
Delivery is sequential within one worker pass, and the retry unit is the whole event
rather than the individual subscriber.

---

## Stock Reservation Flow

```mermaid
sequenceDiagram
    participant Orders
    participant Inventory
    participant DB as Inventory DB
    participant Worker as Expiry Worker
    
    Orders->>Inventory: POST /reserve
    Inventory->>DB: BEGIN TRANSACTION
    Inventory->>DB: Check available stock
    
    alt Sufficient stock
        Inventory->>DB: Decrease available, increase reserved
        Inventory->>DB: Create reservation (expires_at = now + 15min)
        Inventory->>DB: COMMIT
        Inventory-->>Orders: Reservation confirmed
    else Insufficient stock
        Inventory->>DB: ROLLBACK
        Inventory-->>Orders: 409 Conflict
    end
    
    Note over Worker: Every 30 seconds
    
    Worker->>DB: Find expired active reservations
    Worker->>DB: Return stock to available
    Worker->>DB: Mark reservation as "expired"
```

---

## Event-Driven Architecture (Outbox Pattern)

```mermaid
flowchart LR
    subgraph "Orders Service"
        BL[Business Logic]
        OT[(outbox_events)]
        OW[Outbox Worker]
    end
    
    subgraph "Production Service"
        EH[Event Handler]
        JQ[(Jobs Queue)]
    end
    
    subgraph "Notifications Service"
        NEH[Event Handler]
        EP[Email Provider<br/>logging / SES]
    end
    
    BL -->|"1. Same TX"| OT
    OW -->|"2. Poll (2s)"| OT
    OW -->|"3a. HTTP POST"| EH
    EH -->|"4a. Create job"| JQ
    EH -->|"5a. 200 OK"| OW
    OW -->|"3b. HTTP POST"| NEH
    NEH -->|"4b. Render & send"| EP
    NEH -->|"5b. 200 OK"| OW
    OW -->|"6. Mark delivered<br/>(only after ALL subscribers succeed)"| OT
```

Step 6 is the important subtlety: the outbox row is marked delivered only once every
subscriber for that event type has returned success. A failure at any single subscriber
retries the whole event, re-delivering it to subscribers that already succeeded, which is
why every consumer must be idempotent.

---

## Database Schema Overview

```mermaid
erDiagram
    orders_schema_orders {
        int id PK
        string customer_email
        string status
        decimal total_amount
        string checkout_session_id
        string payment_intent_id
        timestamp created_at
        timestamp updated_at
    }
    
    orders_schema_order_items {
        int id PK
        int order_id FK
        string sku
        string name
        int quantity
        decimal unit_price
    }
    
    orders_schema_outbox_events {
        int id PK
        string event_type
        string aggregate_type
        string aggregate_id
        text payload
        timestamp delivered_at
        int retry_count
    }
    
    inventory_schema_stock {
        int id PK
        string sku UK
        string name
        int available
        int reserved
    }
    
    inventory_schema_reservations {
        int id PK
        int order_id
        string sku
        int quantity
        string status
        timestamp expires_at
    }
    
    production_schema_jobs {
        int id PK
        int order_id UK
        string status
        text items_json
        int processing_time_ms
    }
    
    logistics_schema_shipments {
        int id PK
        int order_id
        string status
        string tracking
    }
    
    users_schema_users {
        int id PK
        string email UK
        string password_hash
        string role
    }
    
    catalog_schema_products {
        int id PK
        string sku UK
        string name
        decimal price
        string category
    }
    
    orders_schema_orders ||--o{ orders_schema_order_items : contains
    orders_schema_orders ||--o| orders_schema_outbox_events : emits
    inventory_schema_stock ||--o{ inventory_schema_reservations : has
    production_schema_jobs ||--|| orders_schema_orders : processes
    logistics_schema_shipments ||--|| orders_schema_orders : ships
```

---

## Kubernetes Deployment Architecture

```mermaid
graph TB
    subgraph "AWS Cloud"
        subgraph "VPC"
            subgraph "EKS Cluster"
                subgraph "postershop namespace"
                    FE_DEP[frontend<br/>Deployment]
                    USERS_DEP[users<br/>Deployment]
                    CATALOG_DEP[catalog<br/>Deployment]
                    ORDERS_DEP[orders<br/>Deployment]
                    INVENTORY_DEP[inventory<br/>Deployment]
                    PRODUCTION_DEP[production<br/>Deployment]
                    LOGISTICS_DEP[logistics<br/>Deployment]
                    PAYMENTS_DEP[payments<br/>Deployment]
                    INFRA_DEP[infra<br/>Deployment]
                    NOTIFICATIONS_DEP[notifications<br/>Deployment<br/>no ingress]
                end
                
                subgraph "kube-system"
                    ALB_CTRL[ALB Controller]
                end
                
                subgraph "monitoring"
                    LOKI[Loki]
                    FLUENTBIT[Fluent Bit<br/>DaemonSet]
                end
            end
            
            ALB_EXT[Application<br/>Load Balancer]
            RDS[(RDS PostgreSQL)]
        end
    end
    
    Internet --> ALB_EXT
    ALB_EXT --> FE_DEP
    ALB_EXT --> USERS_DEP
    ALB_EXT --> CATALOG_DEP
    ALB_EXT --> ORDERS_DEP
    ALB_EXT --> INVENTORY_DEP
    ALB_EXT --> PRODUCTION_DEP
    ALB_EXT --> LOGISTICS_DEP
    ALB_EXT --> PAYMENTS_DEP
    ALB_EXT --> INFRA_DEP
    
    FE_DEP -.-> RDS
    USERS_DEP --> RDS
    CATALOG_DEP --> RDS
    ORDERS_DEP --> RDS
    INVENTORY_DEP --> RDS
    PRODUCTION_DEP --> RDS
    LOGISTICS_DEP --> RDS
    
    FLUENTBIT --> LOKI
```

---

## Path-Based Routing (ALB Ingress)

| Path Pattern | Service | Port |
|--------------|---------|------|
| `/users/*` | users | 8000 |
| `/catalog/*` | catalog | 8000 |
| `/orders/*` | orders | 8000 |
| `/inventory/*` | inventory | 8000 |
| `/production/*` | production | 8000 |
| `/logistics/*` | logistics | 8000 |
| `/payments/*` | payments | 8000 |
| `/infra/*` | infra | 8000 |
| `/*` (default) | frontend | 80 |

---

## Logging Architecture

```mermaid
flowchart LR
    subgraph "Application Pods"
        S1[Service 1]
        S2[Service 2]
        S3[Service N]
    end
    
    subgraph "Node"
        LOG[/var/log/containers/]
    end
    
    subgraph "Fluent Bit DaemonSet"
        FB[Fluent Bit]
    end
    
    subgraph "Loki"
        LOKI_IN[Loki Ingester]
        LOKI_ST[(Storage)]
    end
    
    S1 -->|stdout/stderr| LOG
    S2 -->|stdout/stderr| LOG
    S3 -->|stdout/stderr| LOG
    
    FB -->|tail| LOG
    FB -->|push| LOKI_IN
    LOKI_IN --> LOKI_ST
```

**Log Format (JSON):**
```json
{
  "timestamp": "2024-01-15T10:30:00.123Z",
  "level": "INFO",
  "service": "orders",
  "correlation_id": "abc-123-def",
  "message": "Order created",
  "order_id": 42
}
```
