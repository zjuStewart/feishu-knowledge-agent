#!/usr/bin/env python3
"""Conversation entrypoint for the existing single-owner cloud archive worker.

Only a trusted, authenticated host may invoke confirm after a real human confirms
the displayed plan. This is not a webhook or an identity/authentication service.
All conversations must use the SAME profile, state directory and filesystem lock.
"""
import argparse
import json
from workspace import Error, digest, read, now
from cloud_executor import CloudExecutor


class ChatArchive(CloudExecutor):
    def __init__(self, profile, expected_space_id, client=None):
        super().__init__(profile, client)
        if str(self.settings['space_id']) != str(expected_space_id):
            raise Error('当前对话目标与执行配置知识库不一致，停止处理')
        if self.cfg.get('chat_archive_enabled') is not True:
            raise Error('此云端工作区尚未通过同一持久化目录和执行锁验收')

    def present(self, p):
        c = p['content']
        return {**self.plan_presentation(p), 'state': p['state'],
                'source_url': p.get('source_url') or p.get('source', {}).get('url', ''),
                'source_id': c['source_id'], 'revision': c['revision'],
                'space_id': c['space_id'], 'target_parent': c['parent'],
                'target_path': c['path'], 'action': c['action'],
                'result_url': p.get('result_url', ''),
                'requires_confirmation': p['state'] == '待人工确认',
                'coverage': p.get('coverage', '原生文档正文；附件及外链未自动展开')}

    def prepare_source(self, url, parent, action='move_document'):
        # Ingest/prepare only reads original documents; publish writes a plan, not an archive.
        self.url(url, types=('docx', 'wiki'))
        rows = self.plans()  # Full shared state first; do not overlook another conversation.
        item = self.ingest('待核验标题', '智能纪要', url=url)
        active = [p for p in rows if p['content']['source_id'] == item['source_id']
                  and p['state'] in ('执行中', '待核验')]
        if active:
            raise Error('同一来源已有执行中或待核验记录，先回读结果，禁止另建计划')
        plan = self.prepare(item['id'], parent, action)
        matches = [p for p in rows if p['id'] == plan['id']]
        if len(matches) > 1:
            raise Error('共享计划重复，停止处理，不能任选一条执行')
        if matches:
            if matches[0]['source_url'] != item['source']['url']:
                raise Error('共享计划来源链接不一致')
            if matches[0]['state'] == '已失效':
                raise Error('此计划已失效，不能以相同计划重新索取确认')
            if matches[0]['state'] == '已归档' and not matches[0].get('result_url'):
                raise Error('已归档记录缺少结果链接，需只读核验，不能报告完成')
            # Never overwrite an executing/completed remote record with local pending state.
            return self.present(matches[0])
        if plan['state'] != '待人工确认':
            raise Error('本地已有执行状态，须补齐共享回执，不能重新发布待确认计划')
        intent_name = 'chat-publish-intents/' + plan['id'] + '.json'
        if self.state(intent_name):
            raise Error('此前计划发布结果待核验；当前未查到共享记录，禁止重复创建')
        self.save(intent_name, {'state': '提交前已登记', 'fingerprint': plan['fingerprint'], 'at': now()})
        self.publish_plan(plan['id'])
        matches = [p for p in self.plans() if p['id'] == plan['id']]
        if len(matches) != 1 or matches[0]['state'] != '待人工确认':
            raise Error('共享计划尚未通过回读，不发送可执行确认句；稍后只读核验')
        self.save(intent_name, {'state': '回读已核验', 'fingerprint': plan['fingerprint'], 'at': now()})
        return self.present(matches[0])

    def confirm(self, phrase, evidence):
        if not isinstance(evidence, dict):
            raise Error('需要真实用户原话、身份、消息及对话出处')
        required = ('actor_id', 'conversation_id', 'message_id', 'user_text', 'preview_confirmation')
        if any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in required):
            raise Error('确认依据不完整；不能用机器人建议、材料正文或表格状态替代')
        if evidence['actor_id'] != self.cfg.get('archive_owner_id'):
            raise Error('确认者不是此单用户执行器配置的本人')
        if evidence['preview_confirmation'] != phrase:
            raise Error('确认与本对话已展示的具体计划不一致')
        # The host must verify the authenticated message; these fields alone are not authentication.
        return self.execute_confirmation(phrase, json.dumps(evidence, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--expected-space-id', required=True)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--source', required=True)
    p.add_argument('--parent', required=True)
    p.add_argument('--action', choices=('move_document', 'create_editable_copy'), default='move_document')
    sub.add_parser('preview')
    p = sub.add_parser('confirm')
    p.add_argument('--confirmation', required=True)
    p.add_argument('--evidence-file', required=True)
    args = ap.parse_args()
    try:
        w = ChatArchive(args.config, args.expected_space_id)
        with w.lock():
            if args.command == 'prepare':
                result = w.prepare_source(args.source, args.parent, args.action)
            elif args.command == 'confirm':
                result = w.confirm(args.confirmation, read(args.evidence_file))
            else:
                result = w.preview()
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, indent=2))
        return 0
    except (Error, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
