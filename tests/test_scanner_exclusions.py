from job_scanner import ExclusionRules, apply_exclusions


def test_apply_exclusions_removes_excluded_companies_and_links():
    jobs = [
        {"company": "ACME Corp", "job_link": "https://example.com/a"},
        {"company": "Beta Labs", "job_link": "https://example.com/b"},
        {"company": "Gamma", "job_link": "https://example.com/c"},
    ]

    rules = ExclusionRules(
        excluded_job_links={"https://example.com/c"},
        excluded_companies={"acme corp", "beta labs"},
    )

    filtered = apply_exclusions(jobs, rules)

    assert filtered == []
