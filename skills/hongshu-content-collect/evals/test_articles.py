"""Two article questions: body byline preservation and partial-batch saving."""
import argparse
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from extract_weixin import extract
import weixin_collect as collect


class ArticleTests(unittest.TestCase):
    def test_personal_byline_stays_in_body(self):
        html = ('<meta property="og:title" content="阅读分享">'
                '<meta name="author" content="张三"><span id="js_name">读书号</span>'
                '<div id="js_content"><p>作者：张三</p><p>今天分享一本好书。</p>'
                '</div>')
        item = extract(html)
        with tempfile.TemporaryDirectory() as directory:
            body = Path(directory) / 'body.md'
            body.write_text(item['body'], encoding='utf-8')
            item.update(index='01', body_path=str(body), input_url='https://mp.weixin.qq.com/s/fixture')
            saved = collect.note_text(item, {'tags': ['阅读']})
        self.assertIn('作者：张三', saved.split('---', 2)[2])

    def test_blocked_item_does_not_block_ready_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'notes'
            body = root / 'body.md'
            body.write_text('今天分享一本好书。', encoding='utf-8')
            ready = {'index': '01', 'status': 'ready', 'body_path': str(body),
                     'body_sha256': collect.body_metrics(body.read_text(encoding='utf-8'))['sha256'],
                     'source_title': '阅读分享', 'account': '读书号', 'published_at': '2026-11-12',
                     'canonical_url': 'https://mp.weixin.qq.com/s/fixture',
                     'input_url': 'https://mp.weixin.qq.com/s/fixture'}
            manifest = root / 'manifest.json'
            decisions = root / 'decisions.json'
            collect.write_json(manifest, {'vault_root': str(output), 'output_dir': str(output),
                                         'items': [ready, {'index': '02', 'status': 'needs_chrome'}]})
            collect.write_json(decisions, {'items': [{'index': '01', 'tags': ['阅读']}]})
            args = argparse.Namespace(manifest=manifest, vault_root=None,
                                      decisions=decisions, feedback_out=None)
            with contextlib.redirect_stdout(io.StringIO()):
                collect.finish_command(args)
            self.assertEqual(len(list(output.glob('*.md'))), 1)


if __name__ == '__main__':
    unittest.main()
