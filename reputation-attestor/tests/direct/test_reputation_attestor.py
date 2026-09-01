import pytest

from conftest import warp_to

GEN = 10**18

NOW = "2099-01-01T00:00:00Z"
AFTER_COOLDOWN = "2099-01-01T12:00:01Z"  # 12h cooldown

VALID_GITHUB = "https://github.com/octocat"
VALID_TWITTER = "https://x.com/octocat"
VALID_HACKATHON = "https://devpost.com/octocat"


def _code(subject) -> str:
    return str(subject).lower()


def mock_full(direct_vm, subject, gh="HIGH", tw="MEDIUM", hk="LOW"):
    """Mocks all three sources as fetchable AND carrying `subject`'s proof code -- the shape a
    genuine, subject-controlled set of evidence pages would take."""
    code = _code(subject)
    direct_vm.clear_mocks()
    direct_vm.mock_web(
        r".*api\.github\.com/users/.*",
        {"status": 200, "body": f'{{"public_repos":40,"followers":300,"bio":"proof:{code}"}}'},
    )
    direct_vm.mock_web(
        r"https://x\.com/.*",
        {"status": 200, "body": f"profile page text with follower count. verification code: {code}"},
    )
    direct_vm.mock_web(
        r"https://devpost\.com/.*",
        {"status": 200, "body": f"won 1st place at ETHGlobal. verification code: {code}"},
    )
    direct_vm.mock_llm(
        r".*scoring three independent pieces of public evidence.*",
        f'{{"github_activity_level":"{gh}","github_summary":"active github",'
        f'"twitter_activity_level":"{tw}","twitter_summary":"moderate twitter",'
        f'"hackathon_activity_level":"{hk}","hackathon_summary":"one hackathon win"}}',
    )


def mock_full_no_proof(direct_vm, gh="HIGH", tw="MEDIUM", hk="LOW"):
    """Mocks all three sources as fetchable but carrying NO subject's proof code at all --
    real-looking, genuinely-fetchable evidence pages that nonetheless are not bound to whoever
    is registering them. This is exactly the shape of a profile-impersonation attempt: the pages
    are real and fetchable, but nothing on them ties them to the registrant's address."""
    direct_vm.clear_mocks()
    direct_vm.mock_web(
        r".*api\.github\.com/users/.*",
        {"status": 200, "body": '{"public_repos":400,"followers":9000}'},
    )
    direct_vm.mock_web(
        r"https://x\.com/.*",
        {"status": 200, "body": "a very active profile with huge follower count"},
    )
    direct_vm.mock_web(
        r"https://devpost\.com/.*",
        {"status": 200, "body": "won grand prize at every hackathon this year"},
    )
    direct_vm.mock_llm(
        r".*scoring three independent pieces of public evidence.*",
        f'{{"github_activity_level":"{gh}","github_summary":"wildly active github",'
        f'"twitter_activity_level":"{tw}","twitter_summary":"wildly active twitter",'
        f'"hackathon_activity_level":"{hk}","hackathon_summary":"many hackathon wins"}}',
    )


def mock_github_down(direct_vm, subject, tw="LOW", hk="LOW"):
    code = _code(subject)
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*api\.github\.com/users/.*", {"status": 500, "body": ""})
    direct_vm.mock_web(
        r"https://x\.com/.*", {"status": 200, "body": f"profile page text. verification code: {code}"}
    )
    direct_vm.mock_web(
        r"https://devpost\.com/.*",
        {"status": 200, "body": f"one small hackathon mention. verification code: {code}"},
    )
    direct_vm.mock_llm(
        r".*scoring three independent pieces of public evidence.*",
        f'{{"github_activity_level":"NONE","github_summary":"",'
        f'"twitter_activity_level":"{tw}","twitter_summary":"low twitter",'
        f'"hackathon_activity_level":"{hk}","hackathon_summary":"small mention"}}',
    )


def register(contract, direct_vm, subject, github=VALID_GITHUB, twitter=VALID_TWITTER, hackathon=VALID_HACKATHON):
    direct_vm.sender = subject
    contract.register_profile(github, twitter, hackathon)


# --- registration ---

def test_register_profile(contract, direct_vm, direct_bob):
    warp_to(direct_vm, NOW)
    register(contract, direct_vm, direct_bob)
    assert contract.is_registered(direct_bob) is True
    links = contract.get_profile_links(direct_bob)
    assert links["github_url"] == VALID_GITHUB
    assert links["registered_at"] == NOW


def test_register_twice_fails(contract, direct_vm, direct_bob):
    register(contract, direct_vm, direct_bob)
    with pytest.raises(Exception):
        register(contract, direct_vm, direct_bob)


def test_register_rejects_non_github_domain(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        register(contract, direct_vm, direct_bob, github="https://gitlab.com/octocat")


def test_register_rejects_non_twitter_domain(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        register(contract, direct_vm, direct_bob, twitter="https://mastodon.social/@octocat")


def test_register_accepts_www_prefixed_domain(contract, direct_vm, direct_bob):
    register(contract, direct_vm, direct_bob, github="https://www.github.com/octocat")
    assert contract.is_registered(direct_bob) is True


def test_register_rejects_bad_hackathon_url_scheme(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        register(contract, direct_vm, direct_bob, hackathon="ftp://devpost.com/octocat")


def test_register_rejects_hackathon_url_with_credentials(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        register(contract, direct_vm, direct_bob, hackathon="https://user:pass@devpost.com/x")


def test_get_reputation_before_verification_is_zero(contract, direct_vm, direct_bob):
    register(contract, direct_vm, direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["total_score"] == 0
    assert rep["github_status"] == "UNVERIFIED"


def test_get_reputation_unregistered_raises(contract, direct_bob):
    with pytest.raises(Exception):
        contract.get_reputation(direct_bob)


def test_get_verification_code_matches_address(contract, direct_vm, direct_bob):
    register(contract, direct_vm, direct_bob)
    assert contract.get_verification_code(direct_bob) == str(direct_bob).lower()


def test_get_verification_code_requires_registration(contract, direct_bob):
    with pytest.raises(Exception):
        contract.get_verification_code(direct_bob)


# --- update_evidence ---

def test_update_evidence_unchanged_links_keep_score(contract, direct_vm, direct_bob, direct_carol):
    """Re-submitting the SAME links must not clear a component's score -- only an actual change
    should."""
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    rep_before = contract.get_reputation(direct_bob)

    direct_vm.sender = direct_bob
    contract.update_evidence(VALID_GITHUB, VALID_TWITTER, VALID_HACKATHON)
    rep_after = contract.get_reputation(direct_bob)
    assert rep_after["total_score"] == rep_before["total_score"]
    assert rep_after["github_status"] == "VERIFIED"
    assert rep_after["twitter_status"] == "VERIFIED"
    assert rep_after["hackathon_status"] == "VERIFIED"


def test_update_evidence_requires_registration(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.update_evidence(VALID_GITHUB, VALID_TWITTER, VALID_HACKATHON)


# --- link-change score laundering guard ---

def test_update_evidence_changing_one_link_clears_only_that_component(
    contract, direct_vm, direct_bob, direct_carol
):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob, gh="HIGH", tw="MEDIUM", hk="LOW")
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    rep_before = contract.get_reputation(direct_bob)
    assert rep_before["hackathon_status"] == "VERIFIED"
    assert rep_before["hackathon_score"] == 100

    # Swap ONLY the hackathon link -- a subject could otherwise keep displaying their old
    # hackathon score/summary/status while quietly pointing the link at something unrelated.
    direct_vm.sender = direct_bob
    contract.update_evidence(VALID_GITHUB, VALID_TWITTER, "https://devpost.com/newpage")

    rep_after = contract.get_reputation(direct_bob)
    # The changed component is wiped back to its initial UNVERIFIED state immediately.
    assert rep_after["hackathon_status"] == "UNVERIFIED"
    assert rep_after["hackathon_score"] == 0
    assert rep_after["hackathon_summary"] == ""
    assert rep_after["hackathon_last_verified_at"] == ""
    # The unchanged components are untouched.
    assert rep_after["github_status"] == "VERIFIED"
    assert rep_after["github_score"] == rep_before["github_score"]
    assert rep_after["twitter_status"] == "VERIFIED"
    assert rep_after["twitter_score"] == rep_before["twitter_score"]
    # Total score drops by exactly the laundered component.
    assert rep_after["total_score"] == rep_before["total_score"] - 100
    assert contract.get_profile_links(direct_bob)["hackathon_url"] == "https://devpost.com/newpage"


def test_update_evidence_changing_all_three_links_clears_all_three(
    contract, direct_vm, direct_bob, direct_carol
):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    assert contract.get_reputation(direct_bob)["total_score"] > 0

    direct_vm.sender = direct_bob
    contract.update_evidence(
        "https://github.com/someoneelse", "https://x.com/someoneelse", "https://devpost.com/someoneelse"
    )
    rep = contract.get_reputation(direct_bob)
    assert rep["total_score"] == 0
    assert rep["github_status"] == "UNVERIFIED"
    assert rep["twitter_status"] == "UNVERIFIED"
    assert rep["hackathon_status"] == "UNVERIFIED"


# --- verification ---

def test_verify_reputation_full_success(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob, gh="HIGH", tw="MEDIUM", hk="LOW")
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["github_status"] == "VERIFIED"
    assert rep["twitter_status"] == "VERIFIED"
    assert rep["hackathon_status"] == "VERIFIED"
    # HIGH = max component score
    assert rep["github_score"] == 400
    # MEDIUM = 2/3 of max, floor division
    assert rep["twitter_score"] == 200
    # LOW = 1/3 of max
    assert rep["hackathon_score"] == 100
    assert rep["total_score"] == 700


def test_verify_reputation_partial_failure_is_non_destructive(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob, gh="HIGH", tw="MEDIUM", hk="LOW")
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    prior_github_score = contract.get_reputation(direct_bob)["github_score"]
    prior_github_ts = contract.get_reputation(direct_bob)["github_last_verified_at"]

    warp_to(direct_vm, AFTER_COOLDOWN)
    mock_github_down(direct_vm, direct_bob, tw="HIGH", hk="LOW")
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    # github untouched by the failed fetch this round
    assert rep["github_score"] == prior_github_score
    assert rep["github_last_verified_at"] == prior_github_ts
    # twitter did update this round
    assert rep["twitter_score"] == 300


def test_verify_reputation_requires_cooldown(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    with pytest.raises(Exception):
        contract.verify_reputation(direct_bob)


def test_verify_reputation_after_cooldown_succeeds(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    warp_to(direct_vm, AFTER_COOLDOWN)
    mock_full(direct_vm, direct_bob, gh="MEDIUM")
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert int(rep["verification_attempts"]) == 2
    assert rep["github_score"] == 200


def test_verify_unregistered_subject_fails(contract, direct_bob):
    with pytest.raises(Exception):
        contract.verify_reputation(direct_bob)


def test_verify_pays_keeper_reward_when_pool_funded(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    direct_vm.value = 10 * 10**15
    contract.fund_rewards()
    direct_vm.value = 0
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    contract.verify_reputation(direct_bob)
    assert int(contract.get_reward_pool()) == 10 * 10**15 - 5 * 10**14


def test_verify_succeeds_with_empty_reward_pool(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)  # should not raise despite empty pool
    assert int(contract.get_reward_pool()) == 0


def test_fund_rewards_rejects_zero(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = 0
    with pytest.raises(Exception):
        contract.fund_rewards()


def test_out_of_enum_activity_level_defaults_to_none(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    code = str(direct_bob).lower()
    direct_vm.clear_mocks()
    direct_vm.mock_web(r".*api\.github\.com/users/.*", {"status": 200, "body": f"proof:{code}"})
    direct_vm.mock_web(r"https://x\.com/.*", {"status": 200, "body": f"text proof:{code}"})
    direct_vm.mock_web(r"https://devpost\.com/.*", {"status": 200, "body": f"text proof:{code}"})
    direct_vm.mock_llm(
        r".*scoring three independent pieces of public evidence.*",
        '{"github_activity_level":"EXTREME","github_summary":"x",'
        '"twitter_activity_level":"MEDIUM","twitter_summary":"y",'
        '"hackathon_activity_level":"LOW","hackathon_summary":"z"}',
    )
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["github_score"] == 0


# --- profile impersonation: proof-of-control binding ---

def test_verify_does_not_credit_evidence_without_proof_code(contract, direct_vm, direct_bob, direct_carol):
    """Bob registers real-looking, genuinely-fetchable GitHub/X/hackathon pages, but none of
    them carry Bob's own registered-address proof code -- the classic impersonation shape,
    where a registrant points at a real third party's public presence and hopes it gets scored
    as if it were their own. None of the three components may become VERIFIED."""
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full_no_proof(direct_vm, gh="HIGH", tw="HIGH", hk="HIGH")
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["github_status"] == "UNVERIFIED"
    assert rep["twitter_status"] == "UNVERIFIED"
    assert rep["hackathon_status"] == "UNVERIFIED"
    assert rep["github_score"] == 0
    assert rep["twitter_score"] == 0
    assert rep["hackathon_score"] == 0
    assert rep["total_score"] == 0


def test_verify_credits_only_components_with_proof_code(contract, direct_vm, direct_bob, direct_carol):
    """A mixed round -- only the GitHub page actually carries Bob's proof code -- must only
    credit that one component, exactly as if the other two had failed to fetch."""
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    code = str(direct_bob).lower()
    direct_vm.clear_mocks()
    direct_vm.mock_web(
        r".*api\.github\.com/users/.*",
        {"status": 200, "body": f'{{"public_repos":40,"followers":300,"bio":"proof:{code}"}}'},
    )
    direct_vm.mock_web(r"https://x\.com/.*", {"status": 200, "body": "someone else's real profile"})
    direct_vm.mock_web(r"https://devpost\.com/.*", {"status": 200, "body": "someone else's hackathon wins"})
    direct_vm.mock_llm(
        r".*scoring three independent pieces of public evidence.*",
        '{"github_activity_level":"HIGH","github_summary":"active github",'
        '"twitter_activity_level":"HIGH","twitter_summary":"active twitter",'
        '"hackathon_activity_level":"HIGH","hackathon_summary":"hackathon wins"}',
    )
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["github_status"] == "VERIFIED"
    assert rep["github_score"] == 400
    assert rep["twitter_status"] == "UNVERIFIED"
    assert rep["twitter_score"] == 0
    assert rep["hackathon_status"] == "UNVERIFIED"
    assert rep["hackathon_score"] == 0
    assert rep["total_score"] == 400


def test_verify_credits_evidence_once_subject_adds_proof_code(contract, direct_vm, direct_bob, direct_carol):
    """The legitimate remediation path: once the subject actually places their code on their own
    pages, the very next verification round (after cooldown) credits them normally."""
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full_no_proof(direct_vm)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    assert contract.get_reputation(direct_bob)["total_score"] == 0

    warp_to(direct_vm, AFTER_COOLDOWN)
    mock_full(direct_vm, direct_bob, gh="HIGH", tw="MEDIUM", hk="LOW")
    contract.verify_reputation(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["github_status"] == "VERIFIED"
    assert rep["total_score"] == 700


# --- non-public / redirector fetch-target hardening ---

NON_PUBLIC_HACKATHON_URLS = [
    "https://localhost/evidence",
    "https://127.0.0.1/evidence",
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "https://10.0.0.5/internal",
    "https://192.168.1.1/router",
    "https://[::1]/evidence",
    "https://service.internal/evidence",
    "https://box.local/evidence",
    "https://2130706433/evidence",  # decimal-obfuscated 127.0.0.1
    "https://0x7f.0x0.0x0.0x1/evidence",  # hex-obfuscated 127.0.0.1
    "https://bit.ly/abc123",  # redirector: destination is unknown at submission time
]


@pytest.mark.parametrize("bad_url", NON_PUBLIC_HACKATHON_URLS)
def test_register_rejects_non_public_hackathon_url(contract, direct_vm, direct_bob, bad_url):
    with pytest.raises(Exception):
        register(contract, direct_vm, direct_bob, hackathon=bad_url)


@pytest.mark.parametrize("bad_url", NON_PUBLIC_HACKATHON_URLS)
def test_update_evidence_rejects_non_public_hackathon_url(contract, direct_vm, direct_bob, bad_url):
    register(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.update_evidence(VALID_GITHUB, VALID_TWITTER, bad_url)


def test_register_accepts_ordinary_public_hackathon_domain(contract, direct_vm, direct_bob):
    register(contract, direct_vm, direct_bob, hackathon="https://dorahacks.io/octocat")
    assert contract.is_registered(direct_bob) is True


# --- blacklist ---

def test_blacklist_zeroes_total_score_reading(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    assert contract.get_reputation(direct_bob)["total_score"] > 0

    direct_vm.sender = direct_alice
    contract.blacklist_profile(direct_bob, "Evidence of sybil behavior")
    rep = contract.get_reputation(direct_bob)
    assert rep["total_score"] == 0
    assert rep["blacklisted"] is True


def test_non_admin_cannot_blacklist(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.blacklist_profile(direct_bob, "not admin")


def test_blacklisted_profile_cannot_be_verified(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    direct_vm.sender = direct_alice
    contract.blacklist_profile(direct_bob, "Evidence of sybil behavior")
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    with pytest.raises(Exception):
        contract.verify_reputation(direct_bob)


def test_unblacklist_restores_score_reading(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    warp_to(direct_vm, NOW)
    mock_full(direct_vm, direct_bob)
    direct_vm.sender = direct_carol
    contract.verify_reputation(direct_bob)
    score = contract.get_reputation(direct_bob)["total_score"]

    direct_vm.sender = direct_alice
    contract.blacklist_profile(direct_bob, "temp flag")
    contract.unblacklist_profile(direct_bob)
    rep = contract.get_reputation(direct_bob)
    assert rep["blacklisted"] is False
    assert rep["total_score"] == score


# --- listing ---

def test_list_profiles(contract, direct_vm, direct_bob, direct_carol):
    register(contract, direct_vm, direct_bob)
    register(contract, direct_vm, direct_carol, github="https://github.com/carolgh",
             twitter="https://twitter.com/carolgh", hackathon="https://devpost.com/carolgh")
    listed = contract.list_profiles(0, 10)
    assert len(listed) == 2
