from importlib import import_module
from typing import Any


class ExtensionConfigurationError(RuntimeError):
    pass


def load_registrar_modules(
    module_refs: list[str],
    *,
    hook_name: str,
    registry: Any,
) -> None:
    """Load explicitly configured extension modules.

    A module reference may be either ``package.module`` (using ``hook_name``) or
    ``package.module:callable``. Extensions are deployment configuration, so a
    broken configured module fails fast instead of silently shrinking the
    installed capability surface.
    """

    for module_ref in module_refs:
        module_name, separator, explicit_hook = module_ref.partition(":")
        try:
            module = import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            raise ExtensionConfigurationError(
                f"无法加载扩展模块 {module_name}: {type(exc).__name__}"
            ) from exc
        registrar_name = explicit_hook if separator else hook_name
        registrar = getattr(module, registrar_name, None)
        if not callable(registrar):
            raise ExtensionConfigurationError(
                f"扩展模块 {module_name} 缺少可调用入口 {registrar_name}"
            )
        try:
            registrar(registry)
        except Exception as exc:  # noqa: BLE001
            raise ExtensionConfigurationError(
                f"扩展模块 {module_name} 注册失败: {type(exc).__name__}"
            ) from exc
