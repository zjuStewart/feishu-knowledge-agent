import json
import sys
import unittest
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/lark-research-workspace/scripts'))
import test_workspace as base
from workspace import Error, read, write, digest
from chat_archive import ChatArchive


class TestChatArchive(unittest.TestCase):
    setUp = base.TestWorkspace.setUp
    tearDown = base.TestWorkspace.tearDown

    def worker(self):
        self.fake = base.ArchiveFake()
        cfg = read(self.root / 'profile.json')
        cfg.update(runtime='cloud-single-owner', cloud_config=str(self.root / 'cloud.json'),
                   chat_archive_enabled=True, archive_owner_id='human-owner')
        write(self.root / 'profile.json', cfg)
        write(self.root / 'cloud.json', {'schema_version': 2, 'space_id': '1', 'execution_mode': 'cloud'})
        self.rows = []
        self.writes = []
        return self.new_session()

    def new_session(self):
        w = ChatArchive(self.root / 'profile.json', '1', self.fake)
        w.cloud_read = lambda table, fields: self.rows
        def cloud_write(table, fields, rid=None):
            self.writes.append((table, fields.copy(), rid))
            if rid:
                row = next(r for r in self.rows if r['record_id'] == rid)
            else:
                rid = 'rec' + str(len(self.rows) + 1)
                row = {'record_id': rid}
                self.rows.append(row)
            row.update(fields)
            return {'record_id_list': [rid]}
        w.cloud_write = cloud_write
        return w

    def prepare(self, w):
        return w.prepare_source('https://test.feishu.cn/docx/Doc123', 'Parent123')

    def evidence(self, p):
        return dict(actor_id='human-owner', conversation_id='test-conversation',
                    message_id='authenticated-message', user_text=p['confirmation_phrase'],
                    preview_confirmation=p['confirmation_phrase'])

    def moves(self):
        return [c for c in self.fake.calls if c[:2] == ['wiki', '+move']]

    def test_prepare_publishes_real_plan_without_archival(self):
        w = self.worker(); p = self.prepare(w)
        self.assertTrue(p['requires_confirmation'])
        self.assertEqual(p['revision'], 1)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.moves(), [])

    def test_same_conversation_confirm_and_duplicate_receipt(self):
        w = self.worker(); p = self.prepare(w)
        self.assertEqual(w.confirm(p['confirmation_phrase'], self.evidence(p))['state'], '已归档')
        self.assertTrue(w.confirm(p['confirmation_phrase'], self.evidence(p))['reused_receipt'])
        self.assertEqual(len(self.moves()), 1)

    def test_another_conversation_reuses_shared_plan_and_receipt(self):
        w = self.worker(); p = self.prepare(w)
        second = self.new_session()
        self.assertEqual(self.prepare(second)['confirmation_phrase'], p['confirmation_phrase'])
        self.assertEqual(len(self.rows), 1)
        second.confirm(p['confirmation_phrase'], self.evidence(p))
        self.assertTrue(w.confirm(p['confirmation_phrase'], self.evidence(p))['reused_receipt'])
        self.assertEqual(len(self.moves()), 1)

    def test_same_state_directory_is_actually_locked_across_sessions(self):
        w = self.worker(); other = self.new_session()
        with w.lock():
            with self.assertRaises(Error):
                with other.lock(): pass
        with other.lock(): pass

    def test_completed_shared_receipt_is_not_reset_by_prepare(self):
        w = self.worker(); p = self.prepare(w)
        w.confirm(p['confirmation_phrase'], self.evidence(p))
        for f in (w.root / 'plans').glob('*.json'): f.unlink()
        count = len(self.writes)
        self.assertEqual(self.prepare(self.new_session())['state'], '已归档')
        self.assertEqual(len(self.writes), count)
        self.assertEqual(len(self.moves()), 1)

    def test_wrong_space_is_rejected_before_read_or_write(self):
        self.worker(); self.fake.calls.clear()
        with self.assertRaises(Error): ChatArchive(self.root / 'profile.json', '2', self.fake)
        self.assertEqual(self.fake.calls, [])

    def test_missing_identity_or_preview_match_cannot_execute(self):
        w = self.worker(); p = self.prepare(w)
        for change in ({'actor_id': 'other'}, {'message_id': ''}, {'conversation_id': ''},
                       {'user_text': ''}, {'preview_confirmation': 'some other plan'}):
            evidence = {**self.evidence(p), **change}
            with self.assertRaises(Error): w.confirm(p['confirmation_phrase'], evidence)
        self.assertEqual(self.moves(), [])

    def test_source_change_blocks_confirmation(self):
        w = self.worker(); p = self.prepare(w); self.fake.revision = 2
        with self.assertRaises(Error): w.confirm(p['confirmation_phrase'], self.evidence(p))
        self.assertEqual(self.moves(), [])

    def test_target_change_blocks_confirmation(self):
        w = self.worker(); p = self.prepare(w); self.fake.path = 'changed target'
        with self.assertRaises(Error): w.confirm(p['confirmation_phrase'], self.evidence(p))
        self.assertEqual(self.moves(), [])

    def test_prepare_must_not_reopen_uncertain_execution(self):
        w = self.worker(); self.prepare(w); self.rows[0]['状态'] = ['待核验']
        self.fake.revision = 2
        with self.assertRaises(Error): self.prepare(w)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.moves(), [])

    def test_publish_uncertainty_does_not_duplicate_record(self):
        w = self.worker(); original = w.cloud_write
        def lost_response(*args):
            original(*args)
            raise Error('response lost')
        w.cloud_write = lost_response
        with self.assertRaises(Error): self.prepare(w)
        self.assertEqual(self.prepare(self.new_session())['state'], '待人工确认')
        self.assertEqual(len(self.rows), 1)

    def test_publish_uncertainty_without_visible_row_stops(self):
        w = self.worker()
        w.cloud_write = lambda *args: (_ for _ in ()).throw(Error('uncertain'))
        with self.assertRaises(Error): self.prepare(w)
        other = self.new_session()
        with self.assertRaises(Error): self.prepare(other)
        self.assertEqual(self.writes, [])

    def test_minutes_not_accepted_as_native_docx(self):
        w = self.worker()
        with self.assertRaises(Error): w.prepare_source('https://test.feishu.cn/minutes/Minute123', 'Parent123')
        self.assertEqual(self.rows, [])

    def test_shared_lock_blocks_an_independent_process(self):
        w = self.worker()
        code = ('import sys;sys.path.insert(0,sys.argv[1]);'
                'from chat_archive import ChatArchive;'
                'w=ChatArchive(sys.argv[2],"1");'
                'lock=w.lock();lock.__enter__();lock.__exit__(None,None,None)')
        args = [sys.executable, '-c', code, str(Path(__file__).resolve().parents[1] / 'skills/lark-research-workspace/scripts'), str(self.root / 'profile.json')]
        with w.lock():
            result = subprocess.run(args, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('已有处理在运行', result.stderr)
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 0)

    def test_identical_titles_with_different_sources_require_disambiguation(self):
        w = self.worker(); p = self.prepare(w)
        duplicate = json.loads(json.dumps(self.rows[0]))
        content = json.loads(duplicate['预览内容']); content['source_id'] = 'docx:OtherDoc'
        duplicate.update(record_id='recOther', 预览内容=json.dumps(content), 计划指纹=digest(content), 内部编号='ARC-'+digest(content)[:12])
        self.rows.append(duplicate)
        with self.assertRaises(Error): w.confirm(p['confirmation_phrase'], self.evidence(p))
        self.assertEqual(self.moves(), [])

    def test_incomplete_shared_receipt_is_not_reported_as_success(self):
        w = self.worker(); self.prepare(w)
        self.rows[0]['状态'] = ['已归档']; self.rows[0]['结果链接'] = ''
        with self.assertRaises(Error): self.prepare(w)
        self.assertEqual(self.moves(), [])


if __name__ == '__main__': unittest.main(verbosity=2)
