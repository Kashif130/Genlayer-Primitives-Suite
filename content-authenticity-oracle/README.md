# ContentAuthenticityOracle

A generic, reusable content-authenticity verdict primitive: submit an article, tweet, or image
URL plus corroboration keywords, pay a small fee, and anyone can permissionlessly trigger a
GenLayer consensus round that cross-checks the content against independent sources and returns
up to three verdicts -- **is it AI-generated**, **is it plagiarized**, and **is it factually
accurate**. Every result is stored on-chain behind plain, permissionless view methods, so content
moderation systems, journalism DAOs, or any other protocol can consume verdicts without running
their own LLM integration or their own evidence-fetching pipeline.

## Reviewer summary

- **Live app**: not included in this submission -- see "Scope" below.
- **Source**: part of this repository, under `content-authenticity-oracle/`.
- **Contract**: add StudioNet contract address here when deployed.
- **Main workflow**: a caller opens an assessment (`request_assessment`) against a content URL,
  paying a fixed per-content-type fee -> anyone permissionlessly triggers `run_assessment`, which
  fetches the content plus (when a check needs it) two independent corroboration sources, and
  runs one bounded consensus round -> the assessment's verdicts and rationale become readable
  forever via `get_assessment` / `is_flagged`.

## Why a single caller-supplied URL is safe here, when CoverMesh explicitly avoids that

This contract reuses this ecosystem's established safety lessons (bounded non-determinism,
per-check minimum independent-source counts enforced in code, explicit prompt-injection defenses
telling the model to treat every fetched page as untrusted text) but faces a problem the
predecessor parametric-insurance contract (CoverMesh) deliberately designed around: CoverMesh's
own evidence sources are never a caller-supplied URL, specifically to avoid turning a claims
engine into an open fetch proxy. This contract's entire purpose is judging one *specific*
caller-supplied URL, so that avoidance isn't available.

Instead, the caller-supplied surface is bounded a different way:

- `_require_safe_url` enforces a strict http(s)-only, sane-length, whitespace/control-character-
  free, credentials-free URL shape -- closing the classic syntax-level SSRF and query-injection
  tricks.
- Exactly **one** caller-chosen URL is fetched per assessment, never an arbitrary number.
- The two *corroboration* sources (Google News, Wikipedia) remain contract-fixed and driven only
  by caller-supplied, character-restricted keywords -- exactly the model CoverMesh already
  proved safe -- so the open-fetch-proxy exposure never grows past that one validated URL.

## Why the model only classifies, and the contract only aggregates

Unlike CoverMesh's numeric adapters (where the model extracts a number and the contract's own
code does the threshold comparison), every check here is inherently categorical -- there is no
deterministic formula for "is this AI-generated." The model's classification is therefore the
verdict itself, but every verdict is still constrained to a fixed enum
(`LIKELY_AI`/`LIKELY_HUMAN`/`UNCERTAIN`, etc.), and the contract downgrades any out-of-enum output
defensively to the uncertain value rather than trusting it. The contract's own code still owns
the parts that matter for safety: minimum-source enforcement per check, whether an assessment is
resolved vs. insufficient, and fee/keeper-reward accounting.

## Architecture

- `contracts/ContentAuthenticityOracle.py` -- a single Intelligent Contract: an admin-gated
  content-type registry (fee and minimum-source count per `ARTICLE`/`TWEET`/`IMAGE`, seeded at
  deploy time), permissionless assessment requests, and a single consensus round
  (`_consensus_assessment`) combining every requested check into one bounded call (one content
  fetch, up to two corroboration fetches, one `gl.nondet.exec_prompt`).
- `tests/direct/` -- direct-VM `gltest` tests covering registry configuration, URL/keyword/check
  validation, every verdict path (resolved, flagged, insufficient, content-unavailable,
  out-of-enum downgrade), cooldown and retry, the permissionless `finalize_unresolved` escape
  valve, and treasury accounting.

### Contract methods

| Method | Kind | Consensus round? | What it does |
| --- | --- | --- | --- |
| `set_content_type_config(...)` | admin-only write | No | Configures fee and minimum-source count for a content type. |
| `withdraw_treasury(amount)` | admin-only write | No | Withdraws accumulated fee revenue not paid out as keeper rewards. |
| `request_assessment(...)` | payable write | No | Opens an assessment against a content URL, paying the fixed fee. |
| `run_assessment(id)` | write, permissionless | **Yes -- once per attempt** | Runs the bounded consensus round and stores verdicts. |
| `finalize_unresolved(id)` | write, permissionless | No | Closes out a permanently-unresolvable assessment as `FAILED` after a grace period. |
| `get_assessment` / `list_assessments` | view | No | Read a single assessment or page through all of them. |
| `is_flagged(id)` | view | No | Convenience boolean for moderation consumers. |
| `get_content_type_config` / `get_treasury_balance` | view | No | Registry/treasury reads. |

## Economics

- **Fee-funded keeper reward**: `request_assessment`'s fee is not spent until a consensus round
  actually runs. `run_assessment` splits it: a fixed `KEEPER_REWARD_WEI` to whoever triggered the
  round (paid whether the round resolves or not, since the fetch-and-classify work happened
  either way), the remainder to `treasury`.
- **Non-refundable, service-fee model**: like a real information request, the fee is consumed by
  the act of running the check, not refunded if the verdict comes back uncertain -- retries reuse
  the same prepaid fee up to the cooldown, only splitting a reward once a round actually runs.

## Scope of this submission

This submission is **Contract + Tests**. A frontend (submit a URL, watch an assessment resolve,
browse flagged content) is a natural next step but is not included here.

## Honest limitations

- **Content-type registration is admin-gated.** The fee and minimum-source count bound the
  non-determinism budget and the spam-resistance economics, so they are protocol-safety
  parameters, not something a requester should set for themselves. A future version could move
  this to a timelocked or governance-voted process.
- **IMAGE content type has no true visual analysis.** `gl.nondet.web.render(..., mode="text")`
  extracts text, not pixels -- an `IMAGE` assessment can only reason about a page's surrounding
  text (captions, alt text, article context around the image), not the image content itself. This
  is documented rather than silently overstated; a future version could add a vision-capable
  extraction path if the platform exposes one.
- **No dispute or appeals process.** A requester who disagrees with a resolved verdict can only
  request a brand-new assessment (a new fee, a new consensus round); there is no on-chain
  challenge mechanism that re-weighs the same assessment.
- **Plagiarism detection depends on the corroboration sources actually surfacing the original.**
  Google News and Wikipedia are reasonable, safe, keyless corroboration sources, but a plagiarized
  passage from a source neither indexes will correctly resolve to `UNCERTAIN` rather than a false
  `LIKELY_ORIGINAL` -- but it also means genuine plagiarism from an obscure source may go
  undetected. This is a real recall limitation of using only fixed, safe evidence sources.
- **`content_url` host validation cannot see server-side redirects.** `_require_safe_url` rejects
  local/private/link-local/reserved hosts and known URL-shortener/redirector domains at submission
  time (see `_require_public_host`), but `gl.nondet.web.render` is an opaque non-deterministic
  call this contract's code never observes the response/redirect chain of -- a public host that
  itself later redirects server-side to a private target is outside what URL-string validation
  alone can prevent. Blocking known redirector services closes the one practical vector this
  contract can control at its own layer.
