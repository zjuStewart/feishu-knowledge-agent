#!/usr/bin/env python3
"""Bind portable workflow templates to a user's field IDs. Offline only."""
import argparse
import json
import re
import uuid
from pathlib import Path

PATTERN=re.compile(r'\{\{field:([^}]+)\}\}')


def render(template, field_map):
    def replace(match):
        table, name=match.group(1).split('.',1)
        value=field_map.get(table,{}).get(name)
        if not isinstance(value,str) or not re.fullmatch(r'fld[A-Za-z0-9]+',value):
            raise ValueError('缺少有效字段 ID：'+table+'.'+name)
        return value
    data=json.loads(PATTERN.sub(replace,json.dumps(template,ensure_ascii=False)))
    data['client_token']=str(uuid.uuid4())
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--field-map',required=True)
    p.add_argument('--output-dir',required=True)
    a=p.parse_args()
    try:
        fields=json.loads(Path(a.field_map).read_text(encoding='utf-8'))
        assets=Path(__file__).resolve().parent.parent/'assets'
        generated={f.name:render(json.loads(f.read_text(encoding='utf-8')),fields) for f in assets.glob('*.workflow.json')}
        dest=Path(a.output_dir).expanduser().resolve()
        if 'sources' in dest.parts: raise ValueError('sources/ 是只读参考目录。')
        if any((dest/name).exists() for name in generated):
            raise ValueError('输出文件已存在；保留已有 client_token，请复用它们或选择新目录。')
        dest.mkdir(parents=True,exist_ok=True)
        for name,data in generated.items():
            (dest/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    except (ValueError,OSError,KeyError) as e:
        p.exit(1,str(e)+'\n')
    print(json.dumps({'ok':True,'files':[str(dest/n) for n in generated],'remote_operations':0},ensure_ascii=False))


if __name__=='__main__': main()
