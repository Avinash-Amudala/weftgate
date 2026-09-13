# Weftgate launch plan

Goal: earn 1,000 genuine GitHub stars by making a useful verification gate easy to
try, trust, and extend. This is a target, not a promise or a forecast. Stars are a
secondary measure; repeat usage, reproducible bug reports, and outside contributions
are better evidence of value.

## Positioning

**A local second brain for coding agents. Understand. Remember. Verify.**

Weftgate brings source-backed context, a local decision notebook, and verification
into one Python package. It exposes the same tools through CLI and MCP, configures
completion gates for Codex, Claude Code, Cursor and Antigravity, and offers a GitHub
Action for merge checks. No API key or private mnemo installation is needed.

Make the three benefits visible immediately:

| Benefit | Demonstration | Precise claim |
| --- | --- | --- |
| Understand | A route contract card with source locations and relationships. | Compact static context with an explicit JSON byte cap; model tokens are estimated. |
| Remember | Save a decision, change its cited file, recall again. | Stale source-backed notes are hidden by default; unchanged sources do not prove prose true. |
| Verify | Misspelled env name, missing dependency, undefined route handler, then a clean recheck. | Positive false references block; dynamic and unavailable evidence stays advisory. |

The 78-second film demonstrates these with captured CLI evidence and a custom brain
visual. It uses an intentionally broken fixture, not a field benchmark. Avoid claims
of universal editor enforcement, full call-graph understanding, automatic test repair,
zero false positives, exact token savings, or guaranteed correct software.

## Ship before promoting

- Public repository with a short README, working installation, quickstart, license,
  supported-stack table, known limitations, contribution guide, and a false-block template.
- Released wheel tested outside the source checkout, tagged Action, green OS/Python CI,
  trusted publishing, release notes, and Marketplace listing if eligible.
- Captioned MP4, lightweight GIF, poster, and the exact code/results used in the demo.
- Minimal reproducible examples covering `reject`, `accept`, `review`, and `unverifiable`.
- Context, recall and gates install together. Keep the legacy companion integration
  clearly marked while the mnemo repository remains private.

## Six-week plan

Use the original release as the baseline; the v0.2 update adds a substantive context/memory story. Do not publish a broken install
link to meet a calendar date. The milestones below are planning checkpoints, not
predicted star counts.

| Window | Work | Evidence to collect | Decision |
| --- | --- | --- | --- |
| Days 1–3 | Publish release and demo. Share a technical walkthrough on the maintainer’s chosen account. | Installation failures, reproducible findings, first outside trial reports. | Fix onboarding before expanding reach. |
| Days 4–7 | Personally help 5–10 willing developers run an audit. No unsolicited bulk messages. | Which stacks work, confusing output, false blocks, setup friction. | Publish the reproducible lessons, with permission for attributed examples. |
| Week 2 | Submit one Show HN when the maintainer can answer questions. Offer a command people can try without signing up. | Visits, clones, substantive feedback, issue reports. | Address feedback; do not repost for votes. |
| Week 3 | Share a stack-specific example in one relevant community that permits project posts. Disclose authorship. | Useful conversations and another 5 trial reports. | Improve the example if users cannot reproduce it. |
| Week 4 | Write an oracle-authoring tutorial and open bounded contribution issues. | First outside documentation or oracle contribution. | Pair with contributors and publish a tested patch release. |
| Weeks 5–6 | Publish a transparent follow-up with methods, limitations, and outcomes. Seek one relevant newsletter/editor mention. | Returning adopters, outside contributions, cumulative stars. | Invest in the channels that produced users; revise the strategy if it did not. |

A simple scenario model: at a hypothetical 5% visit-to-star rate, 1,000 stars would
require 20,000 qualified repository visits. At 2%, it would require 50,000. These are
arithmetic scenarios, not observed conversion rates. Broad reach is insufficient if
the tool does not solve a problem for those visitors.

## Ready-to-use launch copy

### Repository description

Local second brain for coding agents: grounded context, source-checked memory and
verification gates. CLI, MCP, editor hooks and CI. No API key.

### Show HN: human-authored submission

The maintainer should submit the repository link with a factual title beginning
“Show HN”, explain their own motivation, and be available to discuss it personally.
Do not paste AI-generated introductory comments or replies: the
[HN discussion guidelines](https://news.ycombinator.com/newsguidelines.html) prohibit
generated and AI-edited text in comments. Never solicit votes or coordinated comments.

### LinkedIn / personal technical post

Weftgate 0.2 gives coding agents a local second brain.

Understand: ask for compact source context instead of loading whole files.
Remember: save decisions with file anchors, and hide them when their sources change.
Verify: catch broken env, import and FastAPI route references, then collect observed
test results before handing work back.

One install. CLI and MCP. Setup for Codex, Claude Code, Cursor and Antigravity.
No API key, automatic transcript capture or runtime dependencies.

Hooks need activation in your editor. Uncertainty stays advisory. Required CI checks
provide merge enforcement, and passing checks still have a defined scope.

The new 78-second demo shows the whole loop with real CLI output.
Try it: `pip install weftgate`
https://github.com/Avinash-Amudala/weftgate

I maintain this project and would like feedback on onboarding, useful context and
false blocks. Attach `docs/assets/weftgate-demo.mp4` after the release is verified.

### X announcement

Weftgate: a local second brain for coding agents.

Understand code. Remember decisions. Verify changes.

Source-backed context, memory that notices changed files, and gates for Codex,
Claude Code, Cursor and Antigravity.

https://github.com/Avinash-Amudala/weftgate

Attach the new film. Do not post a link-only substitute while native video is requested.

### Community post

Use a minimal example in the community’s language/stack. Explain the failure and the
limitations first. State “I maintain this project.” Check the community’s current
rules immediately before posting. Do not paste identical posts into many communities.

## Original v0.1 published launch posts

- [GitHub Marketplace Action](https://github.com/marketplace/actions/weftgate)
- [GitHub announcement](https://github.com/Avinash-Amudala/weftgate/discussions/11)
- [LinkedIn announcement](https://www.linkedin.com/feed/update/urn:li:share:7504740331062624256/)
- [DEV technical walkthrough](https://dev.to/avinash_amudala_8712ab560/catch-broken-environment-import-and-route-connections-with-weftgate-2h3p), with [source](launch/DEV-POST.md)
- [Show HN repository submission](https://news.ycombinator.com/item?id=49680443)

The Show HN submission contains a factual title and repository link. The maintainer
should write personal introductory comments and replies directly, in their own words.
Do not solicit coordinated votes or repost the same submission.

## Budget

Start at **$0**. Publishing, repository improvements, the demo, and personal technical
posts do not require an advertising budget.

After organic trial feedback shows the tool is useful, consider a **maximum $250
experiment**, only after the maintainer separately approves the exact placement and
quote. This is a proposed budget cap, not a current vendor quote. Prefer a clearly
disclosed placement with a relevant technical audience; do not buy stars, followers,
reviews, votes, or incentivized endorsements. Stop if a placement brings no meaningful
trial feedback or adoption. No paid campaign is authorized or scheduled by this plan.

## Metrics and privacy

Record once a week: total stars, forks, open false-block reports, resolved onboarding
issues, unique traffic and clones where GitHub provides them, and volunteered adoption
reports. GitHub traffic does not prove an install. PyPI downloads do not prove active
users. No telemetry is added to the package.

Use `python scripts/launch_metrics.py` to retrieve a dated, local JSON snapshot of
public repository counts and authorized aggregate GitHub traffic. Do not publish
private traffic data by default. Keep outreach and advertising status explicit:
**draft**, **published**, **measured**, or **blocked**.

Relevant platform references:

- [GitHub topics](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics) help describe the project for discovery.
- [Show HN guidelines](https://news.ycombinator.com/showhn.html) require something people can try and prohibit asking friends to vote.
- [GitHub Marketplace publishing](https://docs.github.com/en/actions/sharing-automations/creating-actions/publishing-actions-in-github-marketplace) describes the release-page listing flow and eligibility.

## v0.2 launch status

- Source, brain hero, captioned film, integration guide and technical article: prepared.
- Publication and fresh PyPI install: verify before posting the update.
- [v0.2 article source](launch/V020-POST.md): draft until an actual URL is recorded.
- Existing Show HN submission: preserve it; do not submit a duplicate for this update.
- X native-video upload: previously blocked by browser permissions; retry after release.
- Paid placements and direct outreach: none purchased or sent.

Record actual publication URLs and measured results here. Do not mark drafts as posts.
