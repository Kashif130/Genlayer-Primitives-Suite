import pytest

from conftest import warp_to

GEN = 10**18

NOW = "2099-01-01T00:00:00Z"
AFTER_COOLDOWN = "2099-01-01T00:31:00Z"
AFTER_GRACE = "2099-01-15T00:00:01Z"  # > 14 days after NOW
JUST_BEFORE_GRACE = "2099-01-14T23:59:59Z"

ARTICLE_FEE = 2 * 10**15
TWEET_FEE = 1 * 10**15

VALID_URL = "https://example.com/articles/some-story"


def mock_full(direct_vm, ai="LIKELY_HUMAN", plag="LIKELY_ORIGINAL", fact="ACCURATE",
              matched="", reason="Clear evidence across all sources."):
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"https://example\.com.*", {"status": 200, "body": "<html>Article body text.</html>"})
    direct_vm.mock_web(
        r".*news\.google\.com.*",
        {"status": 200, "body": "<rss><channel><item><title>Related coverage</title></item></channel></rss>"},
    )
    direct_vm.mock_web(
        r".*wikipedia\.org.*",
        {"status": 200, "body": '{"query":{"search":[{"title":"Related topic"}]}}'},
    )
    direct_vm.mock_llm(
        r".*assessing a specific piece of online content.*",
        f'{{"ai_generated_verdict":"{ai}","plagiarism_verdict":"{plag}",'
        f'"plagiarism_matched_source":"{matched}","factual_verdict":"{fact}",'
        f'"source_a_summary":"content read","source_b_summary":"news read",'
        f'"source_c_summary":"wiki read","rationale":"{reason}"}}',
    )


def mock_content_unavailable(direct_vm):
    direct_vm.clear_mocks()
    direct_vm.mock_web(r"https://example\.com.*", {"status": 500, "body": ""})


def request(contract, direct_vm, requester, url=VALID_URL, content_type="ARTICLE",
            keywords="climate summit outcome", checks=None, fee=ARTICLE_FEE):
    if checks is None:
        checks = ["AI_GENERATED", "PLAGIARIZED", "FACTUALLY_ACCURATE"]
    direct_vm.sender = requester
    direct_vm.value = fee
    aid = contract.request_assessment(url, content_type, keywords, checks)
    direct_vm.value = 0
    return aid


# --- setup / seeding ---

def test_content_types_seeded(contract):
    cfg = contract.get_content_type_config("ARTICLE")
    assert cfg["active"] is True
    assert cfg["min_independent_sources"] == 2
    assert cfg["fee_wei"] == str(ARTICLE_FEE)
    assert contract.get_content_type_config("TWEET")["fee_wei"] == str(TWEET_FEE)
    assert contract.get_content_type_config("IMAGE")["fee_wei"] == str(TWEET_FEE)


# --- admin registry ---

def test_admin_can_update_content_type_config(contract, direct_alice):
    direct_alice_addr = direct_alice
    contract.set_content_type_config("ARTICLE", 5 * 10**15, 1, True)
    cfg = contract.get_content_type_config("ARTICLE")
    assert cfg["fee_wei"] == str(5 * 10**15)
    assert cfg["min_independent_sources"] == 1


def test_non_admin_cannot_update_content_type_config(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.set_content_type_config("ARTICLE", 5 * 10**15, 1, True)


def test_set_content_type_config_rejects_unknown_type(contract):
    with pytest.raises(Exception):
        contract.set_content_type_config("VIDEO", 1 * 10**15, 2, True)


def test_set_content_type_config_rejects_bad_min_sources(contract):
    with pytest.raises(Exception):
        contract.set_content_type_config("ARTICLE", 1 * 10**15, 3, True)


def test_inactive_content_type_rejects_requests(contract, direct_vm, direct_bob):
    contract.set_content_type_config("IMAGE", TWEET_FEE, 2, False)
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, content_type="IMAGE", fee=TWEET_FEE)


# --- request validation ---

def test_request_rejects_bad_url_scheme(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, url="ftp://example.com/x")


def test_request_rejects_url_with_credentials(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, url="https://user:pass@example.com/x")


def test_request_rejects_url_with_whitespace(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, url="https://example.com/x y")


NON_PUBLIC_CONTENT_URLS = [
    "https://localhost/article",
    "https://127.0.0.1/article",
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata endpoint
    "https://10.0.0.5/internal",
    "https://192.168.1.1/router",
    "https://[::1]/article",
    "https://news.internal/article",
    "https://intranet.local/article",
    "https://2130706433/article",  # decimal-obfuscated 127.0.0.1
    "https://0x7f.0x0.0x0.0x1/article",  # hex-obfuscated 127.0.0.1
    "https://bit.ly/abc123",  # redirector: real destination unknown at submission time
]


@pytest.mark.parametrize("bad_url", NON_PUBLIC_CONTENT_URLS)
def test_request_rejects_non_public_content_url(contract, direct_vm, direct_bob, bad_url):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, url=bad_url)


def test_request_accepts_ordinary_public_domain(contract, direct_vm, direct_bob):
    aid = request(contract, direct_vm, direct_bob, url="https://apnews.com/article/some-story")
    assert contract.get_assessment(aid)["content_url"] == "https://apnews.com/article/some-story"


def test_request_rejects_too_short_url(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, url="http://a")


def test_request_rejects_unsafe_keywords(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, keywords="climate; DROP TABLE")


def test_request_rejects_unknown_check(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, checks=["DEEPFAKE"])


def test_request_rejects_duplicate_check(contract, direct_vm, direct_bob):
    with pytest.raises(Exception):
        request(contract, direct_vm, direct_bob, checks=["AI_GENERATED", "AI_GENERATED"])


def test_request_rejects_wrong_fee(contract, direct_vm, direct_bob):
    direct_vm.sender = direct_bob
    direct_vm.value = ARTICLE_FEE - 1
    with pytest.raises(Exception):
        contract.request_assessment(VALID_URL, "ARTICLE", "climate summit outcome", ["AI_GENERATED"])
    direct_vm.value = 0


def test_request_succeeds_and_is_pending(contract, direct_vm, direct_bob):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    a = contract.get_assessment(aid)
    assert a["status"] == "PENDING"
    assert a["requester"] == str(direct_bob)
    assert a["checks"] == ["AI_GENERATED", "PLAGIARIZED", "FACTUALLY_ACCURATE"]


# --- run_assessment: resolution paths ---

def test_run_assessment_resolves_all_checks(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    a = contract.get_assessment(aid)
    assert a["status"] == "RESOLVED"
    assert a["ai_generated_verdict"] == "LIKELY_HUMAN"
    assert a["plagiarism_verdict"] == "LIKELY_ORIGINAL"
    assert a["factual_verdict"] == "ACCURATE"
    assert a["resolved_at"] == NOW


def test_run_assessment_flags_ai_and_plagiarism(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm, ai="LIKELY_AI", plag="LIKELY_PLAGIARIZED", fact="INACCURATE",
              matched="othersite.com/original-story")
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    assert contract.is_flagged(aid) is True
    a = contract.get_assessment(aid)
    assert a["plagiarism_matched_source"] == "othersite.com/original-story"


def test_is_flagged_false_when_clean(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    assert contract.is_flagged(aid) is False


def test_run_assessment_only_fills_requested_checks(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob, checks=["AI_GENERATED"])
    mock_full(direct_vm, ai="LIKELY_HUMAN")
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    a = contract.get_assessment(aid)
    assert a["ai_generated_verdict"] == "LIKELY_HUMAN"
    assert a["plagiarism_verdict"] == ""
    assert a["factual_verdict"] == ""


def test_run_assessment_content_unavailable_is_insufficient(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_content_unavailable(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    a = contract.get_assessment(aid)
    assert a["status"] == "INSUFFICIENT_EVIDENCE"
    assert a["ai_generated_verdict"] == ""


def test_run_assessment_downgrades_out_of_enum_verdict(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob, checks=["AI_GENERATED"])
    mock_full(direct_vm, ai="DEFINITELY_ROBOT")
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    a = contract.get_assessment(aid)
    assert a["ai_generated_verdict"] == "UNCERTAIN"
    assert a["status"] == "INSUFFICIENT_EVIDENCE"


def test_run_assessment_pays_keeper_reward(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    # treasury should hold fee minus keeper reward
    assert int(contract.get_treasury_balance()) == ARTICLE_FEE - 1 * 10**14


def test_run_assessment_twice_before_final_status_needs_cooldown(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_content_unavailable(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    with pytest.raises(Exception):
        contract.run_assessment(aid)


def test_run_assessment_after_cooldown_can_retry(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_content_unavailable(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    warp_to(direct_vm, AFTER_COOLDOWN)
    mock_full(direct_vm)
    contract.run_assessment(aid)
    a = contract.get_assessment(aid)
    assert a["status"] == "RESOLVED"
    assert int(a["check_attempts"]) == 2


def test_cannot_run_resolved_assessment_again(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    warp_to(direct_vm, AFTER_COOLDOWN)
    with pytest.raises(Exception):
        contract.run_assessment(aid)


# --- finalize_unresolved ---

def test_finalize_unresolved_too_early_fails(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_content_unavailable(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    warp_to(direct_vm, JUST_BEFORE_GRACE)
    with pytest.raises(Exception):
        contract.finalize_unresolved(aid)


def test_finalize_unresolved_after_grace_succeeds(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_content_unavailable(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    warp_to(direct_vm, AFTER_GRACE)
    contract.finalize_unresolved(aid)
    a = contract.get_assessment(aid)
    assert a["status"] == "FAILED"


def test_finalize_unresolved_cannot_run_on_resolved(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    warp_to(direct_vm, AFTER_GRACE)
    with pytest.raises(Exception):
        contract.finalize_unresolved(aid)


# --- treasury ---

def test_only_admin_can_withdraw_treasury(contract, direct_vm, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    direct_vm.sender = direct_bob
    with pytest.raises(Exception):
        contract.withdraw_treasury(1)


def test_admin_can_withdraw_treasury(contract, direct_vm, direct_alice, direct_bob, direct_carol):
    warp_to(direct_vm, NOW)
    aid = request(contract, direct_vm, direct_bob)
    mock_full(direct_vm)
    direct_vm.sender = direct_carol
    contract.run_assessment(aid)
    balance = int(contract.get_treasury_balance())
    direct_vm.sender = direct_alice
    contract.withdraw_treasury(balance)
    assert int(contract.get_treasury_balance()) == 0


def test_withdraw_more_than_treasury_fails(contract, direct_vm, direct_alice):
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        contract.withdraw_treasury(1)


# --- views / listing ---

def test_list_assessments(contract, direct_vm, direct_bob):
    warp_to(direct_vm, NOW)
    aid1 = request(contract, direct_vm, direct_bob)
    aid2 = request(contract, direct_vm, direct_bob, url="https://example.com/other")
    listed = contract.list_assessments(0, 10)
    assert [a["id"] for a in listed] == [aid1, aid2]


def test_get_assessment_missing_raises(contract):
    with pytest.raises(Exception):
        contract.get_assessment("CAO-999")
