import json,sys,unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import test_workspace as base
from workspace import Workspace,Error,write

class TestTeamWorkspace(unittest.TestCase):
    setUp=base.TestWorkspace.setUp
    tearDown=base.TestWorkspace.tearDown
    core=base.TestWorkspace.core
    mapping=base.TestWorkspace.mapping
    intake=base.TestWorkspace.intake
    def test_named_confirmation_runs_exact_plan_once(self):
        self.w.cli=base.ArchiveFake()
        item=self.intake();plan=self.w.prepare(item['id'],'Parent123')
        phrase=plan['confirmation_phrase']
        self.assertIn('会议',phrase);self.assertIn('秋冬学期',phrase)
        self.assertNotIn('ARC-',phrase)
        self.w.execute_named(phrase,'测试中的明确人类确认')
        with self.assertRaises(Error):self.w.execute_named(phrase,'重复确认')
        self.assertEqual(sum(c[:2]==['wiki','+move'] for c in self.w.cli.calls),1)

    def test_named_confirmation_rejects_ambiguous_sources(self):
        item=self.intake();plan=self.w.prepare(item['id'],'Parent123')
        other=json.loads(json.dumps(plan));other['id']='ARC-111111111111'
        other['content']['source_id']='docx:AnotherDocument'
        self.w.save('plans/'+other['id']+'.json',other)
        self.fake.calls=[]
        with self.assertRaises(Error):self.w.execute_named(plan['confirmation_phrase'],'明确确认')
        self.assertEqual(self.fake.calls,[])

    def test_cloud_binding_to_other_space_stops_before_calls(self):
        profile=json.loads((self.root/'profile.json').read_text());profile['cloud_config']=str(self.root/'cloud.json')
        write(self.root/'profile.json',profile);write(self.root/'cloud.json',{'space_id':'another'})
        with self.assertRaises(Error):Workspace(self.root/'profile.json',self.fake)
        self.assertEqual(self.fake.calls,[])

    def test_personal_context_survives_team_role_pull(self):
        self.core();self.w.cloud={'schema_version':2}
        self.w.save('personal-context.json',{'text':'只给本人看的工作偏好'})
        self.w.cloud_read=lambda table,fields: [] if table=='资料收件箱' else [{'名称':'团队背景','配置内容':'团队共有目标','启用':True},{'名称':'管理','配置内容':'任务与期限','启用':True}]
        self.w.pull_cloud();q=self.w.query('任务')
        self.assertEqual(q['user_context'],'只给本人看的工作偏好')
        self.assertEqual(q['team_context'],'团队共有目标')
        self.assertNotIn('只给本人看的工作偏好',json.dumps(self.w.state('roles.json'),ensure_ascii=False))

    def test_old_and_unscoped_cloud_records_are_excluded(self):
        self.w.cloud={'schema_version':2}
        def row(rid,space):return {'record_id':rid,'所属知识库ID':space,'正文':'会议记录','处理状态':['待确认']}
        self.w.save('inbox/cloud-old.json',{'id':'cloud-old','text':'旧库资料','cloud_record_id':'old'})
        self.w.cloud_read=lambda table,fields:[row('new','1'),row('old','2'),row('unknown','')] if table=='资料收件箱' else []
        self.w.pull_cloud()
        self.assertIsNotNone(self.w.state('inbox/cloud-new.json'))
        self.assertFalse(self.w.state('inbox/cloud-old.json')['active'])
        self.assertIsNone(self.w.state('inbox/cloud-unknown.json'))

    def test_cloud_read_uses_workspace_directory_outside_callers_cwd(self):
        self.w.cloud={'base_token':'Base','tables':{'资料收件箱':'Table'}}
        self.w.cli.cli='lark-cli'
        def run(argv,**kwargs):
            output=Path(argv[argv.index('--output')+1])
            self.assertFalse(output.is_absolute())
            self.assertNotIn('..',output.parts)
            self.assertEqual(kwargs['cwd'],self.w.root)
            (kwargs['cwd']/output).write_text('{"record_id":"record1"}\n')
            return SimpleNamespace(returncode=0,stdout='{"has_more":false,"records_count":1}')
        with patch('workspace.subprocess.run',side_effect=run):
            self.assertEqual(self.w.cloud_read('资料收件箱',[]),[{'record_id':'record1'}])

    def test_human_primary_field_and_internal_id_are_separate(self):
        item=self.intake();plan=self.w.prepare(item['id'],'Parent123');self.w.cloud={'schema_version':2}
        calls=[]
        self.w.cloud_write=lambda table,fields,record_id=None:(calls.append(fields) or {'record_id_list':['recExample']})
        self.w.publish_plan(plan['id'])
        self.assertNotIn('ARC-',calls[0]['归档事项'])
        self.assertEqual(calls[0]['内部编号'],plan['id'])
        self.assertEqual(calls[0]['所属知识库ID'],'1')
        self.assertNotIn('ARC-',calls[0]['确认方式'])

if __name__=='__main__':unittest.main()
