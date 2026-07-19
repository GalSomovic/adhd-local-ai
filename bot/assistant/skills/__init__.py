"""Skills registry: each skill contributes OpenAI-format tool schemas + handlers.

To add a capability, create a module exposing `build(ctx) -> dict[name, (schema, handler)]`
and add it to MODULES (or GOOGLE_MODULES if it needs Google credentials).
`ctx` carries shared services (engine, conn, ...).
"""

import logging

from .. import gapi
from . import checkins

log = logging.getLogger(__name__)

MODULES = [checkins]


def build_registry(ctx):
    modules = list(MODULES)
    if gapi.enabled():
        from . import brief, gcal, gmail_skill, gtasks
        modules += [gmail_skill, gcal, gtasks, brief]
        log.info("google skills enabled")
    else:
        log.info("google skills disabled (no credentials)")

    registry = {}
    for module in modules:
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
