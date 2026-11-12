"""Compatibility exports; definitions live in domain modules."""

from app.models.orders.catalog import Campaign, Customer, Product
from app.models.orders.deals import Deal, DealEvent
from app.models.orders.orders import Order, OrderEvent
from app.models.orders.production import CapacityPlan, ProductionRecord
from app.models.orders.support import SupportInteraction

__all__ = [
    "Campaign",
    "CapacityPlan",
    "Customer",
    "Deal",
    "DealEvent",
    "Order",
    "OrderEvent",
    "Product",
    "ProductionRecord",
    "SupportInteraction",
]
