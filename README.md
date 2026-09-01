# GenLayer Primitives Suite

Two independent, standalone GenLayer Intelligent Contracts, each a generic reusable primitive
in the same family as this ecosystem's proven parametric-insurance contract, **CoverMesh**.
Every contract below deliberately reuses CoverMesh's proven safety lessons (bounded
non-determinism, minimum independent-source enforcement in code, explicit prompt-injection
defenses, pre-mutation solvency checks) rather than reinventing them, while solving the one new
design problem specific to its own domain.

| Contract | Directory | What it is |
| --- | --- | --- |
| **ContentAuthenticityOracle** | [`content-authenticity-oracle/`](./content-authenticity-oracle) | A reusable content-authenticity verdict primitive: submit a URL, get a consensus judgment on whether it's AI-generated, plagiarized, or factually accurate. |
| **ReputationAttestor** | [`reputation-attestor/`](./reputation-attestor) | An on-chain reputation registry that periodically LLM-verifies off-chain evidence (GitHub, X/Twitter, hackathon results) into a permissionlessly-readable score -- a shared "proof of work" layer. |

Each subdirectory is a fully self-contained GenLayer project (its own `contracts/`, `tests/direct/`,
`gltest.config.yaml`, `README.md`, and `DECISION.md`) and can be deployed and tested independently
of the other.

## Repository layout

```
.
├── content-authenticity-oracle/
│   ├── contracts/ContentAuthenticityOracle.py
│   ├── tests/direct/{conftest.py,test_content_authenticity_oracle.py}
│   ├── gltest.config.yaml
│   ├── README.md
│   └── DECISION.md
└── reputation-attestor/
    ├── contracts/ReputationAttestor.py
    ├── tests/direct/{conftest.py,test_reputation_attestor.py}
    ├── gltest.config.yaml
    ├── README.md
    └── DECISION.md
```

## Running the tests

Each subdirectory follows the same `gltest` direct-VM testing convention already proven by
CoverMesh in this ecosystem. From inside a given subdirectory, with the GenLayer test toolchain
(`gltest`, the `genlayer` Python package, and their fixtures such as `direct_deploy`, `direct_vm`,
`direct_alice`/`direct_bob`/`direct_carol`/`direct_dave`) installed:

```bash
cd content-authenticity-oracle   # or reputation-attestor
pytest tests/direct -v
```

> **Note on this submission's environment**: the sandbox this suite was authored in has no
> network access, so the `genlayer`/`gltest` packages could not be installed here to execute the
> suites directly. Every test file mirrors CoverMesh's own already-proven `conftest.py` fixtures
> and mocking conventions (`direct_vm.mock_web`, `direct_vm.mock_llm`, `direct_vm.warp`,
> `direct_vm.clear_mocks`) line-for-line in structure, and every contract was syntax-checked
> (`python3 -m ast`) before being committed. Please run the suites in a GenLayer Studio /
> `gltest`-enabled environment before deploying.

## Design lineage

Both contracts share these lessons, each documented in more depth in its own `DECISION.md`:

1. **Query inputs never reshape evidence.** Keywords are restricted to a safe character set and
   percent-encoded before ever reaching a URL; asset ids are restricted to CoinGecko's own
   lowercase-hyphen format.
2. **A minimum independent-source count is a code rule, not a suggestion.** No contract here lets
   a consensus round resolve to a confident verdict on fewer independently-fetched sources than
   the contract itself requires.
3. **The model classifies or extracts; the contract's own code decides what matters.** Every
   numeric threshold comparison happens in plain deterministic Python after consensus, never
   inside the consensus round itself; every categorical verdict is constrained to a fixed enum and
   defensively downgraded if the model returns anything outside it.
4. **Fees and stakes are the concrete mechanism from the first line, never bolted on after the
   fact.** Where a contract moves value, it moves through its own accounting from its very first
   useful call.
5. **State reads never depend on a fresh consensus round.** Once verified, a result stays
   permissionlessly readable without re-triggering non-deterministic work.

## What's genuinely new in each contract, beyond reusing CoverMesh's lessons

- **ContentAuthenticityOracle** is the first contract in this family to fetch a caller-supplied
  URL as its primary evidence source, which CoverMesh's own design explicitly avoids. It solves
  this with strict URL-syntax validation (`_require_safe_url`) rather than avoidance, since
  avoidance isn't available for a contract whose entire purpose is judging one specific URL.
- **ReputationAttestor** is the first contract in this family where a failed verification round
  must never destroy previously-known-good state, because a reputation score (unlike an insurance
  claim) is read continuously by third parties between verification rounds. Each of its three
  score components tracks its own verified status and timestamp independently.

## Honest limitations (repository-wide)

- No contract in this suite includes a frontend; each is **Contract + Tests** only, matching the
  scope of the CoverMesh submission this suite builds on.
- No contract address has been deployed to StudioNet yet -- add addresses to each subdirectory's
  own README once deployed.
- The test suites were authored and syntax-checked but not executed against a live `gltest`
  runner in this environment (see "Running the tests" above).
