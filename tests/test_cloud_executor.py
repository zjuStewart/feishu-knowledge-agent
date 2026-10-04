import json,unittest
from unittest.mock import patch
import test_workspace as base
from workspace import Workspace,Error,APIError,read,write
from cloud_executor import CloudExecutor

class TestCloudExecutor(unittest.TestCase):
    setUp=base.TestWorkspace.setUp
    tearDown=base.TestWorkspace.tearDown
    def worker(self):
        self.fake=base.ArchiveFake();self.w.cli=self.fake
        item=self.w.ingest('会议','智能纪要',url='https://test.feishu.cn/docx/Doc123')
        plan=self.w.prepare(item['id'],'Parent123')
        cfg=read(self.root/'profile.json');cfg['runtime']='cloud-single-owner';cfg['cloud_config']=str(self.root/'cloud.json')
        write(self.root/'profile.json',cfg);write(self.root/'cloud.json',{'schema_version':2,'space_id':'1','execution_mode':'cloud'})
        self.rows=[{'record_id':'recPlan','内部编号':plan['id'],'所属知识库ID':'1','预览内容':json.dumps(plan['content']),
            '计划指纹':plan['fingerprint'],'来源链接':item['source']['url'],'状态':['待人工确认']}]
        w=CloudExecutor(self.root/'profile.json',self.fake)
        w.cloud_read=lambda table,fields:self.rows
        def cloud_write(table,fields,rid=None):
            self.rows[0].update(fields);return {'record_id_list':['recPlan']}
        w.cloud_write=cloud_write
        return w,plan
    def moves(self):return [c for c in self.fake.calls if c[:2]==['wiki','+move']]
    def test_shared_receipt_prevents_duplicate_after_cache_loss(self):
        w,p=self.worker();r=w.execute_confirmation(p['confirmation_phrase'],'authenticated human: test fixture')
        self.assertEqual(r['state'],'已归档');self.assertEqual(self.rows[0]['状态'],['已归档'])
        (w.root/'plans'/ (p['id']+'.json')).unlink()
        self.assertTrue(w.execute_confirmation(p['confirmation_phrase'],'repeated')['reused_receipt'])
        self.assertEqual(len(self.moves()),1)
        self.assertIn('Source123',self.moves()[0]);self.assertNotIn('--obj-token',self.moves()[0])
    def test_missing_confirmation_and_other_wiki_do_not_write(self):
        w,p=self.worker()
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'')
        self.rows[0]['所属知识库ID']='2'
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
        self.assertEqual(self.moves(),[])
    def test_shared_executing_blocks_even_without_local_journal(self):
        w,p=self.worker();self.rows[0]['状态']=['执行中']
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
        self.assertEqual(self.moves(),[])
    def test_changed_source_and_target_fail_before_claim(self):
        for change in ('source','target'):
            with self.subTest(change=change):
                w,p=self.worker()
                if change=='source':self.fake.revision=2
                else:self.fake.path='重命名目录'
                with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
                self.assertEqual(self.rows[0]['状态'],['待人工确认']);self.assertEqual(self.moves(),[])
    def test_shared_claim_failure_prevents_archive(self):
        w,p=self.worker()
        w.cloud_write=lambda *args: (_ for _ in ()).throw(Error('shared write failed'))
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
        self.assertEqual(self.moves(),[])
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
    def test_uncertain_archive_does_not_retry(self):
        w,p=self.worker();old=self.fake.call
        def call(args,stdin=None):
            if args[:2]==['wiki','+move']:
                old(args,stdin);raise Error('response lost after write')
            return old(args,stdin)
        self.fake.call=call
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
        self.assertEqual(self.rows[0]['状态'],['待核验'])
        with self.assertRaises(Error):w.execute_confirmation(p['confirmation_phrase'],'human')
        self.assertEqual(len(self.moves()),1)
    def test_local_execution_disabled_in_cloud_mode(self):
        w,p=self.worker();local=Workspace(self.root/'profile.json',self.fake)
        with self.assertRaises(Error):local.execute(p['id'],p['confirmation_phrase'],'human')
        self.assertEqual(self.moves(),[])
    def test_permission_error_is_not_treated_as_drive_document(self):
        w,p=self.worker();item=w.state('inbox/'+p['item_id']+'.json')
        with patch.object(self.fake,'call',side_effect=APIError({'code':99991679})):
            with self.assertRaises(APIError):w.source_move_args(item)
        with patch.object(self.fake,'call',side_effect=APIError({'code':131014})):
            self.assertEqual(w.source_move_args(item),['--obj-type','docx','--obj-token','Doc123'])

if __name__=='__main__':unittest.main()
