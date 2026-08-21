from functools import lru_cache

from app.core.config import get_settings
from app.core.extensions import load_registrar_modules
from app.product.base import ProductAdapter


class ProductRegistry:
    def __init__(self) -> None:
        self._products: dict[str, ProductAdapter] = {}

    def register(self, product: ProductAdapter) -> None:
        if product.key in self._products:
            raise ValueError(f"产品适配器重复注册：{product.key}")
        self._products[product.key] = product

    def resolve(self, key: str) -> ProductAdapter | None:
        return self._products.get(key)

    def require(self, key: str) -> ProductAdapter:
        product = self.resolve(key)
        if product is None:
            raise ValueError(f"产品类型尚未注册：{key}")
        return product

    def catalog(self) -> list[ProductAdapter]:
        return [self._products[key] for key in sorted(self._products)]


@lru_cache
def get_product_registry() -> ProductRegistry:
    registry = ProductRegistry()
    from app.product.content_article import register_content_article_product
    from app.product.digital_human import register_digital_human_product

    register_digital_human_product(registry)
    register_content_article_product(registry)
    load_registrar_modules(
        get_settings().extension_modules("product"),
        hook_name="register_products",
        registry=registry,
    )
    return registry
