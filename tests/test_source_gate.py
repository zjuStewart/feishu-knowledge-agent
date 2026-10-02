import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

script = Path(__file__).resolve().parents[1] / "skills/lark-meeting-source-check/scripts/prepare_latest.py"
spec = importlib.util.spec_from_file_location("source_gate", script)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def candidate(token, notification):
    return {"document_id": token, "source_url": "https://example.feishu.cn/docx/" + token,
            "notification_time": datetime.fromisoformat(notification).replace(tzinfo=gate.TZ), "notification_message_id": "om_" + token}


def document(token, date, title_date=None):
    stamp = datetime.fromisoformat(date)
    title_stamp = datetime.fromisoformat(title_date or date)
    title = f"智能纪要：测试 {title_stamp.year}年{title_stamp.month}月{title_stamp.day}日"
    content = f"<title>{title}</title><p>会议时间：{stamp.year}年{stamp.month}月{stamp.day}日（周三） {stamp.hour:02}:{stamp.minute:02} - 12:31</p>"
    return {"ok": True, "identity": "user", "data": {"document": {"document_id": token, "revision_id": 4, "content": content}}}


class SourceGateAcceptance(unittest.TestCase):
    def test_late_resend_of_old_meeting_does_not_win(self):
        rows = [candidate("old", "2026-10-01T12:34"), candidate("new", "2026-09-30T12:34")]
        docs = {"old": document("old", "2026-07-31T11:06"), "new": document("new", "2026-09-30T11:06")}
        result = gate.choose_latest(rows, lambda row: docs[row["document_id"]])
        self.assertEqual(result["document_id"], "new")

    def test_unreadable_new_candidate_cannot_fall_back_to_old(self):
        rows = [candidate("new", "2026-09-30T12:34"), candidate("old", "2026-07-31T12:34")]
        def fetch(row):
            if row["document_id"] == "new":
                raise ValueError("Unreadable")
            return document("old", "2026-07-31T11:06")
        with self.assertRaises(ValueError):
            gate.choose_latest(rows, fetch)

    def test_title_body_date_conflict_stops(self):
        row = candidate("new", "2026-09-30T12:34")
        with self.assertRaises(ValueError):
            gate.parse_source(document("new", "2026-09-30T11:06", "2026-07-31T11:06"), row)

    def test_incomplete_pagination_stops(self):
        payload = {"ok": True, "identity": "user", "data": {"has_more": True, "messages": []}}
        with self.assertRaises(ValueError):
            gate.notifications_to_candidates(payload, {"base_url": "https://example.feishu.cn"})

    def test_expired_receipt_cannot_start_processing(self):
        row = candidate("new", "2026-09-30T12:34")
        source = document("new", "2026-09-30T11:06")
        parsed = gate.parse_source(source, row)
        now = datetime(2026, 10, 2, 14, 0, tzinfo=gate.TZ)
        manifest = {k: v for k, v in parsed.items() if k not in ("meeting_start", "notification_time")}
        manifest.update(ok=True, purpose="latest_meeting_selection", notification_chat_id="chat", sender_id="bot", verified_at=(now-timedelta(minutes=11)).isoformat())
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            gate.write_json(root/"source-status.json", {"ok": True})
            gate.write_json(root/"source-manifest.json", manifest)
            gate.write_json(root/"source-document.json", source)
            with self.assertRaises(ValueError):
                gate.verify_receipt(root, {"chat_id":"chat", "sender_id":"bot"}, now)


if __name__ == "__main__":
    unittest.main()
