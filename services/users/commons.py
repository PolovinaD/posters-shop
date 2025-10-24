from enum import Enum

SERVICE_NAME = "users"
SCHEMA_NAME = SERVICE_NAME
TABLE_NAME = SERVICE_NAME

class UserRole(str, Enum):
    OWNER = "owner"
    CUSTOMER = "customer"
    COURIER = "courier"