# Weftgate launch plan

Goal: earn 1,000 genuine GitHub stars by making a useful verification gate easy to
try, trust, and extend. This is a target, not a promise or a forecast. Stars are a
secondary measure; repeat usage, reproducible bug reports, and outside contributions
are better evidence of value.

## Positioning

**Catch broken connections in agent-written code before it ships.**

For developers using coding agents in Python/FastAPI or Node projects, Weftgate checks
env reads against declarations, imports against dependency metadata, and FastAPI route
references against handlers. One local gate works through the CLI, MCP, hooks, and CI.
The default core requires no API key and sends no repository contents over the network.

Lead with a concrete example: `DATABSE_URL` → `DATABASE_URL`. Show actual output and
explain that uncertain references return `review` or `unverifiable`. Avoid claims of
universal coverage, zero false positives, guaranteed token savings, or security certification.
The demo uses an intentionally broken fixture; its results are not field benchmarks.

## Ship before promoting

- Public repository with a short README, working installation, quickstart, license,
  supported-stack table, known limitations, contribution guide, and a false-block template.
- Released wheel tested outside the source checkout, tagged Action, green OS/Python CI,
  trusted publishing, release notes, and Marketplace listing if eligible.
- Captioned MP4, lightweight GIF, poster, and the exact code/results used in the demo.
- Minimal reproducible examples covering `reject`, `accept`, `review`, and `unverifiable`.
- No need to install mnemo to try the verification gate. Keep the optional integration
  clearly marked while the mnemo repository is private.

## Six-week plan

Dates start after the first verified public release. Do not publish a broken install
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

Local verification for coding agents: catch broken env, import, and FastAPI route
references. CLI, MCP, hooks, and GitHub Action. No API key.

### Show HN: human-authored submission

The maintainer should submit the repository link with a factual title beginning
“Show HN”, explain their own motivation, and be available to discuss it personally.
Do not paste AI-generated introductory comments or replies: the
[HN discussion guidelines](https://news.ycombinator.com/newsguidelines.html) prohibit
generated and AI-edited text in comments. Never solicit votes or coordinated comments.

### LinkedIn / personal technical post

Agent-written code can look plausible while pointing at the wrong thing.

I’m releasing Weftgate, an open-source local gate for env declarations, dependency
imports, and FastAPI route references. The short demo shows three real findings,
the suggested corrections, and the clean recheck.

The central rule: block only on a machine-checkable false reference. Dynamic or
incomplete evidence stays advisory. It works through a CLI, MCP, hooks, and CI.

Try it on a project you know well:
`pip install weftgate`
`weftgate audit`

I’d like feedback on installation, useful catches, and false blocks.
https://github.com/Avinash-Amudala/weftgate

Attach `docs/assets/weftgate-demo.mp4`. Publish once, answer responses, and share a
follow-up only when there is a concrete improvement or result.

### Community post

Use a minimal example in the community’s language/stack. Explain the failure and the
limitations first. State “I maintain this project.” Check the community’s current
rules immediately before posting. Do not paste identical posts into many communities.

## Published launch posts

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

No third-party posts, direct outreach, or advertising purchases are claimed complete
by this document. Record actual published URLs after posting.
