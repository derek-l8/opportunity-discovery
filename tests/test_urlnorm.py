from opportunity_discovery.urlnorm import ATSPattern, detect_ats, normalize_url


def test_strips_tracking_params():
    url = "https://jobs.example.com/apply/1?utm_source=x&id=7&fbclid=abc"
    assert normalize_url(url) == "https://jobs.example.com/apply/1?id=7"


def test_preserves_requisition_params():
    url = "https://x.example.com/?gh_jid=123&board=eng"
    assert "gh_jid=123" in normalize_url(url)


def test_scheme_host_fragment_normalization():
    assert normalize_url("http://EXAMPLE.com:443/a//b/#frag") == "https://example.com/a/b/"
    assert normalize_url("https://example.com:8080/x?b=2&a=1") == "https://example.com:8080/x?a=1&b=2"


def test_detect_greenhouse():
    p = detect_ats("https://boards.greenhouse.io/acme/jobs/1001")
    assert p == ATSPattern("greenhouse", "acme", None, "1001")
    p = detect_ats("https://job-boards.greenhouse.io/acme/jobs/1001")
    assert p.provider == "greenhouse" and p.org == "acme"


def test_detect_lever_ashby_smartrecruiters():
    assert detect_ats("https://jobs.lever.co/acme/abc12").provider == "lever"
    assert detect_ats("https://jobs.eu.lever.co/acme/abc12").provider == "lever"
    assert detect_ats("https://jobs.ashbyhq.com/acme/xyz").provider == "ashby"
    p = detect_ats("https://careers.smartrecruiters.com/Acme/ABC-123")
    assert p.provider == "smartrecruiters" and p.req_id == "ABC-123"


def test_detect_workday():
    p = detect_ats("https://intel.wd1.myworkdayjobs.com/External/job/x/1.html")
    assert p.provider == "workday"
    assert p.org == "intel"
    assert p.board_or_site == "External"


def test_no_false_ats_detection():
    assert detect_ats("https://careers.example.com/apply") is None
    assert detect_ats("") is None
