#!/usr/bin/env python3
"""Check publishable files and local Markdown links; never inspect credentials."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
ALLOWED_ROOT={'README.md','.gitignore','LICENSE'}
ALLOWED_DIRS={'skills','tests','scripts'}
BAD_PARTS={'state','documents','inbox','plans','evidence','trial','sources','.env'}


def main():
    failures=[];count=0
    for path in ROOT.rglob('*'):
        rel=path.relative_to(ROOT)
        if '.git' in rel.parts or '__pycache__' in rel.parts:continue
        if path.is_dir():continue
        if path.is_symlink():failures.append(str(rel)+': symlinks are not publishable');continue
        if rel.parts[0] not in ALLOWED_DIRS and str(rel) not in ALLOWED_ROOT:
            failures.append(str(rel)+': unexpected release file');continue
        if set(rel.parts)&BAD_PARTS or path.suffix in ('.png','.jpg','.zip','.log','.pyc'):
            failures.append(str(rel)+': runtime data or generated artifact');continue
        count+=1
        try:text=path.read_text(encoding='utf-8')
        except UnicodeError:failures.append(str(rel)+': non-text file');continue
        if path.suffix=='.json':
            try:json.loads(text)
            except ValueError:failures.append(str(rel)+': invalid JSON')
        # Match credential-shaped values, not generic documentation of credentials.
        if re.search(r'(?<![A-Za-z0-9])(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)',text):
            failures.append(str(rel)+': credential-shaped content')
        if ('/'+'Users/') in text or re.search(r'(?<![A-Za-z0-9])(?:oc_|ou_)[a-f0-9]{20,}',text):
            failures.append(str(rel)+': machine path or personal identity')
        for candidate in re.findall(r'https://[^/\s"<>\x27]+\.feishu\.cn',text):
            host=urlsplit(candidate).hostname
            if host not in ('test.feishu.cn','example.feishu.cn','your-tenant.feishu.cn','你的租户.feishu.cn'):
                failures.append(str(rel)+': personal tenant URL')
        if path.suffix=='.md':
            for link in re.findall(r'\]\(([^)]+)\)',text):
                if '://' in link or link.startswith('#'):continue
                target=(path.parent/link.split('#')[0]).resolve()
                if not target.exists():failures.append(str(rel)+': missing link '+link)
    print(json.dumps({'ok':not failures,'text_files_checked':count,'failures':failures},ensure_ascii=False,indent=2))
    return 1 if failures else 0


if __name__=='__main__':sys.exit(main())
