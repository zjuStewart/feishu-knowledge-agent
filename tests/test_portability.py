import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/lark-research-workspace/scripts'
sys.path.insert(0,str(SCRIPTS))
from init_workspace import initialize
from render_workflows import render
from workspace import Workspace,write


class Portability(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()
    def initialize(self):
        return initialize(self.root/'personal','https://example.feishu.cn','1','测试知识库','Root123',ROOT/'skills')
    def test_initialization_binds_personal_directory_and_blocks_overwrite(self):
        with patch('subprocess.run',side_effect=AssertionError('Initialization must be offline')):
            result=self.initialize()
        w=Workspace(result['profile'])
        command=w.directory_command()
        self.assertEqual(command[-2:],["--config",str(self.root/'personal/directory-profile.json')])
        profile=json.loads(Path(command[-1]).read_text())
        self.assertEqual(profile['output_dir'],str(self.root/'personal/directory'))
        with self.assertRaises(ValueError):self.initialize()
    def test_local_background_sync_does_not_require_cloud(self):
        result=self.initialize();w=Workspace(result['profile'])
        write(w.cfg['directory'],{'directory_complete':True,'nodes':[{'node_token':'Root123','obj_token':'Doc123','obj_type':'docx','shared_context':True}]})
        w.save('documents/Doc123.json',{'document_id':'Doc123','title':'背景','path':'背景','url':'https://example.feishu.cn/docx/Doc123','revision':1,'hash':'sample','text':'虚构背景。','shared_context':True,'active':True})
        with patch('subprocess.run',side_effect=AssertionError('No cloud operations in local mode')):
            self.assertTrue(w.sync_context()['valid'])
            self.assertEqual(w.pull_cloud()['mode'],'local')
            self.assertEqual(w.receive_cloud(),[])
    def test_invalid_or_sensitive_tenant_url_is_rejected_without_writes(self):
        for url in ('http://example.feishu.cn','https://user:password@example.feishu.cn','https://example.feishu.cn/?token=sample'):
            with self.assertRaises(ValueError):initialize(self.root/'invalid',url,'1','测试','root',ROOT/'skills')
        self.assertFalse((self.root/'invalid').exists())
    def test_workflow_field_binding_is_complete_and_fails_closed(self):
        assets=SCRIPTS.parent/'assets'
        templates=[json.loads(p.read_text()) for p in assets.glob('*.workflow.json')]
        fields={}
        for template in templates:
            for ref in re.findall(r'\{\{field:([^}]+)\}\}',json.dumps(template,ensure_ascii=False)):
                table,name=ref.split('.',1)
                fields.setdefault(table,{})[name]='fldFake'+str(len(fields.get(table,{})))
        for template in templates:
            if '{{field:' in json.dumps(template):
                with self.assertRaises(ValueError):render(template,{})
            result=render(template,fields)
            self.assertNotIn('{{field:',json.dumps(result))
            self.assertIn('client_token',result)
        by={s['id']:s for s in templates[next(i for i,t in enumerate(templates) if any(s['id']=='intake' for s in t['steps']))]['steps']}
        self.assertEqual(by['intake']['next'],'context')
        self.assertFalse(by['context']['data']['should_proceed_when_no_results'])
        self.assertEqual(by['roles']['next'],'claim')
        self.assertEqual(by['claim']['next'],'reuse')


if __name__=='__main__':unittest.main()
