# ReputationAttestor

An on-chain reputation registry that periodically LLM-verifies off-chain evidence -- a GitHub
profile, an X/Twitter profile, a hackathon-results page -- and maintains a composite score,
readable permissionlessly by any other protocol. A lending protocol, a DAO membership gate, or a
grant program can read `get_reputation(address)` directly, without running its own evidence
pipeline: a shared "proof of work" layer for the rest of this ecosystem.

## Reviewer summary

- **Live app**: not included in this submission -- see "Scope" below.
- **Source**: part of this repository, under `reputation-attestor/`.
- **Contract**: add StudioNet contract address here when deployed.
- **Main workflow**: a subject registers their own evidence links (`register_profile`, self-only)
  -> the subject places their own `get_verification_code` string somewhere on each linked page
  (GitHub bio, X/Twitter bio, hackathon page) to prove they actually control it -> anyone
  permissionlessly triggers `verify_reputation`, which independently checks all three evidence
  sources in one bounded consensus round and updates whichever component was both fetchable and
  carried the proof code this round -> any protocol reads the composite score forever via
  `get_reputation`.

## The core design choice: reputation is read repeatedly, so a bad round must never destroy data

CoverMesh (this ecosystem's parametric-insurance contract) settles a claim exactly once -- a
cover either resolves or stays open, and `INSUFFICIENT_EVIDENCE` simply means "try again later."
A reputation score is different: it is read continuously by other protocols, potentially between
verification rounds, so a single transient failure (a GitHub API rate limit, a Twitter page that
didn't render this round) must never wipe out a subject's previously-verified standing.

This is why each of the three score components -- `github_score`, `twitter_score`,
`hackathon_score` -- tracks its **own** `_status` (`VERIFIED`/`UNVERIFIED`) and
`_last_verified_at` timestamp, and `verify_reputation` only overwrites a component when that
specific evidence source was actually fetchable in the current round. A GitHub outage during an
otherwise-successful verification leaves the subject's GitHub score exactly as it was, while their
Twitter and hackathon scores still get a fresh update in the same call.

## Why evidence-link registration is self-only, but verification is permissionless

Registering evidence links is a claim about the registrant's own identity -- only they should be
able to say "this is my GitHub, this is my X account, this is my hackathon history." Once
registered, however, *checking* that evidence against the public record is not a privileged
action: anyone (a consuming lending protocol that wants a fresh score before extending credit, a
community keeper bot) can trigger `verify_reputation`, and can be rewarded for doing so from a
permissionlessly-fundable `reward_pool` -- mirroring CoverMesh's "keeper reward paid from the
pool's own accounting" pattern, generalized here to a pool anyone (not just the pool that owns the
underlying asset) can top up.

## Architecture

- `contracts/ReputationAttestor.py` -- a single Intelligent Contract: self-sovereign profile
  registration with domain-restricted GitHub/Twitter URLs and a syntax-validated (but
  domain-open) hackathon URL, a single consensus round (`_consensus_verify`) that scores all three
  sources in one bounded call (three fetches, one `gl.nondet.exec_prompt`), and a minimal
  admin-only blacklist lever for clear abuse cases.
- `tests/direct/` -- direct-VM `gltest` tests covering registration and link validation,
  evidence updates, the non-destructive partial-failure verification path, cooldown and retry,
  keeper-reward accounting (funded and unfunded), out-of-enum activity-level downgrades, and the
  blacklist/unblacklist lever.

### Contract methods

| Method | Kind | Consensus round? | What it does |
| --- | --- | --- | --- |
| `register_profile(...)` | write, self-only | No | Registers a subject's own evidence links (one-time). |
| `update_evidence(...)` | write, self-only | No | Updates evidence links; never itself changes a score. Any component whose URL actually changes is immediately reset to UNVERIFIED (score/status/summary/timestamp cleared) rather than left stale. |
| `verify_reputation(subject)` | write, permissionless | **Yes -- once per attempt** | Runs the bounded consensus round. A component is only credited if it was BOTH fetchable AND its fetched text contains the subject's proof code (see `get_verification_code`) -- proving the subject actually controls that page, not just that the URL resolves. |
| `fund_rewards()` | payable write, permissionless | No | Tops up the keeper-reward pool. |
| `blacklist_profile` / `unblacklist_profile` | admin-only write | No | Emergency lever for clear abuse; zeroes/restores the readable score. |
| `get_reputation(subject)` | view | No | The reusable read primitive: composite score + per-component breakdown. |
| `get_verification_code(subject)` | view | No | The exact string (the subject's own address, lowercased) a subject must place on each evidence page before `verify_reputation` can credit that component. |
| `get_profile_links` / `is_registered` / `list_profiles` / `get_reward_pool` | view | No | Registry reads. |

## Scoring

- Each source is independently classified into an activity level of `NONE`/`LOW`/`MEDIUM`/`HIGH`
  by the consensus round, then mapped deterministically in the contract's own code to a
  component score out of that component's max (`GITHUB_SCORE_MAX=400`,
  `TWITTER_SCORE_MAX=300`, `HACKATHON_SCORE_MAX=300`; `total_score` out of 1000).
- Scores are always a **fresh, independent snapshot** each round, not a running or incremental
  total -- a subject cannot accumulate score simply by being verified repeatedly; only genuinely
  improved (or degraded) evidence changes the number.
- A blacklisted profile always reads `total_score: 0` regardless of its stored component scores,
  without the admin needing to zero out or delete any underlying data (which is preserved for
  potential future reinstatement via `unblacklist_profile`).

## Scope of this submission

This submission is **Contract + Tests**. A frontend (register your links, watch your score
populate, browse the registry) is a natural next step but is not included here.

## Honest limitations

- **Twitter/X evidence is frequently unscoreable.** Most profile pages require an authenticated
  session to show meaningful follower/engagement data to an unauthenticated renderer; a
  `twitter_score` of `NONE`/low is expected and common, not necessarily a sign of low real
  activity. This is documented rather than papered over.
- **Self-sovereign evidence means the subject picks what gets scored.** A subject who has a low-
  activity GitHub account under one username and a high-activity one under another will only be
  scored on whichever they register -- this is a feature (subjects genuinely control which public
  identity they're attesting to) but also means the score reflects the *chosen* evidence, not
  necessarily the subject's single most representative profile.
- **Single-admin blacklist is centralized.** The blacklist lever exists for clear, urgent abuse
  cases (e.g. evidence of large-scale sybil registration) and is deliberately minimal -- it can
  only blacklist or unblacklist, never edit a score directly. A future version could move this to
  a timelocked or DAO-voted process.
- **No sybil resistance beyond the evidence itself.** Nothing stops one person from registering
  many different addresses, each pointing at different real evidence links, to accumulate several
  separate reputation scores. This contract verifies that evidence is real, public, and actually
  controlled by the registering address (via the `get_verification_code` proof-of-control check);
  it does not and cannot prove a one-human-one-address property.
- **Redirects are not followed at the contract's own validation layer.** `_require_public_host`
  rejects local/private/link-local/reserved hosts and known URL-shortener/redirector domains at
  submission time, but it cannot see what a public host's server ultimately does with the
  request -- `gl.nondet.web.render` is an opaque non-deterministic call this contract's code never
  observes the response/redirect chain of. Blocking known redirector services closes the one
  practical vector this contract can control; a public host that itself later redirects
  server-side to a private target is outside what URL-string validation alone can prevent.
