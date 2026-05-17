"""Custom drop-in tool auto-discovery."""

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def get_custom_tools() -> dict:
    tools = {}
    for _, name, _ in pkgutil.iter_modules([__path__[0]]):
        try:
            mod = importlib.import_module(f".{name}", __package__)
            if hasattr(mod, "register"):
                tools.update(mod.register())
        except Exception as e:
            logger.debug(f"Custom tool '{name}' skipped: {e}")
    return tools


def get_custom_schemas() -> list:
    schemas = []
    for _, name, _ in pkgutil.iter_modules([__path__[0]]):
        try:
            mod = importlib.import_module(f".{name}", __package__)
            if hasattr(mod, "schema"):
                schemas.append(mod.schema())
        except Exception as e:
            logger.debug(f"Custom schema '{name}' skipped: {e}")
    return schemas
