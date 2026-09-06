# ContentAuthenticityOracle Decision Record

## The product

A permissionless verdict primitive. Anyone submits a content URL, a content type, corroboration
keywords, and 1-3 requested checks (`AI_GENERATED`, `PLAGIARIZED`, `FACTUALLY_ACCURATE`), paying a
fixed per-content-type fee. Anyone may then trigger a single bounded GenLayer consensus round that
fetches the content plus (only when needed) two independent corroboration sources, and returns a
constrained-enum verdict per requested check. The result is stored forever behind plain view
methods -- any consuming protocol (a moderation queue, a journalism DAO, a social client) reads it
exactly like reading any other on-chain state, no LLM integration of its own required.

## Counterfactual: why this needs to exist as shared infrastructure

Every project that wants "is this content trustworthy" today either builds its own centralized
classifier (a single point of trust and failure) or has no such check at all. A shared,
on-chain, consensus-verified primitive means many consumers can rely on the same verdict, computed
once, checkable by anyone, rather than each reimplementing (and each independently trusting) their
own opaque scoring service.

## Why a caller-supplied URL is safe here, unlike CoverMesh's evidence model

CoverMesh -- the parametric-insurance contract this ecosystem already proved out -- explicitly
never fetches a caller-supplied URL as evidence, reasoning that a consensus contract willing to
fetch whatever URL a caller supplies is an unbounded, abusable fetch proxy, not a bounded,
auditable engine. That reasoning is correct for CoverMesh, where evidence is incidental to a
peril question the caller does not need to point at a specific page for.

This contract cannot avoid a caller-supplied URL, because judging a *specific* piece of content is
the entire product. The design response is to bound the caller-supplied surface as tightly as
possible instead of avoiding it:

1. Exactly one caller-chosen URL per assessment (never a list, never a caller-suppled corroboration
   URL -- corroboration sources stay contract-fixed and keyword-driven).
2. `_require_safe_url` enforces http(s)-only, a sane length ceiling, no whitespace/control
   characters, and no embedded userinfo -- closing the classic string-level SSRF and header/query
   injection techniques.
3. The fetch result is always labelled explicit untrusted evidence text in the prompt, with an
   explicit instruction not to follow instruction-like phrasing found inside it -- the same
   defense CoverMesh already uses for its own (contract-fixed) evidence sources, applied here to
   caller-influenced evidence too.

This is a narrower, but real, safety boundary: it does not make an arbitrary caller-supplied URL
as safe as a contract-fixed one, but it closes the mechanical attack classes that matter most for
a public IC endpoint, while still letting the contract do the one thing it exists to do.

## Why the model only extracts categorical verdicts, never a raw payout decision

Every predecessor contract in this series that reached a categorical decision constrained the
model's output to a fixed enum and validated it in code, never trusting free-text output directly.
This contract keeps that discipline for all three checks, even though (unlike CoverMesh's numeric
adapters) there is no further deterministic comparison step possible here -- "is this
AI-generated" has no formula. The contract's own code still does everything it *can* do
deterministically: enforcing the minimum-source rule before a verdict may resolve, defensively
downgrading any output outside the fixed enum to the uncertain value, and deciding whether an
assessment is `RESOLVED` vs. `INSUFFICIENT_EVIDENCE` based on whether *any* requested check
actually resolved.

## Why fee accounting is deferred to the consensus round, not charged at request time

A steward-reviewed lesson elsewhere in this series is that settlement should be the concrete
mechanism from the start, not retrofitted. Here, the fee is collected at `request_assessment` time
but its *fate* -- keeper reward vs. treasury -- is only decided inside `run_assessment`, because
that is when real off-chain work (fetching, classifying) actually happens. This avoids a subtle
unfairness: if the fee were immediately booked as pure treasury revenue at request time, an
assessment that nobody ever bothers to run would sit as unearned revenue forever; deferring the
split ties revenue recognition to work actually performed, exactly once per attempt.

## Why `run_assessment` and `finalize_unresolved` are both permissionless

Neither step should require the original requester's continued participation -- another consumer
of the eventual verdict (a moderation bot, an indexer) has just as much reason to trigger the
round, and gets paid the keeper reward for doing so. `finalize_unresolved` mirrors CoverMesh's
`expire_unclaimed_cover` escape valve for the same reason: a permanently-unreachable content URL
(a deleted tweet, a 404'd article) must not be able to sit as an open, retriable request forever;
after a grace window, anyone can close it out as a terminal `FAILED` status.

## Why IMAGE content type still uses text-mode rendering, documented as a limitation

`gl.nondet.web.render` in this GenVM environment only extracts text, not pixel data. Rather than
silently mislabeling an `IMAGE` assessment as doing real visual analysis, the contract treats
`IMAGE` as a real, seeded content type (with its own fee and minimum-source configuration) but the
README documents plainly that an `IMAGE` verdict is grounded in the page's surrounding text
context, not the image itself -- an honest limitation rather than an overstated capability, in the
same spirit as CoverMesh's own "Honest limitations" section.

## Post-review hardening: non-public and redirector fetch-target safety

`content_url` is this contract's one caller-supplied fetch target by design (see above), so it
was the one place a submitter could point `gl.nondet.web.render` at an internal address (a cloud
metadata endpoint, a private-network service) or at a URL-shortener whose real destination isn't
visible at submission time. `_require_safe_url` now additionally routes the parsed host through
`_require_public_host`, which rejects localhost/private/link-local/reserved IPv4 and IPv6
literals -- including common decimal/hex/octal obfuscations of them -- plus a fixed list of known
URL-shortener/redirector hosts. This closes the literal-SSRF surface at the contract's own
validation layer.

## Second-round hardening: the denylist alone was not enough

A subsequent review correctly identified that the submission-time denylist above, however
thorough, cannot close two real gaps: an *ordinary*, non-denylisted hostname can still resolve, at
fetch time, to a private or cloud-metadata address (the classic DNS-based SSRF shape), and a
syntactically public, non-denylisted URL can still answer with an HTTP redirect to one. Both are
facts about live network behavior, not about the URL string itself, so no amount of additional
denylisting at `request_assessment` time could ever close them -- they can only be discovered by
actually resolving or requesting the URL, which is a non-deterministic operation, and non-
deterministic operations can only run inside a consensus-gated block (a `leader()` function passed
to `gl.eq_principle.*`), never on the deterministic write path `request_assessment` runs on. This
is a real architectural constraint, not a design preference: the fix could not be "check harder at
submission time," it had to be "check for real, at fetch time, inside consensus."

The fix adds two checks inside `_consensus_assessment`'s `leader()`, run immediately before
`content_url` is ever rendered:

- **`_host_resolves_public`** performs a real DNS-over-HTTPS lookup (via a fixed, trusted
  resolver, `dns.google/resolve`) for both A and AAAA records, and validates every returned
  address against the same private/reserved-range logic `_require_public_host` already used for
  literal IPs. This directly closes the "ordinary hostname resolves to a private/metadata
  address" gap: the check now reflects where the host *actually* resolves at the moment of
  fetching, not just what its string looks like.
- **`_no_unresolved_redirect`** issues a `gl.nondet.web.request` and inspects `response.status_code`
  before ever calling `.render()` on the same URL, refusing any response in the 300-399 range
  rather than silently trusting whatever a `.render()` call might return for a URL that redirects.

Both checks fail closed: a resolution failure, an empty or unrecognized DNS answer, or an observed
redirect status all downgrade `content_page` to `"[FETCH_UNAVAILABLE]"`, which the existing
consensus logic already treats as missing evidence -- no new failure mode was introduced, this
only closes an evidence path that should never have been trusted in the first place.

**What is still not closed, stated plainly:** if the GenVM web primitives internally follow HTTP
redirects before ever returning a response to contract code -- rather than surfacing the
intermediate 3xx the way `gl.nondet.web.request`'s documented `status_code` field implies they
might -- then `_no_unresolved_redirect` never observes anything to refuse, and a host that passed
both checks here could still ultimately serve content fetched from a redirect target this contract
never validated. This is not a gap this contract chose to leave open; it is the edge of what is
achievable without a platform capability this contract cannot build for itself -- either disabling
automatic redirect-following in the web primitives, or exposing the resolved IP/redirect chain to
contract code. Until such a capability exists, this is the most complete mitigation available at
the Intelligent Contract layer, and is documented here rather than silently assumed to be complete.
