# Addendum: grounded context and verified memory

*How to fold the "graph the repo plus a second brain plus token optimization" idea into weft without walking into a red ocean or losing the wedge. Slots into `docs/DESIGN.md` after section 13.*

## A1. Why this is an addendum, not a pivot

As of late 2026 the generic version of this idea is the most crowded niche in agent tooling. A local code graph served to agents over MCP for token savings has a top-tier incumbent with a published benchmark, and several others already bundle the graph, per-branch indexing, cross-session memory, and a savings ledger. Rebuilding that substrate as the headline is a losing fight.

The move is to treat the graph and the memory as a shared commodity substrate, not the product, and to keep the differentiated value on top of it. weft already has to build a per-repo relational graph, because that is what its oracles query. That same graph, once built, can serve two more consumers cheaply. The headline stays verification, which is the only part of this space that is unclaimed. The context and memory consumers are what make weft sticky, not what it is sold on.

## A2. One graph, three consumers

```
                        shared per-repo relational graph
                (built once, incremental sync, local SQLite)
                    symbols + edges + contracts + provenance
                                     |
          +--------------------------+--------------------------+
          |                          |                          |
       verify                     context                     recall
     (weft gate)             (grounded slices)          (verified memory)
   the headline;            read-only; returns          mnemo, integrated;
   blocks on proven         resolved, contract-aware    self-invalidates when
   falsehood                facts, bounded payloads     the graph changes
```

This is the portfolio through-line generalized: grounding, memory, and measurement sharing one retrieval substrate, build once and serve many. The three consumers are individually adoptable. A user can run verify alone, or add context, or add recall, and each is useful on its own.

## A3. The mechanical truth about token savings

State this plainly in the docs so the project never overclaims. MCP tool results are injected into the model's context window. An external graph does not bypass the context; it changes what fills it. The saving is real only when the response is small and high-signal. Reading whole files to trace a call chain can cost tens of thousands of tokens; a resolved structural answer can cost a few hundred. The legitimate context boost is that the agent can reason over relationships far too large to fit in context by pulling one resolved slice at a time.

Two consequences for the design. First, every context response is bounded and ranked, and returns pointers and compact cards, never file bodies. A server that returns blobs makes token usage worse, not better. Second, the differentiated token payoff is not retrieval compression, which is a saturated benchmark war, but avoided retry loops. A hallucinated reference that ships costs a full failed round trip, the attempt plus the error plus the correction, which is larger than any single retrieval saving. weft prevents that. Measure that.

## A4. The context consumer (new, read-only)

A small read-only surface over the same graph the oracles already build. Its differentiator is not size, it is that every fact it returns is verified and contract-aware: it returns edges that actually resolve, not text that merely matches.

Tools, exposed over both MCP and the CLI, identical output:

- `resolve(reference)` returns what a reference points to as a fact, with provenance. Example: `resolve("POST /orders")` returns the handler qualname and its `file:line`, or a not-found with a did-you-mean. This is the verified analogue of grep.
- `neighbors(symbol, hops=1, kinds=[...])` returns the bounded relational context around a node: its callers, callees, the route that reaches it, the config it reads. Capped node count, ranked by relevance.
- `card(unit)` returns a compact card for a unit of meaning that spans files, for example a route with its handler, the schema it validates against, and the env it reads, as one small object rather than five file reads. This is the recipe-card idea, generalized to any relational unit.

Payload discipline, enforced in code and tested:

- Every response is capped by a token budget (`WEFT_CONTEXT_BUDGET`, default small). Over budget, return the highest-ranked items plus a count of what was elided, never a truncated blob.
- Return `file:line` pointers and compact cards. Return a body only when the caller explicitly asks with a `with_body=true` flag, so the default path is frugal.
- Rank by relevance and recency, deterministically, so the same query gives the same slice.
- Never invent. If the graph cannot resolve a reference, say so with a suggestion; do not synthesize a plausible answer.

Scope guard: this is grounded context, not general semantic search. It does not try to beat the retrieval-graph incumbents on breadth or embeddings. It serves the facts weft can verify, served small. If a user wants broad semantic search, they run one of the existing tools alongside; weft integrates, it does not reimplement.

## A5. The recall consumer (integrate mnemo, do not rebuild)

Memory is crowded and increasingly native to the IDEs, and you already own a verified-memory engine in mnemo. So recall is an integration, not a new build. mnemo becomes the memory consumer of the shared graph, and gains the one capability the token-savings memory tools lack.

The differentiator is self-invalidation on code change. A stored memory records the graph nodes and the commit it was grounded on. When the graph syncs and those nodes change, the memory is marked stale automatically, so recall never serves a fact that the code has since contradicted. The token-savings memory tools persist whatever the agent asserts, unverified and unaged; this is verified memory that knows when it has gone out of date.

Concrete hook: the store records, per memory, the referenced node ids and the `valid_commit`. The graph's `sync` emits a changed-node set. A memory whose referenced nodes intersect the changed set flips to `stale` and drops out of recall until re-verified. This reuses weft's oracles as the re-verification path: a stale memory is re-checked by the same gate that would check new code.

## A6. The honest token metric

Ship a ledger, but measure the metric you own, not the one you cannot win.

- Record, per session, the context weft served small (resolved facts and cards) and, where the agent cooperates, an estimate of the whole-file reads it displaced. Report this as an estimate, labeled as such.
- Record avoided retry loops: every `REJECT` the gate produced before execution, with a conservative estimate of the round trip it prevented. This is the differentiated number and the one to lead with.
- Do not report a single headline compression percentage as if it were a field number. Any figure measured on the same repo it was tuned on is an upper bound, and the docs say so. The credible number is the one a user generates on their own repo with `weft audit` and the ledger, not a marketing percentage.

## A7. What still stays out

- Do not compete on generic semantic retrieval or a headline token-compression percentage. That category has winners; integrate beside them.
- Do not build a third memory engine. Integrate mnemo.
- Do not let the graph or the brain become the pitch. The pitch is verification. The graph and the brain are what make it sticky and cheap to run, because the substrate is built once and shared three ways.
- Keep the core standard-library-only and every heavier capability an optional extra that degrades to unverifiable, exactly as in the base design.

## A8. Sequencing

Do not build all three consumers at once; that is how the project fails to ship. Order: finish verify (the base design, v0.1). Add the context surface as v0.2, since it rides the graph that verify already builds and the marginal cost is low. Add recall as v0.3 by integrating mnemo, once the graph exposes a stable changed-node set for self-invalidation. Each step ships and is useful before the next begins.
