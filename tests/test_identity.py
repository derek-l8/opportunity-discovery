from opportunity_discovery.identity import description_hash, identity_key


def test_provider_req_id_wins_over_url():
    id1, basis1 = identity_key(provider="greenhouse", provider_req_id="42",
                               canonical_url="https://boards.greenhouse.io/a/jobs/42",
                               title="X", organization="a")
    assert basis1.startswith("provider-req")
    # same provider+req from a different aggregator URL -> same identity
    id2, _ = identity_key(provider="greenhouse", provider_req_id="42",
                          canonical_url="https://other.example.com/aggregator-link",
                          title="Different Title", organization="Whoever")
    assert id1 == id2


def test_url_basis_when_no_provider_id():
    id1, basis1 = identity_key(canonical_url="https://jobs.example.com/apply/1?utm_source=x")
    assert basis1.startswith("url https://jobs.example.com/apply/1")
    id2, _ = identity_key(canonical_url="https://jobs.example.com/apply/1")
    assert id1 == id2


def test_composite_identity_is_exact_not_fuzzy():
    id1, basis1 = identity_key(organization="Acme", title="FPGA Design Intern",
                               location_text="Austin, TX")
    assert basis1.startswith("composite")
    id2, _ = identity_key(organization="acme ", title="fpga design intern ",
                          location_text="austin, tx")
    assert id1 == id2  # normalization only
    # similar-but-different titles must NOT collide
    id3, _ = identity_key(organization="Acme", title="FPGA Verification Intern",
                          location_text="Austin, TX")
    assert id1 != id3


def test_description_hash_stable_and_case_insensitive():
    assert description_hash("Hello  World") == description_hash("hello world")
    assert description_hash("a") != description_hash("b")
    assert description_hash(None) is None
