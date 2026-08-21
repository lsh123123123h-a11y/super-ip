"""Product-level composition that turns an intent into Agent kernel contracts."""

from app.product.digital_human_plan import (
    build_digital_human_plan,
    build_intent_spec,
)
from app.product.registry import ProductRegistry, get_product_registry

__all__ = [
    "ProductRegistry",
    "build_digital_human_plan",
    "build_intent_spec",
    "get_product_registry",
]
