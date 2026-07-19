"""Skills registry: each skill contributes OpenAI-format tool schemas + handlers.

To add a capability, create a module exposing `build(ctx) -> dict[name, (schema, handler)]`
and add it to MODULES. `ctx` carries shared services (engine, config, ...).
"""

import logging

from . import checkins

MODULES = [checkins]
log = logging.getLogger(__name__)


def build_registry(ctx):
    registry = {}
    for module in MODULES:
        registry.update(module.build(ctx))
    schemas = [schema for schema, _ in registry.values()]

    async def dispatch(name, args):
        log.info("tool call: %s %s", name, args)
        if name not in registry:
            return {"error": f"unknown tool {name}"}
        _, handler = registry[name]
        result = await handler(**args)
        log.info("tool result: %s %s", name, result)
        return result

    return schemas, dispatch
