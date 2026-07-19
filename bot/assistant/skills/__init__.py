"""Skills registry: each skill contributes OpenAI-format tool schemas + handlers.

To add a capability, create a module exposing `build(ctx) -> dict[name, (schema, handler)]`
and add it to MODULES. `ctx` carries shared services (engine, config, ...).
"""

from . import checkins

MODULES = [checkins]


def build_registry(ctx):
    registry = {}
    for module in MODULES:
        registry.update(module.build(ctx))
    schemas = [schema for schema, _ in registry.values()]

    async def dispatch(name, args):
        if name not in registry:
            return {"error": f"unknown tool {name}"}
        _, handler = registry[name]
        return await handler(**args)

    return schemas, dispatch
