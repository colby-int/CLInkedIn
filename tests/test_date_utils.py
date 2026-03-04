from app.date_utils import posted_date_to_minutes, sort_jobs_by_date


def test_posted_date_to_minutes_parses_relative_units():
    assert posted_date_to_minutes("5 hours ago") == 5 * 60
    assert posted_date_to_minutes("2 days ago") == 2 * 24 * 60
    assert posted_date_to_minutes("3 weeks ago") == 3 * 7 * 24 * 60
    assert posted_date_to_minutes("1 month ago") == 30 * 24 * 60


def test_posted_date_to_minutes_handles_unknown_as_oldest():
    assert posted_date_to_minutes("N/A") > posted_date_to_minutes("6 months ago")


def test_sort_jobs_by_date_orders_newest_first():
    jobs = [
        {"title": "Older", "posted_date": "3 weeks ago"},
        {"title": "Newest", "posted_date": "1 day ago"},
        {"title": "Unknown", "posted_date": "N/A"},
    ]

    sorted_jobs = sort_jobs_by_date(jobs)

    assert [job["title"] for job in sorted_jobs] == ["Newest", "Older", "Unknown"]
