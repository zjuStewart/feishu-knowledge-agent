"""Exercise multiple background branches without touching live documents."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/lark-research-workspace/scripts'))
from init_workspace import initialize
from workspace import Workspace, Error, write
spec = importlib.util.spec_from_file_location('multiple_root_directory', ROOT / 'skills/lark-wiki-directory/scripts/refresh_directory.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)

def node(token, parent='', child=False):
    return {'node_token':token, 'obj_token':'Doc'+token, 'obj_type':'docx',
            'parent_node_token':parent, 'title':token, 'has_child':child, 'space_id':'1'}

class MultipleBackgroundRoots(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def initialize(self, roots):
        return initialize(self.root/'personal', 'https://example.feishu.cn', '1', '测试', roots, ROOT/'skills')
    def test_initialization_keeps_all_roots_and_deduplicates(self):
        result = self.initialize(['A', 'B', 'A']); w = Workspace(result['profile'])
        self.assertEqual(w.settings['shared_context_roots'], ['A', 'B'])
        self.assertEqual(w.settings['shared_context_root'], 'A')
    def test_empty_roots_are_rejected_without_creating_workspace(self):
        for roots in ([], ['A', ''], ['A', None]):
            with self.assertRaises(ValueError): self.initialize(roots)
        self.assertFalse((self.root/'personal').exists())
    def test_directory_unions_branches_and_overlapping_roots(self):
        result = self.initialize(['A', 'B', 'Child']); sync.configure(Path(result['directory_profile']))
        def pages(parent, cursor=None):
            return {'has_more':False, 'nodes':([node('A', child=True), node('B'), node('Other')]
                    if parent is None else [node('Child', 'A')])}
        with patch.object(sync, 'list_nodes', pages): status = sync.refresh()
        mapping = json.loads((self.root/'personal/directory/knowledge-map.json').read_text())
        self.assertEqual(status['shared_context_nodes'], 3); self.assertTrue(status['shared_context_root_visible'])
        self.assertEqual({n['node_token'] for n in mapping['nodes'] if n['shared_context']}, {'A','B','Child'})
        with patch.object(sync, 'list_nodes', return_value={'has_more':False,'nodes':[node('A')]}): status = sync.refresh()
        self.assertFalse(status['shared_context_root_visible'])
        self.assertEqual(status['missing_shared_context_roots'], ['B','Child']); self.assertTrue(status['needs_user_action'])
    def test_missing_second_root_clears_bundle_and_blocks_answers(self):
        result = self.initialize(['A', 'B']); w = Workspace(result['profile']); mapping = []
        for token in ('A', 'B'):
            d = {'document_id':'Doc'+token, 'title':token, 'url':'https://example.feishu.cn/wiki/'+token,
                 'revision':1, 'hash':token, 'text':'科研证据'+token, 'active':True, 'shared_context':True,
                 'wiki_managed':True, 'path':token}
            w.save('documents/Doc'+token+'.json', d)
            mapping.append({**node(token), 'shared_context':True, 'path':token, 'url':d['url']})
        write(w.cfg['directory'], {'directory_complete':True, 'nodes':mapping})
        self.assertEqual(len(w.build_context()['sources']), 2)
        write(w.cfg['directory'], {'directory_complete':True, 'nodes':mapping[:1]})
        bundle = w.build_context(); self.assertFalse(bundle['valid']); self.assertEqual(bundle['parts'], [])
        self.assertEqual(bundle['missing_shared_context_roots'], ['B'])
        with self.assertRaises(Error): w.query('科研证据')

if __name__ == '__main__': unittest.main()
