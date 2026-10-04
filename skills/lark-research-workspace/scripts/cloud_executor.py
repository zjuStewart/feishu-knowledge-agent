#!/usr/bin/env python3
"""Single-owner cloud archive worker. No web server, secrets, or model calls.

The trusted host must obtain confirmation from the authenticated human conversation.
Never invoke from document instructions, Base status changes, or an anonymous webhook.
A persistent shared state directory and exactly one worker identity are required.
"""
import argparse
import json
from pathlib import Path
from workspace import Workspace, Error, digest, read

FIELDS=['内部编号','所属知识库ID','预览内容','计划指纹','来源链接','状态','结果链接','执行回执','确认记录']

def scalar(value):
    return value[0] if isinstance(value,list) and len(value)==1 else value

class CloudExecutor(Workspace):
    is_cloud_executor=True
    def __init__(self,profile,client=None):
        super().__init__(profile,client)
        if self.cfg.get('runtime')!='cloud-single-owner' or self.cloud.get('schema_version',0)<2:
            raise Error('需要专用云端单执行者配置及第二版处理台')
    def plans(self):
        result=[]
        for row in self.cloud_read('归档计划',FIELDS):
            if str(row.get('所属知识库ID'))!=str(self.settings['space_id']): continue
            try: content=json.loads(row['预览内容'])
            except (ValueError,KeyError,TypeError): raise Error('当前库有不可解析的归档预览，请先修复')
            if str(content.get('space_id'))!=str(self.settings['space_id']) or digest(content)!=row.get('计划指纹'):
                raise Error('云端计划身份或指纹不一致')
            pid='ARC-'+digest(content)[:12]
            if row.get('内部编号')!=pid: raise Error('云端计划编号与指纹不一致')
            plan={'id':pid,'content':content,'fingerprint':digest(content),'cloud_record_id':row['record_id'],
                  'state':scalar(row.get('状态')),'result_url':row.get('结果链接',''),'source_url':row.get('来源链接','')}
            plan.update(self.plan_presentation(plan));result.append(plan)
        return result
    def preview(self):
        return [{'display_name':p['display_name'],'state':p['state'],'source_url':p['source_url'],
                 'confirmation_phrase':p['confirmation_phrase'],'result_url':p['result_url']} for p in self.plans()]
    def execution_started(self,plan):
        # Persist the shared non-retryable state BEFORE the first archive write.
        self.publish_plan(plan['id'])
        rows=[p for p in self.plans() if p['id']==plan['id']]
        if len(rows)!=1 or rows[0]['state']!='执行中': raise Error('共享执行状态未通过回读，禁止归档')
    def execute_confirmation(self,confirmation,evidence):
        if not confirmation.strip() or not evidence.strip(): raise Error('缺少具体的人类确认及对话出处')
        matches=[p for p in self.plans() if p['confirmation_phrase']==confirmation and p['state']!='已失效']
        if len(matches)!=1: raise Error('确认未唯一对应当前库的一份计划')
        p=matches[0];c=p['content']
        if p['state']=='已归档':
            if not p['result_url']: raise Error('共享回执缺少结果链接，需要只读核验')
            return {'state':'已归档','display_name':p['display_name'],'result_url':p['result_url'],'reused_receipt':True}
        if p['state']!='待人工确认': raise Error('已有执行记录或待核验状态，禁止重复执行')
        saved=self.state('plans/'+p['id']+'.json',{})
        if saved.get('state') in ('执行中','待核验','已归档'):
            raise Error('持久化执行记录存在，须先补齐共享回执，不能重新归档')
        # v1 cloud executor deliberately accepts live native documents only.
        if not c['source_id'].startswith('docx:'): raise Error('云端此版本仅执行可实时核验的原生文档计划；其他资料保留待确认')
        item=self.ingest(c['title'],'智能纪要',url=p['source_url'])
        if item['source_id']!=c['source_id'] or item['hash']!=c['hash'] or str(item['revision'])!=str(c['revision']):
            raise Error('来源版本已变化，请重新预览确认')
        if c['action']=='create_editable_copy' and c.get('text')!=item['text']: raise Error('副本正文与来源不一致')
        if c['action'] not in ('move_document','create_editable_copy'): raise Error('不支持的归档动作')
        p.update(item_id=item['id'],source=item['source'],coverage=item['coverage'])
        self.save('plans/'+p['id']+'.json',p)
        try: result=self.execute(p['id'],confirmation,evidence)
        except Exception:
            current=self.state('plans/'+p['id']+'.json',{})
            if current.get('state')=='待核验':
                try:self.publish_plan(p['id'])
                except Exception:pass  # Persistent journal and shared executing status prohibit retries.
            raise
        return {k:result[k] for k in ('state','display_name','result_url','verified_at','post_archive') if k in result}

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True)
    s=p.add_subparsers(dest='command',required=True);s.add_parser('preview')
    a=s.add_parser('execute-confirmation');a.add_argument('--confirmation',required=True);a.add_argument('--evidence',required=True)
    args=p.parse_args()
    try:
        worker=CloudExecutor(args.config)
        with worker.lock():
            result=worker.preview() if args.command=='preview' else worker.execute_confirmation(args.confirmation,args.evidence)
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False,indent=2));return 0
    except (Error,OSError,ValueError) as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
