# ReputationAttestor Decision Record

## The product

A self-sovereign evidence registry (a subject registers their own GitHub, X/Twitter, and
hackathon-results links) paired with a permissionless verification round that independently
scores each source and writes a composite, always-fresh reputation score other protocols can read
without running any evidence pipeline of their own.

## Counterfactual: why not just let each consuming protocol score reputation itself

Every lending protocol, DAO, or grant program that wants a signal like "has this address done
real public work" today either builds its own off-chain scoring service (opaque, not
independently checkable, a separate trust assumption per consumer) or ignores the signal
entirely. A single, consensus-verified, permissionlessly-read registry means the same evidence is
scored once, by the same rules, checkable by anyone -- exactly the "reusable infrastructure vs.
one more single-purpose contract" argument CoverMesh already made for insurance, applied here to
reputation.

## Why verification is non-destructive per component, unlike CoverMesh's claim settlement

CoverMesh's `check_claim` either resolves a cover to a final, permanent verdict or leaves it
retriable -- there is no partial state, because a cover is a single yes/no financial question with
one deadline. A reputation score is read continuously between verification rounds by third
parties who have no visibility into whether a round is "in progress," so the wrong failure mode
here is different: if a single flaky fetch (a rate-limited GitHub API call, for instance) zeroed
out a subject's entire score, every consuming protocol reading that score in the interim would see
a false collapse in reputation that has nothing to do with the subject's actual evidence. The fix
is to track each of the three components' own verified status and timestamp, and to leave a
component's prior state completely untouched only when its evidence genuinely could not be
fetched this round. This is a deliberate generalization of CoverMesh's `INSUFFICIENT_EVIDENCE`
idea (never resolve on missing evidence) down to per-field granularity, rather than an
all-or-nothing round -- but "missing evidence" has to mean the fetch itself failed, not merely
that the fetched page no longer says what it used to (see the fourth-round hardening below, where
conflating those two was a real bug).

## Why registration is self-only but verification is permissionless

A profile's evidence *links* are a claim only the subject themselves should be able to make --
registering someone else's GitHub URL against your own address would let you steal their public
work as evidence for your own reputation. But once those links are on record, checking them
against the real, public state of GitHub/X/a hackathon page is not a privileged act -- it is
exactly the kind of permissionless, keeper-incentivized action CoverMesh's `check_claim` already
proved out for insurance claims. Reusing that shape here means any consuming protocol that wants a
subject's score refreshed right before making a decision (e.g. before extending undercollateralized
credit) can simply pay to trigger it themselves, rather than waiting on the subject's own
initiative.

## Why the reward pool is a separate, community-fundable pool instead of reusing CoverMesh's NAV pool

CoverMesh's keeper reward is paid from the same NAV pool that backs real financial liability,
because in CoverMesh the reward is a genuine, small operating cost the insurance pool bears as
part of paying claims. ReputationAttestor has no equivalent pool of at-risk capital -- there is
no liability to underwrite, only a public good (fresh reputation data) to fund. Modeling the
reward pool as a simple, permissionlessly-fundable balance (rather than forcing a CoverMesh-style
LP/NAV structure onto a contract with no actual insurance economics) keeps the incentive real
without inventing financial machinery this contract doesn't need. Verification still succeeds with
an empty pool -- the reward is a bonus for keepers, never a requirement for the registry to
function.

## Why activity levels, not raw follower/star counts, are the scored unit

Asking the model to extract a raw follower count or star count and comparing it against a
numeric threshold (the CoverMesh WEATHER/PRICE_THRESHOLD pattern) was considered and rejected for
this contract's three sources, because none of them expose a single canonical numeric signal the
way Open-Meteo or CoinGecko do -- GitHub's own activity signal is a mix of repo count, followers,
and account age; Twitter's rendered text rarely exposes a reliable number at all; a hackathon page
might report placements, not counts. Constraining the model to a four-level ordinal judgment
(`NONE`/`LOW`/`MEDIUM`/`HIGH`), validated against that fixed enum in code and mapped
deterministically to a score, keeps the categorical-classification discipline this ecosystem
already uses for genuinely non-numeric judgments (CoverMesh's own NEWS_EVENT adapter), rather than
forcing a false numeric precision onto evidence that doesn't actually support it.

## Why the blacklist lever is minimal and admin-gated rather than absent or elaborate

A registry that is otherwise fully permissionless still needs *some* emergency response to
clear, urgent abuse (for example, a large batch of registrations that turn out to be tied to a
single sybil operator, discovered off-chain). Building a full on-chain governance/dispute process
for this first version would be substantial additional surface area for a problem that, in
practice, needs a fast circuit breaker more than a deliberative process. The chosen middle ground
-- a single admin who can only toggle a binary blacklist flag (never edit a score directly, never
delete underlying evidence) -- bounds the admin's power to "hide this score from readers" rather
than "rewrite this subject's reputation," and is explicitly documented as a centralization
trade-off future versions should address with a timelocked or DAO-voted process.

## Post-review hardening: proof-of-control, link-change laundering, and fetch-target safety

Three concrete gaps were found and closed after initial review, all addressed in code rather than
by narrowing the contract's scope:

**Profile impersonation.** Registration only required a link to be on the right domain, never
that the registrant actually controlled the linked page. Anyone could register a real third
party's public GitHub/X/hackathon URL against their own address and inherit that person's
evidence as their own score. The fix is a deterministic proof-of-control check enforced in code,
never left to the model: `get_verification_code(subject)` returns the subject's own registered
address, lowercased, and `verify_reputation` now only credits a component when that literal
string is found in that component's fetched text (checked in plain Python inside the leader
closure, and required by the comparative-equivalence principle text so validators agree on it).
A component is "available" this round only when it was BOTH fetchable AND carries the proof
code; missing either leaves it exactly as untouched as a fetch failure always has.

**Link-change score laundering.** `update_evidence` used to swap links without touching any
score, on the theory that a fresh score always requires a new `verify_reputation` round. In
practice this meant a subject could get verified once against strong evidence, then repoint the
link at something else entirely while every reader of `get_reputation` kept seeing the old
score, status, and summary attached to the new URL for as long as nobody happened to re-trigger
verification. `update_evidence` now compares each incoming URL against the stored one and, for
any component that actually changed, immediately clears that component's score, status, summary,
and last-verified timestamp back to UNVERIFIED in the same call. Components whose URL is
unchanged are left alone.

**Non-public and redirector fetch targets.** `hackathon_url` is intentionally domain-open (see
above), which made it the one link in this contract that could point a `gl.nondet.web.render`
call at an internal address (a cloud metadata endpoint, a private-network service) or at a
URL-shortener whose real destination isn't visible at submission time. `_require_safe_url` now
routes every URL (github/twitter/hackathon alike) through `_require_public_host`, which rejects
localhost/private/link-local/reserved IPv4 and IPv6 literals -- including common decimal/hex/octal
obfuscations of them -- plus a fixed list of known URL-shortener/redirector hosts. This closes the
literal-SSRF surface at the contract's own validation layer.

## Third-round hardening: the denylist alone was not enough

A subsequent review correctly identified that the submission-time denylist above, however
thorough, cannot close two real gaps: an *ordinary*, non-denylisted hostname can still resolve, at
fetch time, to a private or cloud-metadata address (the classic DNS-based SSRF shape), and a
syntactically public, non-denylisted URL can still answer with an HTTP redirect to one. Both are
facts about live network behavior, not about the URL string itself, so no amount of additional
denylisting at `register_profile`/`update_evidence` time could ever close them -- they can only be
discovered by actually resolving or requesting the URL, which is a non-deterministic operation,
and non-deterministic operations can only run inside a consensus-gated block, never on the
deterministic write path those two methods run on. The fix could not be "check harder at
registration time," it had to be "check for real, at fetch time, inside consensus" -- exactly the
same architectural correction applied to ContentAuthenticityOracle's `content_url`.

The fix adds two checks inside `_consensus_verify`'s `leader()`, run immediately before
`twitter_url`/`hackathon_url` are ever rendered (`github_url` is exempt, since the contract only
ever fetches a fixed `api.github.com` host it builds itself from the extracted username, never a
caller-influenced host):

- **`_host_resolves_public`** performs a real DNS-over-HTTPS lookup (via a fixed, trusted
  resolver, `dns.google/resolve`) for both A and AAAA records, and validates every returned
  address against the same private/reserved-range logic `_require_public_host` already used for
  literal IPs.
- **`_no_unresolved_redirect`** issues a `gl.nondet.web.request` and inspects `response.status_code`
  before ever calling `.render()` on the same URL, refusing any response in the 300-399 range.

Both checks fail closed to `"[FETCH_UNAVAILABLE]"`, which the existing per-component
non-destructive verification logic already treats as "leave this component's prior score
untouched this round" -- no new failure mode, just an evidence path that should never have been
trusted in the first place now correctly recognized as untrustworthy.

**What is still not closed, stated plainly:** if the GenVM web primitives internally follow HTTP
redirects before ever returning a response to contract code, `_no_unresolved_redirect` never
observes anything to refuse, and a host that passed both checks here could still ultimately serve
content fetched from a redirect target this contract never validated. This is the edge of what is
achievable without a platform capability this contract cannot build for itself -- either disabling
automatic redirect-following in the web primitives, or exposing the resolved IP/redirect chain to
contract code. Until such a capability exists, this is the most complete mitigation available at
the Intelligent Contract layer, documented here rather than silently assumed to be complete.

## Fourth-round hardening: fetched-but-unproven was wrongly treated the same as unreachable

A subsequent review correctly identified that the non-destructive verification path described
above -- built to protect subjects from a transient fetch failure wiping out their score -- had
been applied one step too broadly. The original code checked a single `*_available` boolean per
component (fetched **and** proof-code-bearing) and left the component untouched whenever it was
`False`, for *either* reason: the page could not be fetched at all, or the page fetched fine but
no longer contained the subject's proof code. Those are not the same fact. A page that is real,
reachable, and simply no longer endorses this address is not "missing evidence" the way an
API outage is -- it is a subject who once proved control and then removed that proof, and the
non-destructive design's entire justification (don't let a transient hiccup destroy real,
still-true evidence) does not apply to it: the evidence didn't hiccup, it changed. Treating the
two the same meant a subject could verify once with a genuine proof code, then quietly delete it,
and keep the resulting score indefinitely -- exactly the kind of stale-but-never-revalidated claim
a reusable, continuously-read primitive cannot afford to make.

The fix splits the single boolean into two, both already computed deterministically in
`leader()` and both validated by consensus like any other evidence-derived fact: `*_fetched`
(did the render succeed) and `*_available` (fetched **and** proof-code-bearing, as before).
`verify_reputation` now branches on both: `available` writes a fresh VERIFIED score exactly as
before; `fetched` but not `available` **clears** that component's score to zero and its status to
`UNVERIFIED`, with the timestamp updated to record that a real check ran and found nothing; only
truly unreachable (`not fetched`) leaves the component untouched. This preserves the original
non-destructive guarantee for the case it was actually meant to cover (transient failures) while
closing the gap it accidentally created (evidence that changed).

**Why this couldn't be fixed by simply always overwriting on any `False`.** Reverting to
"overwrite on any non-available outcome" would restore the destructive behavior the non-
destructive design exists to prevent: a single rate-limited GitHub API call would zero out a
subject's real, still-valid score. The fix had to add a third state, not remove the second one.

## Fourth-round hardening: keeper rewards must be earned, not merely triggered

The same review identified a second issue with the same root cause: `verify_reputation` paid its
fixed keeper reward on every call with sufficient pool funds, regardless of what the round
actually found. This is reasonable in isolation -- a legitimate profile might genuinely come back
partially or fully unreachable sometimes, and the keeper still did real work fetching it -- but
combined with the bug above, it created a profitable Sybil pattern: register any number of
profiles pointing at real, fetchable pages that simply never carry a proof code (no registration-
time check can distinguish this from a legitimate subject who hasn't added their code yet), then
repeatedly call `verify_reputation` on them. Each call would report a plausible-looking round
(pages fetched, activity levels estimated) and still collect the keeper reward, even though no
component could ever possibly become `VERIFIED` -- a free, repeatable drain on `reward_pool`
funded by whoever tops it up in good faith.

The fix ties the reward to outcome, not to effort: `verify_reputation` now tracks whether *any*
component achieved a genuine `available` outcome this round, and only pays the keeper reward if
so. A round that only clears stale components or leaves unreachable ones untouched -- the two
outcomes that are, by construction, never accompanied by a real proof-code match -- earns
nothing. This does not require every component to verify, only at least one, so a legitimate
profile with one flaky source among three genuine ones still rewards the keeper who checked it;
it only closes the reward for rounds that could not possibly have produced real evidence.
