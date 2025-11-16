"""
Database Schemas for 1MinuteShop (MongoDB via helper in database.py)

Each Pydantic model name maps to a MongoDB collection using its lowercase name.
- Tenant -> "tenant"
- Product -> "product"
- Order -> "order"
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class Tenant(BaseModel):
    """Tenant (store) metadata"""
    subdomain: str = Field(..., description="Unique subdomain for the store, e.g., 'my-shop'")
    name: str = Field(..., description="Store name")
    description: Optional[str] = Field(None, description="Store description")
    logo_url: Optional[str] = Field(None, description="Public URL to the store logo")
    payment_details: Dict[str, Any] = Field(default_factory=dict, description="Payment metadata like upi_id, bank_acc, paypal, etc.")


class Product(BaseModel):
    """Product belonging to a tenant"""
    tenant_id: str = Field(..., description="Reference to Tenant id or subdomain")
    name: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    inventory: int = Field(..., ge=0)
    image_urls: List[str] = Field(default_factory=list)
    is_active: bool = True


class Order(BaseModel):
    """Order placed by a customer for a tenant"""
    tenant_id: str
    customer_name: str
    customer_email: str
    shipping_address: Dict[str, Any]
    order_total: float = Field(..., ge=0)
    status: str = Field("pending_payment", description="pending_payment|verified|shipped|cancelled")
    transaction_id: Optional[str] = None
    payment_screenshot_url: Optional[str] = None
    created_at: Optional[datetime] = None
