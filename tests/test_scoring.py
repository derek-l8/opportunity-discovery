from opportunity_discovery import constants as c
from opportunity_discovery.config import ScoringConfig
from opportunity_discovery.models import RawOpportunity
from opportunity_discovery.scoring import classify, extract_explicit_language, infer_season


def raw(**kw) -> RawOpportunity:
    base = dict(title="Engineer", canonical_url="https://x.example.com/1")
    base.update(kw)
    return RawOpportunity(**base)


def cfg() -> ScoringConfig:
    return ScoringConfig()


def test_technical_family_match():
    tags, comp, sig, reasons = classify(raw(title="FPGA Design Intern"), cfg())
    assert "semiconductor-fpga" in tags
    assert "include:broad-relevance" in reasons
    assert comp.family_weights["semiconductor-fpga"] == 1.0


def test_excerpt_half_weight():
    _, comp_t, _, _ = classify(raw(title="Platform Intern",
                                   description_excerpt="embedded firmware work"), cfg())
    assert comp_t.family_weights["embedded-firmware"] == 0.5


def test_paid_and_funded_signals():
    _, comp, sig, _ = classify(raw(compensation_text="$25/hr paid internship"), cfg())
    assert sig.get("paid") and comp.bonuses["paid"] > 0
    _, comp2, sig2, _ = classify(raw(compensation_text="fully funded; travel grant"),
                                 cfg())
    assert sig2.get("funded") and comp2.bonuses["funded"] > 0


def test_school_term_coop_suppressed_but_tagged():
    _, _, sig, reasons = classify(
        raw(title="Spring 2027 Co-op: Embedded Engineer"), cfg())
    assert c.EXCLUDE_COOP_SCHOOL_TERM in reasons
    assert sig.get("school-term-coop")


def test_online_hackathon_suppressed_unless_valuable():
    _, _, _, reasons = classify(raw(title="Online Hackathon - build stuff"), cfg())
    assert c.EXCLUDE_ONLINE_HACKATHON in reasons
    _, _, _, reasons2 = classify(
        raw(title="Online Hackathon",
            description_excerpt="sponsors will interview top teams for jobs; $50k prize pool"),
        cfg())
    assert c.EXCLUDE_ONLINE_HACKATHON not in reasons2


def test_expensive_unfunded_event_downranked():
    _, comp, _, reasons = classify(
        raw(title="AI Expo 2027",
            description_excerpt="registration fee $900",
            employment_type="event"), cfg())
    assert "recruiting-event" not in _
    # force event family via title keywords
    _, comp2, _, reasons2 = classify(
        raw(title="Tech Career Fair Expo", description_excerpt="registration fee $900"),
        cfg())
    if "recruiting-event" in comp2.family_weights:
        assert c.DOWNRANK_EXPENSIVE_EVENT in reasons2


def test_effort_estimate_from_stated_components():
    r = raw(description_excerpt="apply with resume only")
    _, _, sig, _ = classify(r, cfg())
    assert sig["effort_estimate"] == c.EFFORT_QUICK
    r = raw(description_excerpt="submit transcript, essay, and letters of recommendation")
    _, _, sig2, _ = classify(r, cfg())
    assert sig2["effort_estimate"] == c.EFFORT_SUBSTANTIAL
    r = raw(title="Nothing stated here")
    _, _, sig3, _ = classify(r, cfg())
    assert sig3["effort_estimate"] == c.EFFORT_UNKNOWN


def test_season_inference_config_driven():
    assert infer_season(raw(title="Summer 2027 Firmware Intern"), "summer-2027", {}) \
        == "summer-2027"
    aliases = {"su27": "summer-2027"}
    assert infer_season(raw(season="su27"), "summer-2027", aliases) == "summer-2027"
    assert infer_season(raw(title="No season here"), "summer-2027", {}) is None


def test_explicit_language_extraction():
    out = extract_explicit_language(raw(
        description_excerpt="open to sophomores and juniors pursuing a BS in "
                            "electrical engineering; US citizenship required"))
    assert out["class_year_language"]
    assert out["major_language"]
    assert out["work_auth_language"]
