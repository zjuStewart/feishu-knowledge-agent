import json,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/lark-research-workspace/scripts'))
from workspace import Workspace,Error,digest,write,plain

class Fake:
    def __init__(self): self.calls=[];self.revision=1;self.content='<title>会议</title><p>方法证据与任务</p>';self.path='秋冬学期'
    def call(self,args,stdin=None):
        self.calls.append(args)
        if args[:2]==['docs','+fetch']:
            return {'document':{'document_id':'Doc123','revision_id':self.revision,'content':self.content,'reference_map':{}}}
        if args[:2]==['wiki','+node-get']:
            return {'node_token':'Parent123','obj_token':'ParentDoc','obj_type':'docx','parent_node_token':'','title':self.path,'space_id':'1'}
        if args[:3]==['drive','permission.members','auth']: return {'auth_result':True}
        raise AssertionError('Unexpected external action: '+str(args))

class ArchiveFake(Fake):
    def __init__(self):super().__init__();self.wrote=False
    def call(self,args,stdin=None):
        if args[:2]==['wiki','+move']:
            self.calls.append(args);self.wrote=True;return {'ready':True,'node_token':'Moved123'}
        if args[:2]==['docs','+create']:
            self.calls.append(args);self.wrote=True;self.content=stdin
            return {'document':{'document_id':'Doc123'}}
        if args[:2]==['wiki','+node-get'] and args[args.index('--node-token')+1] in ('Moved123','Doc123') and self.wrote:
            self.calls.append(args)
            return {'node_token':'Moved123','obj_token':'Doc123','obj_type':'docx','parent_node_token':'Parent123','title':'会议','space_id':'1'}
        return super().call(args,stdin)

class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        write(self.root/'settings.json',{'base_url':'https://test.feishu.cn','space_id':'1','shared_context_root':'Root123'})
        write(self.root/'map.json',{'directory_complete':True,'nodes':[]})
        write(self.root/'profile.json',{'state_dir':str(self.root/'state'),'settings':str(self.root/'settings.json'),'directory':str(self.root/'map.json')})
        self.fake=Fake();self.w=Workspace(self.root/'profile.json',self.fake)
    def tearDown(self): self.temp.cleanup()
    def mapping(self,*nodes):write(self.root/'map.json',{'directory_complete':True,'directory_hash':digest(nodes),'nodes':list(nodes)})
    def core(self):
        d,_=self.w.doc('https://test.feishu.cn/docx/Doc123');d.update(shared_context=True,active=True,wiki_managed=True,path='共同背景')
        self.w.save('documents/Doc123.json',d)
        n={'node_token':'Root123','obj_token':'Doc123','obj_type':'docx','shared_context':True,'title':d['title'],'path':'共同背景','url':d['url']}
        self.mapping(n);return n
    def child(self):
        d={'document_id':'Gone456','title':'旧子文档','revision':1,'hash':'oldhash','text':'旧要求应当消失',
           'url':'https://test.feishu.cn/docx/Gone456','active':True,'wiki_managed':True,'shared_context':True,'path':'共同背景/旧子文档'}
        self.w.save('documents/Gone456.json',d)
        self.w.save('inbox/cloud-old.json',{'id':'cloud-old','title':'旧副本','text':d['text'],'source_id':'docx:Gone456','revision':1,'active':True})
        return {'node_token':'Child456','obj_token':'Gone456','obj_type':'docx','shared_context':True,'title':d['title'],'path':d['path'],'url':d['url']}
    def intake(self): return self.w.ingest('会议','智能纪要',url='https://test.feishu.cn/docx/Doc123')
    def test_unchanged_revision_reuses_body(self):
        self.intake();self.fake.calls=[];self.intake()
        self.assertEqual(len(self.fake.calls),1);self.assertIn('outline',self.fake.calls[0])
    def test_changed_revision_invalidates_summary(self):
        d,_=self.w.doc('https://test.feishu.cn/docx/Doc123')
        d['summary']={'source_hash':d['hash'],'text':'旧摘要'};self.w.save('documents/Doc123.json',d)
        self.fake.revision=2;self.fake.content='<title>会议</title><p>新证据</p>'
        fresh,changed=self.w.doc('https://test.feishu.cn/docx/Doc123')
        self.assertTrue(changed);self.assertNotIn('summary',fresh)
    def test_duplicate_material_has_one_identity(self):
        a=self.intake();b=self.intake();self.assertEqual(a['id'],b['id']);self.assertTrue(b['cache_hit'])
    def test_wrong_confirmation_makes_no_external_calls(self):
        item=self.intake();p=self.w.prepare(item['id'],'Parent123');self.fake.calls=[]
        with self.assertRaises(Error): self.w.execute(p['id'],'同意','人类确认')
        self.assertEqual(self.fake.calls,[])
    def test_changed_source_blocks_approved_plan(self):
        item=self.intake();p=self.w.prepare(item['id'],'Parent123');self.fake.revision=2;self.fake.content='<title>会议</title><p>修改</p>'
        with self.assertRaises(Error):self.w.execute(p['id'],p['confirmation_phrase'],'当前用户显式确认')
        self.assertFalse(any(a[:2]==['wiki','+move'] for a in self.fake.calls))
    def test_changed_target_blocks_plan(self):
        item=self.intake();p=self.w.prepare(item['id'],'Parent123');self.fake.path='另一个目录'
        with self.assertRaises(Error):self.w.execute(p['id'],p['confirmation_phrase'],'当前用户显式确认')
    def test_tampered_plan_blocks_execution(self):
        item=self.intake();p=self.w.prepare(item['id'],'Parent123');p['content']['action']='create_editable_copy';self.w.save('plans/'+p['id']+'.json',p)
        with self.assertRaises(Error):self.w.execute(p['id'],p['confirmation_phrase'],'当前用户显式确认')
    def test_uncertain_write_is_not_repeated(self):
        item=self.intake();p=self.w.prepare(item['id'],'Parent123');p['state']='待核验';self.w.save('plans/'+p['id']+'.json',p);self.fake.calls=[]
        with self.assertRaises(Error):self.w.execute(p['id'],p['confirmation_phrase'],'当前用户显式确认')
        self.assertEqual(self.fake.calls,[])
    def test_people_annotations_preserved(self):
        text=plain('<checkbox>搭建框架（来自提出者乙）<cite type="user" user-name="受派人甲"></cite></checkbox><p><cite user-name="甲"/></p>')
        self.assertIn('受派人甲',text);self.assertIn('提出者乙',text);self.assertIn('甲',text)
    def test_word_and_text_ingest(self):
        p=self.root/'a.docx'
        with zipfile.ZipFile(p,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>真实记录</w:t></w:r></w:p></w:body></w:document>')
        result=self.w.ingest('测试','上传文件',file=p);self.assertEqual(result['text'],'真实记录')
        t=self.root/'a.txt';t.write_text('未智能处理的记录')
        self.assertEqual(self.w.ingest('测试','原始记录',file=t)['text'],'未智能处理的记录')
    def test_external_url_requires_evidence(self):
        with self.assertRaises(Error):self.w.ingest('网页','外部转发',url='https://example.com/page')
        item=self.w.ingest('网页','外部转发',url='https://example.com/page',body='用户粘贴原文',provenance='用户提供正文')
        self.assertEqual(item['source']['url'],'https://example.com/page')
    def test_role_preferences_share_same_context(self):
        self.w.save('roles.json',{'管理':'任务优先','内容':'证据优先'})
        self.core()
        self.intake()
        a=self.w.query('方法证据','管理');b=self.w.query('方法证据','内容')
        self.assertEqual(a['shared_context'],b['shared_context']);self.assertNotEqual(a['role_preference'],b['role_preference'])
    def test_confirmed_move_verifies_and_never_repeats(self):
        self.fake=ArchiveFake();self.w.cli=self.fake
        item=self.intake();p=self.w.prepare(item['id'],'Parent123')
        r=self.w.execute(p['id'],p['confirmation_phrase'],'模拟用户确认')
        self.assertEqual(r['state'],'已归档');self.assertTrue(r['edit_permission_verified'])
        self.w.execute(p['id'],p['confirmation_phrase'],'模拟用户确认')
        self.assertEqual(sum(a[:2]==['wiki','+move'] for a in self.fake.calls),1)
    def test_editable_copy_retains_source_text(self):
        self.fake=ArchiveFake();self.w.cli=self.fake
        item=self.w.ingest('会议','原始记录',body='第一行<&>\n第二行真实内容',provenance='测试原文')
        p=self.w.prepare(item['id'],'Parent123','create_editable_copy')
        r=self.w.execute(p['id'],p['confirmation_phrase'],'模拟用户确认')
        self.assertEqual(r['state'],'已归档');self.assertIn('第一行<&>',plain(self.fake.content))
    def test_new_background_requires_complete_summary(self):
        self.core();d=self.w.state('documents/Doc123.json');d.update(shared_context=True,text='更新后的完整背景。'*500)
        self.w.save('documents/Doc123.json',d)
        self.assertFalse(self.w.sync_context()['valid'])
        self.assertEqual(self.w.state('context-bundle.json')['needs_summary'],['Doc123'])
    def test_removed_document_and_its_inbox_copy_leave_context(self):
        root=self.core();self.child();self.mapping(root)
        q=self.w.query('旧要求应当消失')
        self.assertEqual(q['evidence'],[])
        self.assertEqual([s['id'] for s in q['shared_context']['sources']],['Doc123'])
        self.assertFalse(self.w.state('documents/Gone456.json')['active'])
        self.assertTrue((self.w.root/'documents/Gone456.json').exists())
    def test_moved_out_child_is_no_longer_shared_even_with_core_only_refresh(self):
        root=self.core();child=self.child();child.update(shared_context=False,path='历史记录/旧子文档')
        self.mapping(root,child);self.w.refresh_context(False)
        self.assertEqual([s['id'] for s in self.w.build_context()['sources']],['Doc123'])
        self.assertEqual(self.w.state('documents/Gone456.json')['path'],'历史记录/旧子文档')
        self.assertFalse(self.w.state('documents/Gone456.json')['shared_context'])
    def test_rename_changes_context_metadata_without_redownloading_body(self):
        root=self.core();root.update(title='新名字',path='新位置/新名字');self.mapping(root);self.fake.calls=[]
        self.w.refresh_context(True)
        d=self.w.state('documents/Doc123.json');self.assertEqual(d['title'],'新名字');self.assertEqual(d['path'],'新位置/新名字')
        self.assertEqual(sum('--detail' in c for c in self.fake.calls),0)
    def test_removed_root_empties_background_and_blocks_current_answers(self):
        self.core();self.w.build_context();self.mapping();self.w.refresh_context(True)
        bundle=self.w.state('context-bundle.json');self.assertFalse(bundle['valid']);self.assertEqual(bundle['parts'],[])
        with self.assertRaises(Error):self.w.query('会议')
        self.assertFalse(self.w.sync_context()['valid'])
    def test_inaccessible_core_is_preserved_but_not_used(self):
        self.core()
        with patch.object(self.w,'doc',side_effect=Error('不可访问')):result=self.w.refresh_context(True)
        self.assertFalse(result['ok']);self.assertFalse(self.w.state('documents/Doc123.json')['active'])
        with self.assertRaises(Error):self.w.query('会议')
    def test_old_source_revision_cannot_reenter_via_intake_copy(self):
        self.core();d=self.w.state('documents/Doc123.json');d['revision']=2;self.w.save('documents/Doc123.json',d)
        self.assertFalse(self.w.source_available({'source_id':'docx:Doc123','revision':'1'}))
        self.assertTrue(self.w.source_available({'source_id':'docx:Doc123','revision':'2'}))
    def test_target_removal_invalidates_pending_plan(self):
        item=self.intake();plan=self.w.prepare(item['id'],'Parent123');self.core()
        invalid=self.w.invalidate_changed_plans(self.w.directory_snapshot());self.assertEqual(invalid,[plan['id']])
        self.fake.calls=[]
        with self.assertRaises(Error):self.w.execute(plan['id'],plan['confirmation_phrase'],'模拟用户确认')
        self.assertEqual(self.fake.calls,[])
    def test_failed_directory_refresh_does_not_allow_old_cache_answers(self):
        self.core();write(self.root/'sync-status.json',{'ok':False,'previous_directory_preserved':True})
        with self.assertRaises(Error):self.w.query('会议')

if __name__=='__main__':unittest.main(verbosity=2)
