"""Built-in oracles. Each also exposes ``register(api)`` for entry-point discovery.

``BUILTIN`` lets the registry find them by bare name even when the package was
not installed with its entry points (for example, run straight from a checkout).
"""

BUILTIN: dict[str, str] = {
    "env_vars": "weftgate.oracles.env_vars:register",
    "imports_lockfile": "weftgate.oracles.imports_lockfile:register",
    "routes_fastapi": "weftgate.oracles.routes_fastapi:register",
}
