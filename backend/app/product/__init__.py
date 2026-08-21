"""Product-level composition that turns an intent into Agent kernel contracts."""

from app.product.digital_human_plan import (
    build_digital_human_plan,
    build_intent_spec,
)

__all__ = ["build_digital_human_plan", "build_intent_spec"]
