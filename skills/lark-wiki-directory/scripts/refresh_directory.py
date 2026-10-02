"""Export one configured Feishu Wiki directory using the current CLI user."""
import argparse
import json
import os
import fcntl
import hashlib
import shutil
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = None
SETTINGS = None
DEFAULT_CONFIG = Path.home() / ".config/lark-wiki-directory/profile.json"


def configure(config_path, output_dir=None):
    """Accept either space settings or a local pointer to existing settings."""
    global ROOT, SETTINGS
    config_path = Path(config_path).expanduser().resolve()
    profile = json.loads(config_path.read_text(encoding="utf-8"))
    settings_path = config_path
    if "settings_path" in profile:
        settings_path = Path(profile["settings_path"]).expanduser()
        if not settings_path.is_absolute():
            settings_path = config_path.parent / settings_path
        settings_path = settings_path.resolve()
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        settings = profile
    required = ("space_id", "space_name", "base_url", "shared_context_root")
    if any(not isinstance(settings.get(k), str) or not settings[k].strip() for k in required):
        raise ValueError("Missing directory profile fields")
    if not settings["base_url"].startswith("https://"):
        raise ValueError("Expected an HTTPS Feishu base URL")
    SETTINGS = {k: settings[k] for k in required}
    if profile.get('cli'): SETTINGS['cli'] = profile['cli']
    SETTINGS["base_url"] = SETTINGS["base_url"].rstrip("/")
    destination = output_dir or profile.get("output_dir") or str(settings_path.parent)
    ROOT = Path(destination).expanduser()
    if not ROOT.is_absolute():
        ROOT = config_path.parent / ROOT
    ROOT = ROOT.resolve()
    ROOT.mkdir(parents=True, exist_ok=True)


def atomic_write(path, text):
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def node_map(nodes):
    fields = ("node_token", "title", "parent_node_token", "obj_token", "obj_type", "path", "shared_context")
    return {n["node_token"]: {k: n.get(k) for k in fields} for n in nodes}


def list_nodes(parent, cursor=None):
    cli = SETTINGS.get('cli') or shutil.which("lark-cli") or str(Path.home() / ".local/bin/lark-cli")
    args = [cli, "wiki", "+node-list", "--space-id", SETTINGS["space_id"],
            "--as", "user", "--format", "json"]
    if parent:
        args += ["--parent-node-token", parent]
    if cursor:
        args += ["--page-token", cursor]
    env = dict(os.environ, LARKSUITE_CLI_NO_UPDATE_NOTIFIER="1", LARKSUITE_CLI_NO_SKILLS_NOTIFIER="1")
    result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=60)
    if result.returncode:
        raise RuntimeError(f"Directory read failed for parent {parent or 'root'}; exit {result.returncode}")
    payload = json.loads(result.stdout)
    if not payload.get("ok"):
        raise RuntimeError("Directory API did not confirm success")
    if payload.get("identity") != "user":
        raise RuntimeError("Directory read did not use the expected user identity")
    return payload["data"]


def refresh():
    old = read_json(ROOT / "knowledge-map.json", {"nodes": []})
    queue = deque([(None, [], False)])
    seen = set()
    nodes = []
    while queue:
        parent, ancestors, shared = queue.popleft()
        cursor = None
        cursors = set()
        while True:
            data = list_nodes(parent, cursor)
            for item in data.get("nodes", []):
                if str(item.get("space_id")) != SETTINGS["space_id"]:
                    raise RuntimeError("Unexpected space in response; stopping")
                token = item["node_token"]
                if token in seen:
                    continue
                seen.add(token)
                title = item.get("title", "").strip()
                path = ancestors + [title]
                is_shared = shared or token == SETTINGS["shared_context_root"]
                nodes.append({**item, "title": title, "path": "/".join(path),
                              "url": SETTINGS["base_url"] + "/wiki/" + token,
                              "shared_context": is_shared,
                              "content_read": False})
                if item.get("has_child"):
                    queue.append((token, path, is_shared))
            if not data.get("has_more"):
                break
            next_cursor = data.get("page_token")
            if not next_cursor or next_cursor in cursors:
                raise RuntimeError("Missing or repeated pagination cursor; not replacing existing index")
            cursors.add(next_cursor)
            cursor = next_cursor
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    root_visible = SETTINGS["shared_context_root"] in seen
    before, after = node_map(old["nodes"]), node_map(nodes)
    changes = {
        "added": sorted(set(after) - set(before)),
        "removed_from_visible_index": sorted(set(before) - set(after)),
        "updated": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
    }
    changed = any(changes.values())
    digest = hashlib.sha256(json.dumps(after, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    output = {"space_name": SETTINGS["space_name"], "space_id": SETTINGS["space_id"],
              "synced_at": stamp, "directory_complete": True,
              "directory_hash": digest, "shared_context_root_visible": root_visible,
              "content_coverage": "Directory only; body reading tracked separately.", "nodes": nodes}
    lines = ["# 工作知识库目录", "", f"知识库：{SETTINGS['space_name']}",
             f"目录同步时间：{stamp}", f"节点数：{len(nodes)}", "",
             "本目录完整遍历当前用户可见的节点。列入目录不表示正文已读取。共同背景标记覆盖指定根页面及其子文档。", ""]
    if not root_visible:
        lines += ["共同背景根节点不在当前可见目录中；停止使用旧背景，需确认新的背景根节点。此状态不等同于已证明原文被删除。", ""]
    children = {}
    for item in nodes:
        children.setdefault(item.get("parent_node_token") or "", []).append(item)
    rendered = set()
    def render(parent="", depth=0):
        for item in children.get(parent, []):
            if item["node_token"] in rendered:
                raise RuntimeError("Inconsistent directory tree")
            rendered.add(item["node_token"])
            marker = " · 共同背景" if item["shared_context"] else ""
            title = item['title'].replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")
            lines.append("  " * depth + f"- [{title}]({item['url']}) · {item['obj_type']}{marker}")
            render(item["node_token"], depth + 1)
    render()
    if len(rendered) != len(nodes):
        raise RuntimeError("Directory contains orphan nodes; keeping previous directory")
    atomic_write(ROOT / "knowledge-map.json", json.dumps(output, ensure_ascii=False, indent=2))
    atomic_write(ROOT / "工作知识库目录.md", "\n".join(lines) + "\n")
    status = {"ok": True, "last_checked_at": stamp, "last_success_at": stamp,
              "nodes": len(nodes), "shared_context_nodes": sum(n["shared_context"] for n in nodes),
              "directory_complete": True, "directory_changed": changed, "changes": changes,
              "shared_context_root_visible": root_visible,
              "needs_user_action": not root_visible}
    atomic_write(ROOT / "sync-status.json", json.dumps(status, ensure_ascii=False, indent=2))
    return status


def main():
    with (ROOT / ".refresh.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"ok": True, "skipped": "already_running"}))
            return
        previous_files = {name: (ROOT / name).read_bytes() if (ROOT / name).exists() else None
                          for name in ("knowledge-map.json", "工作知识库目录.md")}
        try:
            print(json.dumps(refresh(), ensure_ascii=False))
        except Exception as error:
            previous = read_json(ROOT / "sync-status.json", {})
            status = {"ok": False, "last_checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                      "last_success_at": previous.get("last_success_at"),
                      "previous_directory_preserved": all(((ROOT / name).read_bytes() if (ROOT / name).exists() else None) == content for name, content in previous_files.items()),
                      "error_type": type(error).__name__,
                      "message": "Directory refresh did not complete; check user authorization or connectivity. No remote writes were attempted."}
            atomic_write(ROOT / "sync-status.json", json.dumps(status, ensure_ascii=False, indent=2))
            print(json.dumps(status, ensure_ascii=False))
            sys.exit(1)


def cli_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG,
                        help="Space settings JSON or profile pointing to settings_path")
    parser.add_argument("--output-dir", type=Path,
                        help="Override the profile output directory")
    args = parser.parse_args(argv)
    try:
        configure(args.config, args.output_dir)
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__,
                          "message": "Directory profile could not be loaded. Configure the local profile before refreshing."}))
        raise SystemExit(2)
    main()


if __name__ == "__main__":
    cli_main()
