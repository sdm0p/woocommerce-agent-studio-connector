from pydantic import BaseModel, ConfigDict


class LineItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    product_id: int
    name: str
    quantity: int
    subtotal: str
    total: str


class OrderSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    customer_id: int
    status: str
    date_created: str | None = None
    date_modified: str | None = None
    date_created_gmt: str | None = None
    date_modified_gmt: str | None = None
    currency: str
    total: str
    total_tax: str
    shipping_total: str
    discount_total: str
    line_items: list[LineItem]


class OrderPage(BaseModel):
    orders: list[OrderSummary]
    page: int
    per_page: int
    total: int
    total_pages: int
    next_page: int | None
