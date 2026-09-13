# Grounded context

Use `resolve`, `neighbors` and `card` from the CLI or identically named MCP tools.
All three refresh the oracle index and verify Python parsing cache entries by
content hash, including uncommitted changes. They never import or execute your app.

```bash
weftgate resolve DATABASE_URL
weftgate resolve app/orders.py:create_order
weftgate neighbors create_order --hops 2
weftgate card "POST /api/orders" --budget 1200
```

## Coverage

The current graph contains Python function/class definitions with line locations,
source files, declared environment names, manifest dependencies and statically
enumerated FastAPI/Starlette routes. Edges include declarations, imported packages,
environment reads and direct local route handlers. Contract reads are linked only
when the existing gate accepts that reference. Missing or dynamic references appear
as review notes instead of fabricated edges. The graph is not a runtime call graph.

Resolve uses exact IDs, names, or unqualified symbol names. Multiple matches are
reported as ambiguous. Neighbors walks one to three undirected hops; `card` uses
three. `--kinds` filters returned node cards. Every edge contains complete locators,
so it remains interpretable when some node cards are omitted by the budget.

Python syntax errors, unreadable sources, symlinks, source files larger than 512 KB
and binary files are skipped and counted in `index_notes`. Git ignore rules and
Weftgate directory exclusions apply. Non-source assets are not inventoried unless
they declare an indexed contract. File bodies and environment values are never
returned. Symbols and static registrations are observations, not guarantees that
conditional code executes, a route is reachable, or a name cannot be rebound.

## Payload budget

`--budget N`, MCP `budget`, or `WEFTGATE_CONTEXT_BUDGET` sets an **estimated** token
budget from 256 to 16,000. The default is 1,500. The enforced limit is `N * 4`
UTF-8 bytes for the compact JSON text, including its accounting envelope.
The estimate is `ceil(bytes / 4)` and can differ from a model's actual tokenizer.
Transport headers and client-added tool wrappers are outside that cap.

Items are ranked deterministically by distance, then stable IDs. Whole items are
omitted instead of cutting JSON or truncating source bodies. `usage.omitted` counts
elided items. Inspect `matches`, `status`, `index_notes` and `usage`, then request a
narrower reference or larger budget when needed. No exact model-token guarantee or
universal token-savings claim is made.

The default MCP response includes the text payload once, avoiding duplication in
`structuredContent`. `weftgate ledger` records byte counts and operations, never
context bodies, queries, note text or secret values. Set `WEFTGATE_LEDGER=0` to stop
recording and `weftgate ledger --clear` to delete the event file.
