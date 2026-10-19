import unittest
from unittest import mock

import requests

from radar.discover import Discoverer
from radar.http import Http, HttpError
from tests.test_fetchers_and_run import FakeHttp


def resp(status=200, body=None, text=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = (text if text is not None else (__import__("json").dumps(body) if body is not None else "")).encode()
    r.headers.update(headers or {})
    return r


class TestHttp(unittest.TestCase):
    def mk(self, seq):
        s = mock.Mock()
        s.headers = {}
        s.request.side_effect = seq
        return Http(retries=2, per_host_delay=0, session=s), s

    def test_retries_429_then_ok(self):
        h, s = self.mk([resp(429, headers={"Retry-After": "0"}), resp(200, {"ok": 1})])
        self.assertEqual(h.get_json("https://a.example/x"), {"ok": 1})
        self.assertEqual(s.request.call_count, 2)

    def test_html_instead_of_json_is_retried(self):
        h, s = self.mk([resp(200, text="<html>oops</html>"), resp(200, [1, 2])])
        with mock.patch("time.sleep"):
            self.assertEqual(h.get_json("https://a.example/x"), [1, 2])

    def test_404_raises_with_status(self):
        h, _ = self.mk([resp(404, text="nope")])
        with self.assertRaises(HttpError) as cm:
            h.get_json("https://a.example/x")
        self.assertEqual(cm.exception.status, 404)

    def test_network_error_is_wrapped(self):
        h, _ = self.mk([requests.ConnectionError("boom")] * 3)
        with mock.patch("time.sleep"), self.assertRaises(HttpError):
            h.get_json("https://a.example/x")


class TestDiscover(unittest.TestCase):
    GH = {"jobs": [{"id": 1, "title": "Dev", "location": {"name": "Tel Aviv, Israel"}, "updated_at": "2026-10-19T10:00:00Z", "absolute_url": "u"}]}

    def test_resolves_from_careers_page_link(self):
        http = FakeHttp({
            "https://acme.io/careers": '<a href="https://boards.greenhouse.io/acmeinc">Jobs</a>',
            "boards-api.greenhouse.io/v1/boards/acmeinc/jobs": self.GH,
        })
        r = Discoverer(http).resolve({"id": "acme", "name": "Acme", "domain": "acme.io"})
        self.assertEqual((r["status"], r["ats"], r["token"], r["israel_jobs"]), ("ok", "greenhouse", "acmeinc", 1))

    def test_blind_probe_needs_israel_job_for_ok(self):
        us = {"jobs": [{"id": 1, "title": "Dev", "location": {"name": "New York"}, "updated_at": "2026-10-19T10:00:00Z", "absolute_url": "u"}]}
        r = Discoverer(FakeHttp({"v1/boards/acme/jobs": us})).resolve({"id": "acme", "name": "Acme", "domain": "acme.io"})
        self.assertEqual(r["status"], "review")
        r = Discoverer(FakeHttp({"v1/boards/acme/jobs": self.GH})).resolve({"id": "acme", "name": "Acme", "domain": "acme.io"})
        self.assertEqual((r["status"], r["ats"]), ("ok", "greenhouse"))

    def test_nothing_found(self):
        r = Discoverer(FakeHttp({})).resolve({"id": "acme", "name": "Acme", "domain": "acme.io"})
        self.assertEqual(r["status"], "none")


if __name__ == "__main__":
    unittest.main()
