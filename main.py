import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, timezone

from database import db, create_document, get_documents

# Utils
from bson import ObjectId


def to_str_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = {**doc}
    if d.get("_id") is not None:
        d["id"] = str(d.pop("_id"))
    # Convert datetime to isoformat
    for k, v in list(d.items()):
        if isinstance(v, datetime):
            d[k] = v.astimezone(timezone.utc).isoformat()
    return d


# Pydantic models for requests
class TenantIn(BaseModel):
    subdomain: str = Field(..., pattern=r"^[a-z0-9-]+$", description="Unique subdomain (lowercase, digits, hyphen)")
    name: str
    description: Optional[str] = None
    logo_url: Optional[str] = None
    payment_details: Dict[str, Any] = Field(default_factory=dict)


class ProductIn(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    inventory: int = Field(..., ge=0)
    image_urls: List[str] = Field(default_factory=list)
    is_active: bool = True


class OrderIn(BaseModel):
    tenant_id: str
    customer_name: str
    customer_email: str
    shipping_address: Dict[str, Any]
    order_total: float = Field(..., ge=0)
    status: str = Field("pending_payment")
    transaction_id: Optional[str] = None
    payment_screenshot_url: Optional[str] = None


class OrderUpdate(BaseModel):
    status: Optional[str] = None
    transaction_id: Optional[str] = None
    payment_screenshot_url: Optional[str] = None


app = FastAPI(title="1MinuteShop API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "1MinuteShop Backend Running"}


# Tenants
@app.post("/tenants")
def create_tenant(tenant: TenantIn):
    # Ensure unique subdomain
    existing = db["tenant"].find_one({"subdomain": tenant.subdomain}) if db else None
    if existing:
        raise HTTPException(status_code=400, detail="Subdomain already exists")
    tenant_dict = tenant.model_dump()
    tenant_dict["created_at"] = datetime.now(timezone.utc)
    tenant_dict["updated_at"] = datetime.now(timezone.utc)
    inserted_id = db["tenant"].insert_one(tenant_dict).inserted_id
    created = db["tenant"].find_one({"_id": inserted_id})
    return to_str_id(created)


@app.get("/tenants/by-subdomain/{subdomain}")
def get_tenant_by_subdomain(subdomain: str):
    t = db["tenant"].find_one({"subdomain": subdomain}) if db else None
    if not t:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return to_str_id(t)


# Products
@app.post("/products")
def create_product(product: ProductIn):
    # Scope to tenant
    tenant = db["tenant"].find_one({"_id": ObjectId(product.tenant_id)}) if ObjectId.is_valid(product.tenant_id) else None
    if not tenant:
        # allow matching by subdomain fallback
        tenant = db["tenant"].find_one({"subdomain": product.tenant_id})
    if not tenant:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")
    data = product.model_dump()
    data["tenant_id"] = str(tenant["_id"])  # normalize to id string
    _id = create_document("product", data)
    created = db["product"].find_one({"_id": ObjectId(_id)})
    return to_str_id(created)


@app.get("/products")
def list_products(tenant_id: str = Query(..., description="Tenant id or subdomain"), only_active: bool = True):
    # Resolve tenant id
    tenant = db["tenant"].find_one({"_id": ObjectId(tenant_id)}) if ObjectId.is_valid(tenant_id) else None
    if not tenant:
        tenant = db["tenant"].find_one({"subdomain": tenant_id})
    if not tenant:
        raise HTTPException(status_code=400, detail="Invalid tenant")
    filt: Dict[str, Any] = {"tenant_id": str(tenant["_id"])}
    if only_active:
        filt["is_active"] = True
    docs = db["product"].find(filt).sort("created_at", -1)
    return [to_str_id(d) for d in docs]


@app.put("/products/{product_id}")
def update_product(product_id: str, product: ProductIn):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product id")
    existing = db["product"].find_one({"_id": ObjectId(product_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    # Ensure tenant scope matches
    if existing.get("tenant_id") != product.tenant_id:
        # allow subdomain match
        tenant = db["tenant"].find_one({"subdomain": product.tenant_id})
        if not tenant or str(tenant["_id"]) != existing.get("tenant_id"):
            raise HTTPException(status_code=403, detail="Tenant mismatch")
    update = product.model_dump()
    update["updated_at"] = datetime.now(timezone.utc)
    db["product"].update_one({"_id": ObjectId(product_id)}, {"$set": update})
    updated = db["product"].find_one({"_id": ObjectId(product_id)})
    return to_str_id(updated)


@app.delete("/products/{product_id}")
def delete_product(product_id: str, tenant_id: str = Query(...)):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(status_code=400, detail="Invalid product id")
    existing = db["product"].find_one({"_id": ObjectId(product_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found")
    # Verify tenant has rights
    if existing.get("tenant_id") != tenant_id:
        tenant = db["tenant"].find_one({"subdomain": tenant_id})
        if not tenant or str(tenant["_id"]) != existing.get("tenant_id"):
            raise HTTPException(status_code=403, detail="Tenant mismatch")
    db["product"].delete_one({"_id": ObjectId(product_id)})
    return {"deleted": True}


# Orders
@app.post("/orders")
def create_order(order: OrderIn):
    # Resolve tenant
    tenant = db["tenant"].find_one({"_id": ObjectId(order.tenant_id)}) if ObjectId.is_valid(order.tenant_id) else None
    if not tenant:
        tenant = db["tenant"].find_one({"subdomain": order.tenant_id})
    if not tenant:
        raise HTTPException(status_code=400, detail="Invalid tenant")
    data = order.model_dump()
    data["tenant_id"] = str(tenant["_id"])  # normalize
    data["created_at"] = datetime.now(timezone.utc)
    data["updated_at"] = datetime.now(timezone.utc)
    inserted_id = db["order"].insert_one(data).inserted_id
    created = db["order"].find_one({"_id": inserted_id})
    return to_str_id(created)


@app.get("/orders")
def list_orders(tenant_id: str = Query(...)):
    tenant = db["tenant"].find_one({"_id": ObjectId(tenant_id)}) if ObjectId.is_valid(tenant_id) else None
    if not tenant:
        tenant = db["tenant"].find_one({"subdomain": tenant_id})
    if not tenant:
        raise HTTPException(status_code=400, detail="Invalid tenant")
    docs = db["order"].find({"tenant_id": str(tenant["_id"]) }).sort("created_at", -1)
    return [to_str_id(d) for d in docs]


@app.patch("/orders/{order_id}")
def update_order(order_id: str, payload: OrderUpdate):
    if not ObjectId.is_valid(order_id):
        raise HTTPException(status_code=400, detail="Invalid order id")
    existing = db["order"].find_one({"_id": ObjectId(order_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Order not found")
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        return to_str_id(existing)
    update["updated_at"] = datetime.now(timezone.utc)
    db["order"].update_one({"_id": ObjectId(order_id)}, {"$set": update})
    updated = db["order"].find_one({"_id": ObjectId(order_id)})
    return to_str_id(updated)


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
