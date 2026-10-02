#!/usr/bin/env python3
"""Create an isolated personal profile. Offline; never reads credentials."""
import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit


def initialize(destination, base_url, space_id, space_name, shared_root,
               skills_dir=None, cli='lark-cli', chat_id=None, sender_id=None):
    root = Path(destination).expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('请选择空目录；初始化不会覆盖已有配置或缓存。')
    if 'sources' in root.parts:
        raise ValueError('sources/ 是只读参考目录。')
    url = urlsplit(base_url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
        raise ValueError('base_url 应为不含路径、密码或参数的 HTTPS 飞书租户域名。')
    if not all(str(v).strip() for v in (space_id, space_name, shared_root)):
        raise ValueError('知识库 ID、名称和共同背景根节点均必填。')
    if bool(chat_id) != bool(sender_id):
        raise ValueError('最近纪要核验需要同时提供本人助手会话 ID 和机器人 ID。')
    skills = Path(skills_dir).expanduser().resolve() if skills_dir else Path(__file__).resolve().parents[2]
    refresh = skills / 'lark-wiki-directory/scripts/refresh_directory.py'
    if not refresh.is_file():
        raise ValueError('请同时安装 lark-wiki-directory，或通过 --skills-dir 指定三个 Skill 的父目录。')
    root.mkdir(parents=True, exist_ok=True)
    def save(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save('settings.json', {'space_id':str(space_id), 'space_name':space_name,
         'base_url':base_url.rstrip('/'), 'shared_context_root':shared_root})
    save('directory-profile.json', {'settings_path':str(root/'settings.json'), 'output_dir':str(root/'directory'), 'cli':shutil.which(cli) or cli})
    save('profile.json', {'state_dir':str(root/'state'), 'settings':str(root/'settings.json'),
         'directory':str(root/'directory/knowledge-map.json'), 'cloud_config':str(root/'cloud-config.json'),
         'directory_refresh_script':str(refresh), 'directory_refresh_config':str(root/'directory-profile.json'),
         'cli':shutil.which(cli) or cli})
    save('state/roles.json', {'用户背景':'由当前用户填写工作范围、目标与限制。',
         '管理':'关注任务、提出者与负责人、期限、依赖和未决事项。',
         '内容':'关注观点、证据、方法、分歧和知识缺口。',
         '趣味':'仅提取有原文支持且适合工作记录的有趣表达。'})
    if chat_id:
        save('meeting-profile.json', {'chat_id':chat_id, 'sender_id':sender_id,
             'base_url':base_url.rstrip('/'), 'output_dir':str(root/'meeting-source')})
    return {'ok':True, 'profile':str(root/'profile.json'), 'directory_profile':str(root/'directory-profile.json'),
            'cloud_configured':False, 'remote_operations':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True)
    p.add_argument('--base-url', required=True)
    p.add_argument('--space-id', required=True)
    p.add_argument('--space-name', required=True)
    p.add_argument('--shared-root', required=True)
    p.add_argument('--skills-dir')
    p.add_argument('--cli', default='lark-cli')
    p.add_argument('--chat-id')
    p.add_argument('--sender-id')
    a=p.parse_args()
    try:
        result=initialize(a.workspace,a.base_url,a.space_id,a.space_name,a.shared_root,a.skills_dir,a.cli,a.chat_id,a.sender_id)
    except (ValueError,OSError) as e:
        p.exit(1,str(e)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
