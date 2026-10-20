import unittest
from datetime import timedelta

from radar import feedback
from radar.config import load_config
from radar.models import Job, Verdict
from radar.run import Radar
from radar.state import State
from tests.test_fetchers_and_run import COMPANY, GH_DETAIL, GH_LIST, NOW, FakeHttp


class FakeTg:
    chat_id = "42"

    def __init__(self, updates=None):
        self.updates, self.sent, self.answered, self.edited = updates or [], [], [], []

    def send(self, text, silent=False, markup=None):
        self.sent.append((text, markup))
        return 100 + len(self.sent)

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]

    def answer_callback(self, cid, text):
        self.answered.append(cid)

    def edit_buttons(self, mid, markup):
        self.edited.append((mid, markup))


def job(jid="1"):
    return Job(company_id="acme", company="Acme", job_id=jid, title="Junior Backend Engineer", url="https://x/1", source="greenhouse")


class TestFeedback(unittest.TestCase):
    def test_alerts_carry_buttons_and_are_logged(self):
        tg = FakeTg()
        r = Radar(load_config(None), [dict(COMPANY)], State(), FakeHttp({"/jobs/": lambda u: GH_DETAIL[u.rsplit("/", 1)[1]],
                                                                        "/jobs": GH_LIST}), notifier=tg, now=NOW)
        r.run(0)
        self.assertTrue(tg.sent)
        text, markup = tg.sent[0]
        sid = markup["inline_keyboard"][0][0]["callback_data"].split("|")[1]
        self.assertEqual(r.state.d["meta"]["sent"][sid]["mid"], 101)

    def test_collect_buttons_replies_and_notes(self):
        meta = {}
        sid = feedback.sent_id(job())
        feedback.record_sent(meta, sid, job(), Verdict(True, tier="A"), 101, NOW)
        chat = {"id": 42}
        tg = FakeTg([
            {"update_id": 5, "callback_query": {"id": "c1", "data": f"fb|{sid}|0", "message": {"message_id": 101, "chat": chat}}},
            {"update_id": 6, "message": {"chat": chat, "text": "too much C#", "reply_to_message": {"message_id": 101}}},
            {"update_id": 7, "message": {"chat": chat, "text": "more cyber please"}},
            {"update_id": 8, "message": {"chat": {"id": 999}, "text": "stranger"}},
        ])
        self.assertEqual(feedback.collect(meta, tg, NOW), 3)
        self.assertEqual((meta["feedback"][sid]["v"], meta["feedback"][sid]["note"]), (0, "too much C#"))
        self.assertEqual([n["text"] for n in meta["notes"]], ["more cyber please"])
        self.assertEqual((meta["tg_offset"], tg.answered), (8, ["c1"]))
        self.assertIn("לא רלוונטי", tg.edited[0][1]["inline_keyboard"][0][0]["text"])

    def test_prune_drops_old_entries(self):
        meta = {}
        feedback.record_sent(meta, "old", job(), Verdict(True), 1, NOW - timedelta(days=40))
        feedback.record_sent(meta, "new", job("2"), Verdict(True), 2, NOW)
        meta["feedback"] = {"old": {"v": 1}, "new": {"v": 0}}
        feedback.prune(meta, NOW)
        self.assertEqual((list(meta["sent"]), list(meta["feedback"])), (["new"], ["new"]))


class TestBacklog(unittest.TestCase):
    def test_baseline_job_that_now_fits_is_listed_once(self):
        routes = {"/jobs/": lambda u: GH_DETAIL[u.rsplit("/", 1)[1]], "/jobs": GH_LIST}
        r = Radar(load_config(None), [dict(COMPANY)], State(), FakeHttp(routes), now=NOW, dry_run=True)
        r.run(0)  # baseline
        jobs = r.state.company("acme")["jobs"]
        for k in jobs.values():  # pretend everything was rejected by older rules
            k.update({"a": 0, "r": "no experience signal"})
        r.state.d["meta"]["alerted"] = {}
        items = r.backlog()
        self.assertTrue(items)
        self.assertTrue(all(jobs[j.job_id]["r"] == "backlog" for j, _, _ in items))
        self.assertEqual(r.backlog(), [])


if __name__ == "__main__":
    unittest.main()
