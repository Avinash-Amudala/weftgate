"""Built-in oracles. Each also exposes ``register(api)`` for entry-point discovery.

``BUILTIN`` lets the registry find them by bare name even when the package was
not installed with its entry points (for example, run straight from a checkout).
"""

BUILTIN: dict[str, str] = {
    "env_vars": "weft.oracles.env_vars:register",
    "imports_lockfile": "weft.oracles.imports_lockfile:register",
    "routes_fastapi": "weft.oracles.routes_fastapi:register",
}
