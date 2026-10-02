"""Read current note notifications and prepare a verified source manifest."""
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CONFIG = Path.home() / ".config/lark-meeting-source-check/profile.json"


def cli(args):
    binary = shutil.which("lark-cli") or str(Path.home() / ".local/bin/lark-cli")
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1", LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    result = subprocess.run([binary, *args, "--as", "user", "--format", "json"],
                            capture_output=True, text=True, timeout=120, env=env)
    if result.returncode:
        raise ValueError("CLI read was not successful")
    payload = json.loads(result.stdout)
    if not payload.get("ok") or payload.get("identity") != "user":
        raise ValueError("Read was not confirmed for user identity")
    return payload


def notifications_to_candidates(payload, config):
    if not payload.get("ok") or payload.get("identity") != "user":
        raise ValueError("Unconfirmed notification read")
    if payload.get("data", {}).get("has_more") or payload.get("meta", {}).get("pagination", {}).get("complete") is False:
        raise ValueError("Incomplete pagination")
    candidates = []
    host = urlparse(config["base_url"]).netloc
    for message in payload["data"].get("messages", []):
        if message.get("deleted") or message.get("chat_id") != config["chat_id"] or message.get("sender", {}).get("open_bot_id") != config["sender_id"]:
            continue
        stamp = datetime.strptime(message["create_time"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        for link in re.findall(r'https://[^\s<>\[\]()"\u200b]+', message.get("content", "")):
            url = urlparse(link)
            match = re.fullmatch(r"/docx/([A-Za-z0-9]+)", url.path)
            if match and url.netloc == host:
                candidates.append({"document_id": match[1], "source_url": f"https://{host}{url.path}",
                                   "notification_time": stamp, "notification_message_id": message["message_id"]})
    if not candidates:
        raise ValueError("No generated note document found")
    return sorted(candidates, key=lambda row: row["notification_time"], reverse=True)


def parse_source(payload, candidate):
    if not payload.get("ok") or payload.get("identity") != "user":
        raise ValueError("Unconfirmed document read")
    document = payload["data"]["document"]
    if document["document_id"] != candidate["document_id"]:
        raise ValueError("Wrong source document")
    content = document["content"]
    title = re.search(r"<title>(.*?)</title>", content, re.S)
    start = re.search(r"会议时间：(\d{4})年(\d{1,2})月(\d{1,2})日[^<]*?(\d{1,2}):(\d{2})", content)
    if not title or not start:
        raise ValueError("Missing title or original meeting start time")
    title_date = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title[1])
    fields = tuple(map(int, start.groups()))
    if not title_date or tuple(map(int, title_date.groups())) != fields[:3]:
        raise ValueError("Title and original meeting date disagree")
    meeting_start = datetime(*fields, tzinfo=TZ)
    if meeting_start > candidate["notification_time"]:
        raise ValueError("Notification precedes original meeting start")
    return {**candidate, "meeting_start": meeting_start, "source_title": title[1],
            "revision_id": document["revision_id"],
            "content_sha256": hashlib.sha256(content.encode()).hexdigest()}


def choose_latest(candidates, fetch, expected_date=None):
    best = None
    seen = set()
    for candidate in sorted(candidates, key=lambda row: row["notification_time"], reverse=True):
        # Earlier notifications cannot refer to a meeting starting after them.
        # Stop only when that bound proves they cannot be newer than the verified best.
        if best and candidate["notification_time"] < best["meeting_start"]:
            break
        if candidate["document_id"] in seen:
            continue
        seen.add(candidate["document_id"])
        row = parse_source(fetch(candidate), candidate)
        if best is None or row["meeting_start"] > best["meeting_start"]:
            best = row
        elif row["meeting_start"] == best["meeting_start"] and row["document_id"] != best["document_id"]:
            raise ValueError("Multiple documents for latest meeting require clarification")
    if not best:
        raise ValueError("No verified meeting")
    if expected_date and best["meeting_start"].date().isoformat() != expected_date:
        raise ValueError("Latest original meeting date differs from user request")
    return best


def write_json(path, payload):
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def verify_receipt(root, config, now=None):
    status = json.loads((root / "source-status.json").read_text())
    manifest = json.loads((root / "source-manifest.json").read_text())
    if not status.get("ok") or not manifest.get("ok") or manifest.get("purpose") != "latest_meeting_selection":
        raise ValueError("No successful source selection")
    verified_at = datetime.fromisoformat(manifest["verified_at"])
    age = ((now or datetime.now(TZ)) - verified_at).total_seconds()
    if not 0 <= age <= 600 or manifest.get("notification_chat_id") != config["chat_id"] or manifest.get("sender_id") != config["sender_id"]:
        raise ValueError("Source receipt expired or belongs to another configuration")
    source = json.loads((root / "source-document.json").read_text())
    document = source["data"]["document"]
    if document["document_id"] != manifest["document_id"] or document["revision_id"] != manifest["revision_id"] or hashlib.sha256(document["content"].encode()).hexdigest() != manifest["content_sha256"]:
        raise ValueError("Source receipt does not match retained document")
    return manifest


def prepare(config, root, expected_date=None):
    queried_at = datetime.now(TZ)
    notifications = cli(["im", "+chat-messages-list", "--chat-id", config["chat_id"], "--order", "desc",
                         "--page-all", "--page-limit", "100", "--no-reactions"])
    candidates = notifications_to_candidates(notifications, config)
    documents = {}

    def fetch(candidate):
        response = cli(["docs", "+fetch", "--doc", candidate["source_url"]])
        documents[candidate["document_id"]] = response
        return response

    best = choose_latest(candidates, fetch, expected_date)
    manifest = {**best, "meeting_start": best["meeting_start"].isoformat(timespec="minutes"),
                "notification_time": best["notification_time"].isoformat(timespec="minutes"),
                "ok": True, "purpose": "latest_meeting_selection", "queried_at": queried_at.isoformat(timespec="seconds"),
                "verified_at": datetime.now(TZ).isoformat(timespec="seconds"), "notification_scope": "complete current visible assistant chat",
                "notification_chat_id": config["chat_id"], "sender_id": config["sender_id"],
                "candidates_count": len(candidates), "sources_checked": len(documents),
                "selection_basis": "original_meeting_start", "expected_date": expected_date,
                "cloud_source_instruction": f"唯一输入为{best['source_url']}，文档ID {best['document_id']}，标题《{best['source_title']}》，会议开始时间{best['meeting_start'].isoformat(timespec='minutes')}，核验版本{best['revision_id']}。必须实际读取并核对ID、日期和版本；不匹配则停止，不用历史样本替换。本次是已有材料回放，不代表新会议事件自动触发。"}
    write_json(root / "notifications.json", notifications)
    write_json(root / "source-document.json", documents[best["document_id"]])
    write_json(root / "source-manifest.json", manifest)
    write_json(root / "source-status.json", {"ok": True, "verified_at": manifest["verified_at"], "purpose": manifest["purpose"]})
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--expected-date")
    parser.add_argument("--verify-receipt", action="store_true", help="Validate an existing receipt before starting downstream processing")
    args = parser.parse_args()
    root = None
    try:
        config = json.loads(args.config.expanduser().read_text())
        for key in ("chat_id", "sender_id", "base_url", "output_dir"):
            if not isinstance(config.get(key), str) or not config[key]:
                raise ValueError("Missing profile fields")
        root = Path(config["output_dir"]).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        if args.verify_receipt:
            print(json.dumps(verify_receipt(root, config), ensure_ascii=False))
            return
        with (root / ".source-check.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(prepare(config, root, args.expected_date), ensure_ascii=False))
    except Exception as error:
        status = {"ok": False, "error_type": type(error).__name__, "purpose": "latest_meeting_selection",
                  "checked_at": datetime.now(TZ).isoformat(timespec="seconds"), "start_processing_allowed": False,
                  "message": "Source verification did not complete. Do not use a cached or old source to continue."}
        if root:
            write_json(root / "source-status.json", status)
        print(json.dumps(status, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
