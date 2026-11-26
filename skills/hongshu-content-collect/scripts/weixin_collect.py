#!/usr/bin/env python3
"""Prepare, save and verify faithful WeChat article batches."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from zoneinfo import ZoneInfo

from extract_weixin import body_metrics, canonical_body, extract
try:
    from media_common import executable as _find_executable
except Exception:
    _find_executable = lambda name: name

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36'


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def emit(stage, **fields):
    print(json.dumps({'stage': stage, **fields}, ensure_ascii=False), flush=True)


def gather_urls(values, url_file):
    if url_file:
        values = values + url_file.read_text(encoding='utf-8').splitlines()
    urls = list(dict.fromkeys(s.strip() for s in values if s.strip() and not s.strip().startswith('#')))
    if not urls or any(not re.match(r'^https?://mp\.weixin\.qq\.com/', u) for u in urls):
        raise ValueError('supply mp.weixin.qq.com article URLs')
    return urls


def find_existing_note(vault, urls):
    for path in sorted(vault.rglob('*.md')):
        with path.open(encoding='utf-8') as note:
            if note.readline().strip() != '---':
                continue
            for line in note:
                if line.strip() == '---':
                    break
                key, separator, value = line.partition(':')
                if separator and key.strip() == '原文链接' and value.strip().strip('\"\'') in urls:
                    return str(path.resolve())
    return ''


def fetch_html(url, output, timeout):
    result = subprocess.run([
        _find_executable('curl'), '--location', '--compressed', '--fail-with-body', '--silent', '--show-error',
        '--max-time', str(timeout), '--user-agent', USER_AGENT,
        '--referer', 'https://mp.weixin.qq.com/', '--output', str(output), url,
    ], text=True, capture_output=True)
    output.with_name('fetch.log').write_text(
        f'EXIT: {result.returncode}\n{result.stdout}{result.stderr}', encoding='utf-8')
    kind = ''
    if result.returncode in {5, 6, 7, 28} or re.search(
        r'could not resolve host|failed to connect|operation timed out|network is unreachable',
        result.stderr, re.I,
    ):
        kind = 'network_unavailable'
    elif result.returncode:
        kind = 'http_fetch_failed'
    elif not output.is_file() or not output.stat().st_size:
        kind = 'empty_response'
    if kind and output.exists():
        output.replace(output.with_name('rejected.html'))
    return kind, result.stderr.strip()


def _weixin_url_mismatch(input_url: str, page_url: str) -> bool:
    if not input_url or not page_url:
        return False
    u1, u2 = urlsplit(input_url.strip()), urlsplit(page_url.strip())
    if u2.hostname and not u2.hostname.lower().endswith('weixin.qq.com'):
        return True
    m1 = re.fullmatch(r'/s/([A-Za-z0-9_-]+)', u1.path.rstrip('/'))
    m2 = re.fullmatch(r'/s/([A-Za-z0-9_-]+)', u2.path.rstrip('/'))
    if m1 and m2:
        return m1.group(1) != m2.group(1)
    q1, q2 = parse_qs(u1.query), parse_qs(u2.query)
    shared = [k for k in ('__biz', 'mid', 'sn', 'idx') if k in q1 and k in q2]
    return any(q1[k] != q2[k] for k in shared)


def prepare_one(index, url, work, vault, args):
    item = {'index': f'{index:02d}', 'input_url': url}
    existing = find_existing_note(vault, [url])
    if existing:
        return dict(item, status='existing', existing_path=existing)
    folder = work / f'item-{index:02d}'
    folder.mkdir(parents=True, exist_ok=True)
    html = folder / 'article.html'
    item.update(item_dir=str(folder), body_path=str(folder / 'body.md'))
    explicit_src = (
        args.html.expanduser().resolve() if getattr(args, 'html', None)
        else ((args.html_dir / folder.name / 'article.html').resolve() if args.html_dir and (args.html_dir / folder.name / 'article.html').is_file() else None)
    )
    if explicit_src is not None:
        if not explicit_src.is_file() or not explicit_src.stat().st_size:
            raise FileNotFoundError(f'explicit HTML missing or empty: {explicit_src}')
        if explicit_src != html.resolve():
            shutil.copy2(explicit_src, html)
    data = extract(html.read_text(encoding='utf-8', errors='replace')) if html.exists() else None
    if data and _weixin_url_mismatch(url, data.get('canonical_url', '')):
        html.replace(folder / 'rejected.html')
        if explicit_src is not None:
            return dict(item, status='needs_chrome', canonical_url=data.get('canonical_url', ''),
                        error='传入 HTML 的页面文章链接与目标链接不匹配，请确认保存的是同一篇文章',
                        risk_flags=['html_url_mismatch'])
        data = None
    if data and not data['is_article']:
        html.replace(folder / 'rejected.html')
        if explicit_src is not None:
            return dict(item, status='needs_chrome', blocked_markers=data.get('blocked_markers', []),
                        error='显式传入的 HTML 为验证页或缺少正文容器，请在已登录桌面浏览器加载正文后重新保存',
                        risk_flags=data['reasons'])
        data = None
    if data is None:
        kind, error = fetch_html(url, html, args.timeout)
        if kind:
            return dict(item, status='needs_chrome', fetch_error_kind=kind,
                        fetch_error=error, risk_flags=['fetch_failed', kind])
        data = extract(html.read_text(encoding='utf-8', errors='replace'))
        if _weixin_url_mismatch(url, data.get('canonical_url', '')):
            html.replace(folder / 'rejected.html')
            return dict(item, status='needs_chrome', canonical_url=data.get('canonical_url', ''),
                        error='抓取结果链接与目标文章不匹配', risk_flags=['html_url_mismatch'])
    valid = data.pop('is_article')
    flags = data.pop('reasons')
    (folder / 'body.md').write_text(data.pop('body') + '\n', encoding='utf-8')
    if not valid:
        html.replace(folder / 'rejected.html')
    else:
        flags += [f'missing_{key}' for key in ('account', 'author', 'published_at') if not data[key]]
    canonical = data['canonical_url'] or url
    existing = find_existing_note(vault, [canonical]) if canonical != url else ''
    data.update(source_title=data.pop('title'), canonical_url=canonical)
    return dict(item, **data, status='existing' if existing else 'ready' if valid else 'needs_chrome',
                existing_path=existing, risk_flags=flags)


def prepare_command(args):
    urls = gather_urls(args.urls, args.url_file)
    if getattr(args, 'html', None) and len(urls) != 1:
        raise ValueError('--html only applies to a single URL; use --html-dir or item-XX/article.html for batches')
    directory = args.output_dir.resolve()
    work = args.work_dir.resolve() if args.work_dir else Path(tempfile.mkdtemp(prefix='weixin-mp-collect.'))
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = work / 'manifest.json'
    if manifest_path.exists():
        old = load_json(manifest_path)
        vault = Path(old['vault_root'])
        if (old['input_urls'] != urls or args.vault_root and args.vault_root.resolve() != vault
                or Path(old.get('output_dir', directory)) != directory):
            raise ValueError('workdir belongs to different URLs, directory or search scope')
    else:
        vault = (args.vault_root or directory).resolve()
    manifest = {'schema_version': 3, 'vault_root': str(vault), 'output_dir': str(directory),
                'input_urls': urls, 'items': []}
    write_json(manifest_path, manifest)
    emit('prepare', status='started', workdir=str(work), total=len(urls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(urls)))) as pool:
        futures = [pool.submit(prepare_one, i, url, work, vault, args)
                   for i, url in enumerate(urls, 1)]
        for future in concurrent.futures.as_completed(futures):
            manifest['items'].append(future.result())
    manifest['items'].sort(key=lambda item: item['index'])
    manifest['status'] = 'prepared'
    write_json(manifest_path, manifest)
    blocked = sum(item['status'] == 'needs_chrome' for item in manifest['items'])
    emit('prepare', status='partial' if blocked else 'complete', blocked=blocked,
         manifest=str(manifest_path))
    return 2 if blocked else 0


def note_text(item, decision):
    body = canonical_body(Path(item['body_path']).read_text(encoding='utf-8'))
    if body_metrics(body)['sha256'] != item['body_sha256']:
        raise ValueError(f"item-{item['index']}: prepared body changed")
    tags = decision.get('tags', [])
    if not isinstance(tags, list) or not 1 <= len(tags) <= 2 or not all(
        isinstance(t, str) and t.strip() for t in tags
    ):
        raise ValueError('tags must contain 1-2 nonempty strings')
    header = ['---', f"发布日期: {item.get('published_at', '')}",
              '平台: 微信公众号',
              f"原文链接: {json.dumps(item.get('canonical_url') or item['input_url'], ensure_ascii=False)}",
              f"作者: {json.dumps(item.get('account', ''), ensure_ascii=False)}",
              '点赞数:', '内容类型: 图文', '标签:',
              *(f'  - {json.dumps(t.strip(), ensure_ascii=False)}' for t in tags), '---']
    return '\n'.join(header) + '\n\n' + body + '\n'


def validate_saved(item, expected):
    saved = Path(item['output_path']).read_text(encoding='utf-8')
    if saved != expected:
        raise ValueError(f"item-{item['index']}: saved note differs from prepared text/fields")
    item['validation'] = {'status': 'passed',
                          'body_sha256': body_metrics(saved.split('---', 2)[2])['sha256']}


def finish_command(args):
    manifest_path = args.manifest.resolve()
    manifest = load_json(manifest_path)
    vault = Path(manifest['vault_root'])
    if args.vault_root and args.vault_root.resolve() != vault:
        raise ValueError('finish Vault differs from prepared Vault')
    directory = Path(manifest['output_dir'])
    intake_date = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    decisions = {str(d['index']).zfill(2): d for d in load_json(args.decisions)['items']}
    plans = []
    for item in manifest['items']:
        status = item['status']
        if status == 'existing':
            if not Path(item['existing_path']).is_file():
                raise FileNotFoundError(item['existing_path'])
            continue
        if status not in {'ready', 'written'}:
            continue  # Preserve blocked items; save the ready part of this fixed selection.
        decision = item if status == 'written' else decisions[item['index']]
        filename_date = item.get('published_at') or intake_date
        name = f"{filename_date[2:].replace('-', '.')}-{item['source_title']}"
        name = name.translate(str.maketrans(':*?"<>|\\/', '：＊？＂＜＞｜＼／'))
        name = re.sub(r'[\x00-\x1f]', '_', name).rstrip(' .') + '.md'
        path = directory / name
        expected = note_text(item, decision)
        if status == 'written':
            validate_saved(item, expected)
            continue
        if path.exists():
            existing = find_existing_note(path.parent, [item['canonical_url']])
            if not existing:
                raise FileExistsError(f'target exists; choose another filename: {path}')
            item.update(status='existing', existing_path=existing)
            continue
        plans.append((item, path, decision, expected))
    for item, path, decision, expected in plans:
        path.parent.mkdir(parents=True, exist_ok=True)
        item.update(status='written', output_path=str(path), output_stem=path.stem,
                    tags=decision['tags'], intake_date=intake_date,
                    validation={'status': 'pending'})
        write_json(manifest_path, manifest)
        with path.open('x', encoding='utf-8') as output:
            output.write(expected)
        validate_saved(item, expected)
        write_json(manifest_path, manifest)
    paths = [Path(i['existing_path'] if i['status'] == 'existing' else i['output_path'])
             for i in manifest['items'] if i['status'] in {'existing', 'written'}]
    destinations = sorted({str(path.parent) for path in paths})
    feedback = args.feedback_out or manifest_path.parent / 'feedback.md'
    links = [f'[{path.stem}]({quote(str(path), safe="/" )})' for path in paths]
    warnings = [f"《{i['source_title']}》未取得原始发布日期，文件名使用录入日期 "
                f"{i['intake_date']}（Asia/Shanghai）；发布日期属性留空。"
                for i in manifest['items'] if i['status'] == 'written' and not i.get('published_at')]
    feedback.write_text('文件位置：\n' + '\n'.join(f'- `{p}`' for p in destinations)
                        + '\n\n' + '\n\n'.join(links + warnings) + '\n', encoding='utf-8')
    blocked = sum(i['status'] not in {'existing', 'written'} for i in manifest['items'])
    manifest.update(status='partial' if blocked else 'complete', feedback=str(feedback), destinations=destinations)
    write_json(manifest_path, manifest)
    emit('finish', status=manifest['status'], blocked=blocked, written=len(plans), existing=len(paths)-len(plans),
         manifest=str(manifest_path), feedback=str(feedback))
    return 2 if blocked else 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('urls', nargs='*')
    prepare.add_argument('--url-file', type=Path)
    prepare.add_argument('--work-dir', type=Path)
    prepare.add_argument('--html', type=Path)
    prepare.add_argument('--html-dir', type=Path)
    prepare.add_argument('--output-dir', type=Path, required=True)
    prepare.add_argument('--vault-root', type=Path)
    prepare.add_argument('--workers', type=int, default=8)
    prepare.add_argument('--timeout', type=int, default=60)
    prepare.set_defaults(func=prepare_command)
    finish = sub.add_parser('finish')
    finish.add_argument('--manifest', type=Path, required=True)
    finish.add_argument('--decisions', type=Path, required=True)
    finish.add_argument('--vault-root', type=Path)
    finish.add_argument('--feedback-out', type=Path)
    finish.set_defaults(func=finish_command)
    return parser


def main():
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except Exception as error:
        emit(args.command, status='failed', error=str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
