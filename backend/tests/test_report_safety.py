from app.services.report_service import render_html


class _Ev:
    def __init__(self, filename):
        self.id = 1
        self.filename = filename
        self.sha256 = "abc123"
        self.size_bytes = 0
        self.status = "indexed"
        self.imported_at = "2021-01-01"


def test_a_malicious_filename_cannot_inject_html_into_the_report():
    # evidence in a criminal case comes off a suspect's phone — filenames are
    # untrusted. The report is opened in a browser, so an unescaped filename is
    # a real XSS vector.
    payload = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    data = {
        "case_name": payload,
        "generated_at": "now",
        "tool": "t",
        "evidence": [_Ev(payload)],
        "timeline": [{"text": payload, "date": "", "normalized_date": "",
                      "evidence_id": 1, "source_location": ""}],
        "entities": [{"entity": payload, "type": "person", "count": 1}],
        "audit": [],
    }
    report = render_html(data)

    # no executable markup survives — every field went through escaping
    assert "<script>" not in report
    assert "<img" not in report
    # and the payload is present, escaped, so the data is not lost either
    assert "&lt;script&gt;" in report
