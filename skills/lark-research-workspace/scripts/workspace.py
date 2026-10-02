#!/usr/bin/env python3
"""Feishu research workspace: intake, version cache, retrieval, and confirmed archive.

No model credentials or model API calls. Model summaries are reusable, version-bound
data supplied by the host agent or Feishu workflow. Source documents are untrusted.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

TZ=dt.timezone(dt.timedelta(hours=8))
def now(): return dt.datetime.now(TZ).isoformat(timespec='seconds')
def digest(value):
    if not isinstance(value,str): value=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return hashlib.sha256(value.encode()).hexdigest()
def read(path, default=None): return json.loads(Path(path).read_text()) if Path(path).exists() else default
def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as f:
        json.dump(value,f,ensure_ascii=False,indent=2); temp=f.name
    os.replace(temp,path)
def plain(xml):
    xml=re.sub(r'<cite\b[^>]*user-name="([^"]+)"[^>]*/>',r'[受派/引用人员：\1]',xml)
    xml=re.sub(r'<cite\b[^>]*user-name="([^"]+)"[^>]*>(.*?)</cite>',r'\2 [受派/引用人员：\1]',xml,flags=re.S)
    xml=re.sub(r'</(?:p|h[1-9]|li|row|tr|title|quote|checkbox)>','\n',xml)
    return html.unescape(re.sub('<[^>]+>','',xml)).strip()

class Error(RuntimeError): pass

def shared_roots(settings):
    roots=settings.get('shared_context_roots',[settings.get('shared_context_root')])
    if not isinstance(roots,list) or not roots or any(not isinstance(v,str) or not v.strip() for v in roots):
        raise Error('共同背景根节点配置无效')
    return list(dict.fromkeys(v.strip() for v in roots))

class Client:
    def __init__(self,cfg): self.cli=cfg.get('cli','lark-cli'); self.calls=[]
    def call(self,args,stdin=None):
        self.calls.append(args[:2])
        p=subprocess.run([self.cli]+args+['--as','user','--format','json'],input=stdin,
            text=True,capture_output=True,timeout=120,env={**os.environ,
            'LARKSUITE_CLI_NO_UPDATE_NOTIFIER':'1','LARKSUITE_CLI_NO_SKILLS_NOTIFIER':'1'})
        try: x=json.loads(p.stdout if p.returncode==0 else p.stderr)
        except ValueError: raise Error('飞书返回不可解析的响应；已停止，不自动重试写入。')
        if p.returncode or not x.get('ok') or x.get('identity')!='user':
            e=x.get('error',{}); raise Error('飞书操作未完成：'+str(e.get('subtype',e.get('type','unknown'))))
        return x['data']

class Workspace:
    def __init__(self,profile,client=None):
        self.profile=Path(profile).resolve(); self.cfg=read(self.profile)
        if not self.cfg: raise Error('缺少个人配置')
        self.root=Path(self.cfg['state_dir']).resolve()
        if 'sources' in self.root.parts: raise Error('sources/ 只读')
        self.root.mkdir(parents=True,exist_ok=True)
        self.cli=client or Client(self.cfg)
        self.cloud=read(self.cfg.get('cloud_config',''),{}) if self.cfg.get('cloud_config') else {}
        self.settings=read(self.cfg['settings'])
    @contextlib.contextmanager
    def lock(self):
        with (self.root/'.workspace.lock').open('a+') as f:
            try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: raise Error('已有处理在运行，请等待其完成。')
            yield
    def state(self,name,default=None): return read(self.root/name,default)
    def save(self,name,value): write(self.root/name,value)
    def url(self,value,types=('docx','wiki','minutes')):
        u=urllib.parse.urlsplit(value)
        if u.scheme!='https' or u.netloc!=urllib.parse.urlsplit(self.settings['base_url']).netloc: raise Error('只接受当前飞书域名；外部材料请提供正文或本地文件。')
        m=re.fullmatch(r'/('+ '|'.join(types)+r')/([A-Za-z0-9]+)',u.path.rstrip('/'))
        if not m: raise Error('资料链接类型不支持')
        return m.group(1),m.group(2),urllib.parse.urlunsplit((u.scheme,u.netloc,u.path,'',''))
    def doc(self,url,force=False):
        kind,token,url=self.url(url,('docx','wiki'))
        if kind=='wiki':
            node=self.cli.call(['wiki','+node-get','--node-token',token])
            node=node.get('node',node)
            if node['obj_type']!='docx': raise Error('该节点不是可直接读取的文档')
            token=node['obj_token']
        cached=self.state('documents/'+token+'.json')
        if not force:
            meta=self.cli.call(['docs','+fetch','--doc',url,'--scope','outline','--max-depth','1'])['document']
            if cached and str(cached['revision'])==str(meta['revision_id']) and cached['document_id']==meta['document_id']:
                cached['checked_at']=now(); self.save('documents/'+token+'.json',cached)
                return cached,False
        response=self.cli.call(['docs','+fetch','--doc',url,'--detail','full'])
        d=response['document']; content=d['content']
        if d.get('revision_id') is None or d['document_id']!=token: raise Error('文档身份或版本不一致')
        title=re.search(r'<title\b[^>]*>(.*?)</title>',content,re.S)
        obj={'document_id':token,'url':url,'revision':d['revision_id'],'hash':digest(content),
             'title':plain(title.group(1)) if title else token,'text':plain(content),
             'checked_at':now(),'response':response}
        if cached:
            for k in ('shared_context','wiki_managed','path','node_token','active','availability'):
                if k in cached:obj[k]=cached[k]
        if cached and cached['hash']==obj['hash'] and cached.get('summary'): obj['summary']=cached['summary']
        self.save('documents/'+token+'.json',obj)
        return obj,True
    def directory_snapshot(self):
        mapping=read(self.cfg['directory'],{})
        status=read(Path(self.cfg['directory']).parent/'sync-status.json',{})
        if status.get('ok') is False or mapping.get('directory_complete') is not True:
            raise Error('目录尚未完整核验；旧缓存只保留作历史记录，不用于当前回答。')
        if str(mapping.get('space_id',self.settings['space_id']))!=str(self.settings['space_id']):
            raise Error('目录与配置的知识库不一致')
        return mapping
    def reconcile_directory(self):
        mapping=self.directory_snapshot(); nodes={}
        for n in mapping['nodes']:
            if n['obj_type']=='docx' and (n['obj_token'] not in nodes or n['shared_context']): nodes[n['obj_token']]=n
        changes=[]
        for p in (self.root/'documents').glob('*.json'):
            d=read(p); n=nodes.get(d['document_id'])
            if not (n or d.get('wiki_managed') or d.get('path')): continue
            before={k:d.get(k) for k in ('active','title','path','shared_context','url','availability')}
            d['wiki_managed']=True
            if n:
                d.update(title=n['title'],path=n['path'],url=n['url'],node_token=n['node_token'],shared_context=n['shared_context'])
                if d.get('availability')=='not_in_visible_directory':d.update(active=False,availability='verification_pending')
            else:
                d.update(active=False,shared_context=False,availability='not_in_visible_directory')
            if n and before['title']!=d['title']:d.pop('summary',None)
            after={k:d.get(k) for k in before}
            if before!=after:changes.append({'id':d['document_id'],'before':before,'after':after})
            self.save('documents/'+d['document_id']+'.json',d)
        result={'checked_at':now(),'directory_hash':mapping.get('directory_hash'),'changes':changes,
                'root_visible':set(shared_roots(self.settings)).issubset({n['node_token'] for n in mapping['nodes']})}
        self.save('directory-reconciliation.json',result)
        return mapping,nodes,result
    def refresh_context(self,all_docs=False):
        mapping,by_doc,reconciled=self.reconcile_directory()
        nodes=[n for n in by_doc.values() if all_docs or n['shared_context']]
        results=[]; failures=[]
        for n in nodes:
            try:
                d,changed=self.doc(n['url'])
                d.update(shared_context=n['shared_context'],title=n['title'],path=n['path'],url=n['url'],node_token=n['node_token'],
                         active=True,wiki_managed=True,availability='available')
                self.save('documents/'+d['document_id']+'.json',d)
                results.append({'id':d['document_id'],'revision':d['revision'],'changed':changed,'shared':n['shared_context']})
            except (Error,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as e:
                failures.append({'id':n['obj_token'],'shared':n['shared_context'],'error':str(e)})
                d=self.state('documents/'+n['obj_token']+'.json')
                if d:d.update(active=False,availability='unavailable');self.save('documents/'+n['obj_token']+'.json',d)
        result={'checked_at':now(),'ok':not failures and reconciled['root_visible'],'documents':results,'failures':failures,
                'root_visible':reconciled['root_visible'],'structure_changes':reconciled['changes']}
        self.save('context-status.json',result)
        self.build_context()
        result['invalidated_plans']=self.invalidate_changed_plans(mapping)
        return result
    def build_context(self):
        docs=[read(p) for p in (self.root/'documents').glob('*.json')]
        core=[d for d in docs if d.get('active',True) and d.get('shared_context')]
        mapping=read(self.cfg['directory'],{})
        if mapping.get('directory_complete') is True:
            shared_ids={n['obj_token'] for n in mapping['nodes'] if n.get('shared_context') and n['obj_type']=='docx'}
            missing_roots=sorted(set(shared_roots(self.settings))-{n['node_token'] for n in mapping['nodes']})
            root_visible=not missing_roots
            core=[d for d in core if d['document_id'] in shared_ids]
            missing=shared_ids-{d['document_id'] for d in core}
            if not root_visible or missing:
                bundle={'version':digest({'root_visible':root_visible,'missing':sorted(missing),'directory':mapping.get('directory_hash')}),
                    'valid':False,'sources':[],'parts':[],'needs_summary':[],'checked_at':now(),
                    'reason':'共同背景根节点不再可见，需指定新的根节点' if not root_visible else '共同背景正文未完整核验',
                    'unavailable_documents':sorted(missing),'root_visible':root_visible,'missing_shared_context_roots':missing_roots}
                self.save('context-bundle.json',bundle);return bundle
        if not core: raise Error('请先刷新共同背景')
        parts=[]; versions=[]; needs_summary=[]
        for d in sorted(core,key=lambda d:d['document_id']):
            versions.append({'id':d['document_id'],'revision':d['revision'],'hash':d['hash'],'title':d['title'],'path':d.get('path',''),'url':d['url']})
            summary=d.get('summary')
            valid=summary and summary['source_hash']==d['hash']
            if not valid and len(d['text'])>1800: needs_summary.append(d['document_id'])
            text=summary['text'] if valid else '原文（待压缩）：\n'+d['text']
            parts.append({'title':d['title'],'url':d['url'],'text':text,'revision':d['revision']})
        bundle={'version':digest(versions),'valid':True,'sources':versions,'parts':parts,'checked_at':now(),'needs_summary':needs_summary,
                'authority':'仅共同背景原文为现行依据；历史纪要与待确认材料不覆盖它。'}
        self.save('context-bundle.json',bundle)
        return bundle
    def set_summary(self,doc_id,text,expected_hash):
        path='documents/'+doc_id+'.json'; d=self.state(path)
        if not d or d['hash']!=expected_hash: raise Error('摘要来源版本已变化')
        d['summary']={'text':text,'source_hash':expected_hash,'created_at':now(),'kind':'agent_reviewed'}
        self.save(path,d); return self.build_context()
    def extract_file(self,path):
        p=Path(path).resolve()
        if p.stat().st_size>40*1024*1024: raise Error('文件过大，请拆分或转为飞书文档')
        raw=p.read_bytes(); ext=p.suffix.lower()
        if ext in ('.txt','.md','.csv','.json'): text=raw.decode('utf-8-sig')
        elif ext=='.docx':
            with zipfile.ZipFile(p) as z:
                info=z.getinfo('word/document.xml')
                if info.file_size>50*1024*1024: raise Error('Word展开后过大')
                root=ET.fromstring(z.read(info))
            ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            text='\n'.join(''.join(q.itertext()) for q in root.findall('.//w:p',ns))
        elif ext=='.pdf':
            binary=shutil.which('pdftotext')
            if not binary: raise Error('缺少PDF文字提取器；可提供文字版或交给宿主PDF读取能力')
            p2=subprocess.run([binary,'-layout',str(p),'-'],capture_output=True,text=True,timeout=60)
            if p2.returncode: raise Error('PDF文字提取失败')
            text=p2.stdout
        else: raise Error('此文件需宿主先提取正文；目前直接支持TXT、Markdown、CSV、JSON、Word和文字PDF。')
        if not text.strip(): raise Error('未取得正文；扫描件或音视频需先转写/OCR')
        return text,hashlib.sha256(raw).hexdigest(),str(p)
    def ingest(self,title,kind,url=None,file=None,body=None,provenance=None):
        if kind not in ('智能纪要','妙记','原始记录','上传文件','外部转发'): raise Error('未知资料类型')
        if url and not body:
            typ,token,url=self.url(url)
            if typ=='minutes':
                out=os.path.relpath(self.root/'minutes',Path.cwd())
                data=self.cli.call(['minutes','+detail','--minute-tokens',token,'--transcript','--overwrite','--output-dir',out])
                rows=data.get('minutes',[])
                if len(rows)!=1: raise Error('妙记返回数量不匹配')
                source_file=Path(rows[0]['artifacts']['transcript_file']).resolve()
                if self.root not in source_file.parents: raise Error('妙记输出目录不匹配')
                text=source_file.read_text(); rev=digest(text); hash_=rev; source_id='minutes:'+token; title=rows[0].get('title') or title
                source={'kind':'minutes','token':token,'url':url}
            else:
                d,_=self.doc(url)
                title=d['title']; text=d['text']; rev=d['revision']; hash_=d['hash']; source_id='docx:'+d['document_id']
                source={'kind':'docx','token':d['document_id'],'url':url}
        elif file:
            text,hash_,path=self.extract_file(file); rev=hash_; source_id='file:'+hash_
            source={'kind':'file','path':path,'url':url or ''}
        elif body:
            if not provenance: raise Error('粘贴正文必须注明来源和读取范围')
            text=body; hash_=digest(text); rev=hash_; source_id='text:'+digest((url or '')+'\n'+text)
            source={'kind':'text','url':url or '', 'provenance':provenance}
        else: raise Error('请提供可读链接、文件或正文')
        if not text.strip(): raise Error('材料正文为空')
        key=digest({'source_id':source_id,'hash':hash_})[:20]
        old=self.state('inbox/'+key+'.json')
        if old: return {**old,'cache_hit':True}
        item={'id':key,'title':title,'type':kind,'source_id':source_id,'source':source,'revision':rev,
              'hash':hash_,'text':text,'received_at':now(),'state':'待整理','cache_hit':False,
              'coverage':provenance or ('文档正文；链接、图片、白板及其他附件未自动展开' if source['kind']=='docx' else '取得的文字记录')}
        self.save('inbox/'+key+'.json',item)
        return item
    def cloud_write(self,table,fields,record_id=None):
        if not self.cloud: raise Error('未配置云端处理台')
        payload={'update_records':{record_id:fields}} if record_id else {'create_records':[fields]}
        return self.cli.call(['base','+record-batch-update' if record_id else '+record-batch-create',
            '--base-token',self.cloud['base_token'],'--table-id',self.cloud['tables'][table],'--json',json.dumps(payload,ensure_ascii=False)])
    def cloud_read(self,table,fields):
        path=self.root/'evidence'/('cloud-'+table+'.ndjson'); path.parent.mkdir(parents=True,exist_ok=True)
        argv=[self.cli.cli,'base','+record-list','--base-token',self.cloud['base_token'],'--table-id',self.cloud['tables'][table],
              '--format','ndjson','--output',os.path.relpath(path,Path.cwd()),'--overwrite','--as','user']
        for field in fields: argv.extend(['--field-id',field])
        p=subprocess.run(argv,capture_output=True,text=True,timeout=120,env={**os.environ,'LARKSUITE_CLI_NO_UPDATE_NOTIFIER':'1','LARKSUITE_CLI_NO_SKILLS_NOTIFIER':'1'})
        if p.returncode: raise Error('云端记录读取失败，旧本地数据保留')
        manifest=json.loads(p.stdout)
        if manifest.get('has_more') or manifest.get('records_count',0)>2000: raise Error('云端记录尚未完整读取；不能以局部覆盖完整索引')
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    def pull_cloud(self):
        if not self.cloud: return {'records':0,'changed':0,'mode':'local'}
        rows=self.cloud_read('资料收件箱',['标题','资料类型','来源链接','正文','来源标识','来源版本','内容指纹','统一摘要','共同背景版本','阅读覆盖','处理状态','处理回执'])
        changed=0
        for row in rows:
            if row.get('处理状态')==['测试完成'] or not row.get('正文'):
                stale=self.state('inbox/cloud-'+row['record_id']+'.json')
                if stale: stale['active']=False; self.save('inbox/cloud-'+row['record_id']+'.json',stale)
                continue
            key='cloud-'+row['record_id']; old=self.state('inbox/'+key+'.json',{})
            text=row['正文']; h=digest(text); rev=row.get('来源版本') or h
            item={'id':key,'title':row.get('标题') or '未命名资料','type':(row.get('资料类型') or ['原始记录'])[0],
                'source':{'kind':'cloud_text','url':row.get('来源链接') or '', 'record_id':row['record_id']},
                'source_id':row.get('来源标识') or key,'revision':rev,'hash':h,'text':text,
                'state':(row.get('处理状态') or ['待接收'])[0],'received_at':old.get('received_at') or now(),
                'summary':row.get('统一摘要') or '', 'context_version':row.get('共同背景版本'),
                'coverage':row.get('阅读覆盖') or '提交的正文；原始链接和附件需独立核验','cloud_record_id':row['record_id']}
            changed+=int(digest({k:v for k,v in item.items() if k!='received_at'})!=digest({k:v for k,v in old.items() if k!='received_at'}))
            self.save('inbox/'+key+'.json',item)
        live={r['record_id'] for r in rows if r.get('正文') and r.get('处理状态')!=['测试完成']}
        for p in (self.root/'inbox').glob('*.json'):
            item=read(p)
            if item.get('cloud_record_id') and item['cloud_record_id'] not in live:
                item.update(active=False,availability='not_in_active_inbox');write(p,item)
        roles=self.cloud_read('用户与角色',['名称','配置内容','启用'])
        self.save('roles.json',{r['名称']:r['配置内容'] for r in roles if r.get('启用') and r.get('配置内容')})
        self.save('cloud-pull-status.json',{'ok':True,'at':now(),'records':len(rows),'changed':changed})
        return {'records':len(rows),'changed':changed}
    def receive_cloud(self):
        if not self.cloud: return []
        rows=self.cloud_read('资料收件箱',['标题','资料类型','来源链接','正文','附件','处理状态','阅读覆盖'])
        results=[]
        for row in rows:
            if row.get('处理状态')!=['待接收'] or row.get('正文'): continue
            rid=row['record_id']; kind=(row.get('资料类型') or ['原始记录'])[0]
            try:
                if row.get('附件'):
                    parent=self.root/'attachments'/rid; parent.mkdir(parents=True,exist_ok=True)
                    folder=Path(tempfile.mkdtemp(prefix='receipt-',dir=parent))
                    self.cli.call(['base','+record-download-attachment','--base-token',self.cloud['base_token'],
                        '--table-id',self.cloud['tables']['资料收件箱'],'--record-id',rid,'--output',os.path.relpath(folder,Path.cwd()),'--overwrite'])
                    files=[p for p in folder.rglob('*') if p.is_file() and not p.is_symlink()]
                    if not files: raise Error('附件未下载完成')
                    extracted=[(p,self.extract_file(p)) for p in files]
                    body='\n\n'.join('文件：'+p.name+'\n'+entry[0] for p,entry in extracted)
                    source_hash=digest([entry[1] for _,entry in extracted])
                    item=self.ingest(row.get('标题') or '上传资料',kind,body=body,provenance='完整提取支持格式的附件文字；图片、音视频与扫描件未OCR')
                    item['source']['cloud_record_id']=rid
                    item['attachment_hashes']=[entry[1] for _,entry in extracted]
                    self.save('inbox/'+item['id']+'.json',item)
                elif row.get('来源链接'):
                    item=self.ingest(row.get('标题') or '链接资料',kind,url=row['来源链接'])
                else: raise Error('需补充正文、可读飞书链接或文件')
                if len(item['text'])>45000: raise Error('长资料已保存在本地，需按段整理后汇总；不能直接截断')
                self.cloud_write('资料收件箱',{'正文':item['text'],'来源标识':item['source_id'],'来源版本':str(item['revision']),
                    '内容指纹':item['hash'],'阅读覆盖':item['coverage'],'处理状态':['待整理']},rid)
                item['cloud_record_id']=rid;self.save('inbox/'+item['id']+'.json',item)
                results.append({'record_id':rid,'item_id':item['id'],'state':'待整理'})
            except Error as e:
                self.cloud_write('资料收件箱',{'处理状态':['待补充'],'待确认事项':str(e)},rid)
                results.append({'record_id':rid,'state':'待补充','reason':str(e)})
        return results
    def sync_context(self):
        bundle=self.build_context(); roles=self.state('roles.json',{})
        if bundle.get('valid') is False or bundle['needs_summary']:
            reason=bundle.get('reason') or '共同背景更新后需重建摘要：'+','.join(bundle['needs_summary'])
            return self.invalidate_cloud_context(reason,'不可访问' if bundle.get('valid') is False else '待刷新')
        version=digest({'sources':bundle['sources'],'roles':roles,'prompt_version':1})
        text='\n\n'.join(p['title']+'（版本'+str(p['revision'])+'，'+p['url']+'）：\n'+p['text'] for p in bundle['parts'])
        if not self.cloud:
            return {'valid':True,'context_version':version,'summary_characters':len(text),'mode':'local'}
        record=self.cloud.get('seed_records',{}).get('shared_bundle')
        if not record: raise Error('缺少云端共享背景记录')
        result=self.cloud_write('共享上下文',{'可复用摘要':text,'来源版本':version,'内容指纹':version,
            '版本清单':json.dumps(bundle['sources'],ensure_ascii=False),'核验时间':now(),'状态':['有效']},record)
        return {'valid':True,'context_version':version,'summary_characters':len(text),'result':result}
    def invalidate_cloud_context(self,reason,status='不可访问'):
        version='invalid-'+digest(reason)
        result={'valid':False,'context_version':version,'reason':reason}
        if self.cloud:
            record=self.cloud.get('seed_records',{}).get('shared_bundle')
            if record:
                self.cloud_write('共享上下文',{'可复用摘要':'','来源版本':version,'内容指纹':version,'状态':[status],'核验时间':now()},record)
        self.save('cloud-context-status.json',result);return result
    def source_available(self,item):
        if item.get('active') is False:return False
        sid=item.get('source_id','')
        docid=item.get('document_id') or item.get('archive_document_id') or (sid[5:] if sid.startswith('docx:') else None)
        cached=self.state('documents/'+docid+'.json') if docid else None
        if cached and (cached.get('wiki_managed') or cached.get('path')):
            if cached.get('active') is False:return False
            if item.get('document_id') is None and str(item.get('revision'))!=str(cached.get('revision')):return False
        return True
    def invalidate_changed_plans(self,mapping):
        by_node={n['node_token']:n for n in mapping['nodes']};invalid=[]
        for p in (self.root/'plans').glob('ARC-*.json'):
            plan=read(p)
            if plan['state'] not in ('待人工确认','已确认待执行'):continue
            c=plan['content'];parent=by_node.get(c['parent']);reason=None
            if not parent or parent['path']!=c['path']:reason='目标父节点已移出可见目录或路径已改变'
            item=self.state('inbox/'+plan['item_id']+'.json')
            if item and not self.source_available(item):reason='来源已变更、不可访问或不在当前知识库范围'
            if reason:
                plan.update(state='已失效',invalidated_at=now(),invalidation_reason=reason);write(p,plan);invalid.append(plan['id'])
        return invalid
    def directory_command(self):
        script=self.cfg.get('directory_refresh_script')
        if not script: raise Error('个人配置未设置目录刷新入口')
        command=[sys.executable,script]
        if self.cfg.get('directory_refresh_config'):
            command.extend(['--config',self.cfg['directory_refresh_config']])
        return command
    def daily_sync(self):
        p=subprocess.run(self.directory_command(),capture_output=True,text=True,timeout=180)
        try:directory_result=json.loads(p.stdout)
        except ValueError:directory_result={}
        if directory_result.get('skipped'):
            return {'ok':True,'skipped':'directory_sync_already_running','notice':'未宣称目录已刷新；等待已有同步完成。'}
        if p.returncode or not directory_result.get('ok'):
            reason='目录刷新未成功；旧缓存保留为历史，不作为当前上下文'
            self.save('context-bundle.json',{'valid':False,'reason':reason,'parts':[],'sources':[],'needs_summary':[],'checked_at':now()})
            try:self.invalidate_cloud_context(reason)
            finally:self.save('daily-status.json',{'ok':False,'checked_at':now(),'reason':reason})
            raise Error(reason)
        cloud=self.pull_cloud()
        context=self.refresh_context(all_docs=True)
        bundle=self.state('context-bundle.json')
        if bundle['needs_summary']:
            self.invalidate_cloud_context('共同背景有变化，等待新版摘要','待刷新')
            result={'ok':False,'needs_summary':bundle['needs_summary'],'next':'只读取这些文档的完整缓存正文，由宿主更新版本绑定摘要后执行 sync-context 和 receive-cloud。'}
            self.save('daily-status.json',result); return result
        synced=self.sync_context()
        received=self.receive_cloud() if synced['valid'] else []
        for pid in context['invalidated_plans']:
            if self.cloud:self.publish_plan(pid)
        result={'ok':context['ok'],'checked_at':now(),'documents_checked':len(context['documents']),
            'documents_changed':sum(x['changed'] for x in context['documents']),'cloud_changed':cloud['changed'],
            'context_version':synced['context_version'],'context_valid':synced['valid'],'received':received,'failures':context['failures'],
            'root_visible':context['root_visible'],'structure_changes':context['structure_changes'],'invalidated_plans':context['invalidated_plans']}
        self.save('daily-status.json',result);return result
    def publish_plan(self,pid):
        plan=self.state('plans/'+pid+'.json')
        if not plan: raise Error('计划不存在')
        c=plan['content']; result=self.cloud_write('归档计划',{'计划编号':pid,'资料标题':c['title'],'来源链接':plan['source'].get('url',''),
            '来源标识':c['source_id'],'来源版本':str(c['revision']),'正文指纹':c['hash'],'目标路径':c['path'],
            '目标父节点':c['parent'],'动作':'移动原生文档' if c['action']=='move_document' else '创建可编辑文字副本',
            '预览内容':json.dumps(c,ensure_ascii=False),'计划指纹':plan['fingerprint'],'状态':[plan['state']],
            '确认方式':'在当前对话回复：'+plan['confirmation_phrase']+'。修改表格状态不构成执行授权。',
            '结果链接':plan.get('result_url',''),'确认记录':json.dumps(plan.get('approval',{}),ensure_ascii=False),
            '执行回执':json.dumps({k:plan[k] for k in ('verified_at','editable_format_verified','edit_permission_verified','post_archive','invalidation_reason') if k in plan},ensure_ascii=False)},plan.get('cloud_record_id'))
        if not plan.get('cloud_record_id'):
            plan['cloud_record_id']=result['record_id_list'][0];self.save('plans/'+pid+'.json',plan)
        return result
    def publish_item(self,id_):
        item=self.state('inbox/'+id_+'.json')
        if not item: raise Error('材料不存在')
        if item.get('cloud_record_id'): return {'record_id':item['cloud_record_id'],'cache_hit':True}
        if len(item['text'])>45000: raise Error('正文超过单次处理上限，先分段处理，不能截断后假装完整。')
        fields={'标题':item['title'],'资料类型':[item['type']],'正文':item['text'],'来源链接':item['source'].get('url',''),
                '来源标识':item['source_id'],'来源版本':str(item['revision']),'内容指纹':item['hash'],
                '阅读覆盖':item['coverage'],'处理状态':['待整理']}
        result=self.cloud_write('资料收件箱',fields)
        ids=result.get('record_id_list')
        if not ids or len(ids)!=1: raise Error('云端可能已创建；需要回读，不自动重试。')
        item['cloud_record_id']=ids[0]; self.save('inbox/'+id_+'.json',item)
        return {'record_id':ids[0],'cache_hit':False}
    def query(self,question,role='管理',limit=10000):
        if role not in ('管理','内容','趣味'): raise Error('未知角色')
        if not 1000<=limit<=20000: raise Error('片段预算必须在1000至20000字符之间')
        self.reconcile_directory()
        bundle=self.build_context()
        if not bundle: raise Error('先刷新共同背景')
        if bundle.get('valid') is False:raise Error(bundle['reason']+'；已停止使用旧共同背景。')
        roles=self.state('roles.json',{})
        terms=set(re.findall(r'[a-zA-Z0-9]{2,}|[\u4e00-\u9fff]{2,}',question))
        grams={t[i:i+2] for t in terms for i in range(len(t)-1)}|terms
        boosts={'管理':['任务','负责人','待办','期限','推进'],'内容':['观点','证据','方法','争议','科研'],'趣味':['有趣','玩笑','比喻','表达']}[role]
        candidates=[]
        for folder in ('documents','inbox'):
            for p in (self.root/folder).glob('*.json'):
                d=read(p)
                if not self.source_available(d): continue
                for i,start in enumerate(range(0,len(d['text']),1400)):
                    chunk=d['text'][start:start+1500]
                    score=sum(3 for term in grams if term in chunk)+sum(.15 for w in boosts if w in chunk)
                    if score>=3: candidates.append((score,{'title':d['title'],'url':d.get('url') or d.get('source',{}).get('url'),
                        'revision':d['revision'],'text':chunk,'chunk':i,'shared':d.get('shared_context',False),
                        'state':d.get('state','原文证据'),'cache_checked_at':d.get('checked_at',d.get('received_at'))}))
        chunks=[]; seen=set(); used=0
        for _,c in sorted(candidates,key=lambda x:-x[0]):
            sig=digest(c['text'])
            if sig in seen or used+len(c['text'])>limit: continue
            chunks.append(c); seen.add(sig); used+=len(c['text'])
        out={'role':role,'role_preference':roles.get(role,''),'user_context':roles.get('用户背景',''),
             'shared_context':bundle,'evidence':chunks,'evidence_characters':used,
             'notice':'缓存片段附核验时间；回答现状、负责人、期限或执行归档前须回查相关原文。历史与待确认材料不自动升级为现行事实。'}
        self.save('last-context-query.json',out)
        return out
    def node_path(self,token):
        chain=[]; visited=set()
        while token:
            if token in visited or len(chain)>30: raise Error('节点路径异常')
            visited.add(token)
            n=self.cli.call(['wiki','+node-get','--node-token',token]); n=n.get('node',n)
            if str(n['space_id'])!=str(self.settings['space_id']): raise Error('目标不在授权知识库内')
            chain.append(n); token=n.get('parent_node_token','')
        return '/'.join(n['title'] for n in reversed(chain)),chain[0]
    def prepare(self,item_id,parent,action='move_document'):
        if not re.fullmatch('[a-f0-9]{20}',item_id): raise Error('资料编号不合法')
        item=self.state('inbox/'+item_id+'.json')
        if not item: raise Error('资料不存在')
        if action not in ('move_document','create_editable_copy'): raise Error('未知动作')
        if action=='move_document' and item['source']['kind']!='docx': raise Error('只有原生文档可以直接移动')
        path,node=self.node_path(parent)
        perm=self.cli.call(['drive','permission.members','auth','--params',json.dumps({'token':node['obj_token'],'type':node['obj_type'],'action':'edit'})])
        if perm.get('auth_result') is not True: raise Error('目标父文档没有编辑权限')
        if node['node_token']==item['source'].get('token'): raise Error('不能移动到自身下方')
        if item['source']['kind']=='docx':
            d,_=self.doc(item['source']['url'],force=True)
            if d['hash']!=item['hash'] or str(d['revision'])!=str(item['revision']): raise Error('来源已变更，请重新接收并预览')
        content={'source_id':item['source_id'],'revision':item['revision'],'hash':item['hash'],
                 'parent':node['node_token'],'path':path,'space_id':self.settings['space_id'],
                 'action':action,'title':item['title'],'text':item['text'] if action=='create_editable_copy' else None}
        fingerprint=digest(content); pid='ARC-'+fingerprint[:12]
        plan={'id':pid,'fingerprint':fingerprint,'item_id':item_id,'created_at':now(),'state':'待人工确认','content':content,
              'confirmation_phrase':'确认归档 '+pid,'source':item['source'],'coverage':item['coverage']}
        existing=self.state('plans/'+pid+'.json')
        if existing: return existing
        self.save('plans/'+pid+'.json',plan)
        return plan
    def validate_plan(self,plan):
        if digest(plan['content'])!=plan['fingerprint']: raise Error('计划内容已改变，旧确认失效')
        path,node=self.node_path(plan['content']['parent'])
        if path!=plan['content']['path']: raise Error('目标目录已改变，需重新预览确认')
        item=self.state('inbox/'+plan['item_id']+'.json')
        if item['hash']!=plan['content']['hash']: raise Error('材料已改变')
        if item['source']['kind']=='docx':
            d,_=self.doc(item['source']['url'],force=True)
            if d['hash']!=item['hash'] or str(d['revision'])!=str(item['revision']): raise Error('原文已改变，旧确认失效')
        elif item['source']['kind']=='file':
            if hashlib.sha256(Path(item['source']['path']).read_bytes()).hexdigest()!=item['hash']: raise Error('本地原文件已改变')
        return item
    def execute(self,pid,confirmation,evidence):
        if not re.fullmatch('ARC-[a-f0-9]{12}',pid): raise Error('计划编号不合法')
        plan=self.state('plans/'+pid+'.json')
        if not plan: raise Error('计划不存在')
        if confirmation!=plan['confirmation_phrase'] or not evidence.strip(): raise Error('缺少用户对本计划的明确确认与原始确认记录')
        if plan['state']=='已归档': return plan
        if plan['state']=='已失效':raise Error('此计划已失效，需要根据当前目录重新生成计划')
        if plan['state'] in ('执行中','待核验'): raise Error('上次操作结果需先回读，禁止自动重复创建或移动')
        item=self.validate_plan(plan)
        plan.update(state='执行中',approval={'text':confirmation,'evidence':evidence,'time':now()})
        self.save('plans/'+pid+'.json',plan)
        try:
            c=plan['content']
            if c['action']=='move_document':
                known=next((n for n in read(self.cfg['directory'],{}).get('nodes',[]) if n.get('obj_token')==item['source']['token']),None)
                mode_args=['--node-token',self.url(item['source']['url'])[1]] if '/wiki/' in item['source']['url'] else (['--node-token',known['node_token']] if known else ['--obj-type','docx','--obj-token',item['source']['token']])
                result=self.cli.call(['wiki','+move']+mode_args+[
                    '--target-space-id',str(c['space_id']),'--target-parent-token',c['parent']])
                plan['write_result']=result; self.save('plans/'+pid+'.json',plan)
                if result.get('ready') is False: raise Error('移动尚未确认完成，需按回执查询，不能重试移动')
                token=result.get('node_token') or result.get('wiki_token')
                if not token: raise Error('缺少归档节点回执')
                result_url=self.settings['base_url']+'/wiki/'+token
            else:
                # Import extracted source text as editable paragraphs, preserving the source link.
                xml='<title>'+html.escape(c['title'])+'</title><p>来源：'+html.escape(item['source'].get('url') or item['source'].get('path','粘贴原文'))+'</p>'
                xml+=''.join('<p>'+html.escape(line)+'</p>' for line in item['text'].splitlines() if line.strip())
                result=self.cli.call(['docs','+create','--doc-format','xml','--parent-token',c['parent'],'--content','-'],stdin=xml)
                plan['write_result']=result; self.save('plans/'+pid+'.json',plan)
                if result.get('warnings'): raise Error('创建有内容警告，需检查回执')
                doc_id=result['document']['document_id']
                n=self.cli.call(['wiki','+node-get','--node-token',doc_id]); n=n.get('node',n)
                token=n['node_token']; result_url=self.settings['base_url']+'/wiki/'+token
            _,node=self.node_path(token)
            if node.get('parent_node_token')!=c['parent'] or node['obj_type']!='docx': raise Error('归档位置或文档类型不匹配')
            actual,_=self.doc(result_url,force=True)
            if c['action']=='move_document' and actual['hash']!=item['hash']: raise Error('移动后正文不一致')
            if c['action']=='create_editable_copy' and re.sub(r'\s+','',item['text']) not in re.sub(r'\s+','',actual['text']): raise Error('转换后正文未通过完整性检查')
            perm=self.cli.call(['drive','permission.members','auth','--params',json.dumps({'token':actual['document_id'],'type':'docx','action':'edit'})])
            if perm.get('auth_result') is not True: raise Error('归档后编辑权限未通过核验')
            plan.update(state='已归档',result_url=result_url,verified_at=now(),editable_format_verified=True,edit_permission_verified=True)
            item.update(state='已归档',archive_url=result_url,archive_document_id=actual['document_id']); self.save('inbox/'+item['id']+'.json',item)
        except Exception:
            plan['state']='待核验'; self.save('plans/'+pid+'.json',plan); raise
        self.save('plans/'+pid+'.json',plan)
        # Remote archive succeeded: auxiliary sync failures must never cause a second write.
        followup={}
        if self.cloud:
            try:
                self.publish_plan(pid)
                if item.get('cloud_record_id'):
                    self.cloud_write('资料收件箱',{'处理状态':['已归档'],'归档结果':result_url,'处理回执':'已核验目标父节点、正文完整性与编辑权限。'},item['cloud_record_id'])
                followup['cloud_receipt']='ok'
            except Exception as e: followup['cloud_receipt']='待补同步：'+str(e)
        script=self.cfg.get('directory_refresh_script')
        if script:
            try:
                p=subprocess.run(self.directory_command(),capture_output=True,text=True,timeout=180)
                followup['directory']='ok' if p.returncode==0 else '待手动刷新'
            except (OSError,subprocess.TimeoutExpired): followup['directory']='待手动刷新'
        plan['post_archive']=followup;self.save('plans/'+pid+'.json',plan)
        return plan

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',default=str(Path.home()/'.config/lark-research-workspace/profile.json'))
    s=p.add_subparsers(dest='command',required=True)
    a=s.add_parser('context-refresh'); a.add_argument('--all',action='store_true')
    a=s.add_parser('query'); a.add_argument('question'); a.add_argument('--role',default='管理'); a.add_argument('--max-chars',type=int,default=10000)
    a=s.add_parser('intake'); a.add_argument('--title',required=True); a.add_argument('--type',required=True); a.add_argument('--url'); a.add_argument('--file'); a.add_argument('--body-file'); a.add_argument('--provenance')
    a=s.add_parser('publish'); a.add_argument('item_id')
    s.add_parser('pull-cloud')
    s.add_parser('receive-cloud')
    s.add_parser('sync-context')
    s.add_parser('daily-sync')
    a=s.add_parser('set-summary'); a.add_argument('doc_id'); a.add_argument('--text-file',required=True); a.add_argument('--source-hash',required=True)
    a=s.add_parser('publish-plan'); a.add_argument('plan_id')
    a=s.add_parser('prepare'); a.add_argument('item_id'); a.add_argument('--parent',required=True); a.add_argument('--action',default='move_document')
    a=s.add_parser('execute'); a.add_argument('plan_id'); a.add_argument('--confirmation',required=True); a.add_argument('--evidence',required=True)
    args=p.parse_args(); w=Workspace(args.config)
    try:
        with w.lock():
            if args.command=='context-refresh': result=w.refresh_context(args.all)
            elif args.command=='query': result=w.query(args.question,args.role,args.max_chars)
            elif args.command=='intake': result=w.ingest(args.title,args.type,args.url,args.file,Path(args.body_file).read_text() if args.body_file else None,args.provenance); result={k:v for k,v in result.items() if k!='text'}
            elif args.command=='publish': result=w.publish_item(args.item_id)
            elif args.command=='pull-cloud': result=w.pull_cloud()
            elif args.command=='receive-cloud': result=w.receive_cloud()
            elif args.command=='sync-context': result=w.sync_context()
            elif args.command=='daily-sync': result=w.daily_sync()
            elif args.command=='set-summary': result=w.set_summary(args.doc_id,Path(args.text_file).read_text(),args.source_hash)
            elif args.command=='publish-plan': result=w.publish_plan(args.plan_id)
            elif args.command=='prepare': result=w.prepare(args.item_id,args.parent,args.action)
            elif args.command=='execute': result=w.execute(args.plan_id,args.confirmation,args.evidence)
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False,indent=2))
    except (Error,ValueError,OSError,KeyError,subprocess.TimeoutExpired) as e:
        print(json.dumps({'ok':False,'message':str(e)},ensure_ascii=False)); sys.exit(1)

if __name__=='__main__': main()
