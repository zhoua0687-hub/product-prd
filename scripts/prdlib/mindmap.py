# -*- coding: utf-8 -*-
"""思维导图：从第 3 章的页面大纲生成网页导图、Markdown 大纲、OPML。"""
import re
import json
from pathlib import Path
from xml.sax.saxutils import quoteattr

from .parse import strip_md, save, open_doc
from .gen import safe_name

TEMPLATE = Path(__file__).resolve().parent / 'mindmap_template.html'


def _short(text, limit=110):
    t = re.sub(r'\s+', ' ', strip_md(text).replace('〔建议〕', '')).strip()
    return t if len(t) <= limit else t[:limit - 1] + '…'


def _facts(doc, h):
    """组件的目的、状态名、配置项数量，给导图的说明面板用。"""
    out = {}
    if not h or doc.is_reuse(h):
        return out
    items = doc.card(h)
    it = items.get('目的')
    if it and not it.is_empty() and not it.is_none():
        out['d'] = _short(it.text())
    it = items.get('交互状态')
    if it and not it.is_none():
        names = []
        for t in doc.item_tables(it):
            ci = t.col('状态') or 0
            names += [_short(t.cell(r, ci), 24) for r in t.data_rows() if t.cell(r, ci)]
        if names:
            out['st'] = names
    it = items.get('后台配置项')
    if it and not it.is_none():
        n = 0
        for t in doc.item_tables(it):
            ci = t.col('配置项')
            if ci is not None:
                n += len([r for r in t.data_rows() if t.cell(r, ci)])
        if n:
            out['cf'] = n
    return out


def _conv(doc, n):
    d = {'t': n.name or '（未命名）', 'k': 'part', 'c': [_conv(doc, c) for c in n.children]}
    if n.ref:
        d['n'] = n.ref
        d['k'] = {'own': 'comp', 'reuse': 'reuse', 'global': 'global'}[n.kind]
        d.update(_facts(doc, doc.sec(n.ref)))
    elif any(x.ref for x in n.walk()):
        d['k'] = 'group'   # 不带节号、下面有组件的一项：页面上的一个区域
    if n.todo:
        d['q'] = 1
    if n.sugg:
        d['s'] = 1
    return d


def _page_intro(doc, p):
    for i in range(p.line + 1, doc.end_own(p)):
        s = doc.lines[i].strip()
        if not s or doc.in_code[i]:
            continue
        if '页面结构' in s or s.startswith(('-', '*', '|', '#')):
            break
        return _short(s)
    return ''


def split_entry(name):
    """页面标题写成「入口名：页面名」时拆开，返回 (入口名, 页面名)；没有冒号返回 (None, 原名)。"""
    if '：' in (name or ''):
        a, b = name.split('：', 1)
        if a.strip() and b.strip():
            return a.strip(), b.strip()
    return None, name


def build_tree(doc):
    root = {'t': doc.product, 'k': 'root', 'c': []}
    globs = [g for g in doc.globals_() if not doc.is_reuse(g)]
    if globs:
        root['c'].append({'t': '全局组件', 'n': '3.0', 'k': 'page', 'c': [
            dict({'t': g.name or '（未命名）', 'n': g.num, 'k': 'comp', 'c': []}, **_facts(doc, g)) for g in globs]})
    tabs = {}   # 有底部导航的产品：先按入口（标签）归组，再到页面
    for p in doc.pages():
        roots, _ = doc.outline(p)
        entry, pname = split_entry(p.name)
        node = {'t': pname or '（未命名页面）', 'n': p.num, 'k': 'page', 'c': [_conv(doc, n) for n in roots]}
        intro = _page_intro(doc, p)
        if intro:
            node['d'] = intro
        if entry is None:
            root['c'].append(node)
            continue
        if entry not in tabs:
            tabs[entry] = {'t': entry, 'k': 'tab', 'c': []}
            root['c'].append(tabs[entry])
        tabs[entry]['c'].append(node)
    return root


def _label(n):
    if n['k'] == 'comp':
        return '%s（%s）' % (n['t'], n['n'])
    if n['k'] == 'reuse':
        return '%s（复用 %s）' % (n['t'], n['n'])
    if n['k'] == 'global':
        return '%s（全局 %s）' % (n['t'], n['n'])
    if n['k'] == 'page':
        return '%s %s' % (n['n'], n['t'])
    return n['t']


def to_markdown(tree):
    out = ['# %s' % tree['t'], '']

    def walk(n, depth):
        out.append('%s- %s' % ('  ' * depth, _label(n)))
        for c in n['c']:
            walk(c, depth + 1)

    for page in tree['c']:
        out += ['## %s' % _label(page), '']
        for c in page['c']:
            walk(c, 0)
        out.append('')
    return '\n'.join(out)


def to_opml(tree):
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">',
           '  <head><title>%s 页面结构</title></head>' % tree['t'].replace('&', '&amp;').replace('<', '&lt;'),
           '  <body>']

    def walk(n, depth):
        pad = '  ' * (depth + 2)
        if n['c']:
            out.append('%s<outline text=%s>' % (pad, quoteattr(_label(n))))
            for c in n['c']:
                walk(c, depth + 1)
            out.append('%s</outline>' % pad)
        else:
            out.append('%s<outline text=%s/>' % (pad, quoteattr(_label(n))))

    walk(tree, 0)
    out += ['  </body>', '</opml>', '']
    return '\n'.join(out)


def to_html(tree):
    data = json.dumps(tree, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    title = '%s · 页面结构' % tree['t']
    html = TEMPLATE.read_text(encoding='utf-8')
    return html.replace('__TITLE__', title.replace('&', '&amp;').replace('<', '&lt;')).replace('__DATA__', data)


def cmd_mindmap(path, out_dir=None):
    doc = open_doc(path)
    if not doc.pages():
        print('第 3 章还没有页面（## 3.1 页面名），导图先不生成。')
        return 1
    tree = build_tree(doc)
    empty = [p['n'] + ' ' + p['t'] for p in _walk(tree) if p['k'] == 'page' and p.get('n') != '3.0' and not p['c']]
    base = Path(out_dir) if out_dir else doc.path.parent
    base.mkdir(parents=True, exist_ok=True)
    stem = '%s-页面结构' % safe_name(doc.product)
    save(base / (stem + '.html'), to_html(tree))
    save(base / (stem + '.md'), to_markdown(tree))
    save(base / (stem + '.opml'), to_opml(tree))
    n_comp = sum(1 for x in _walk(tree) if x['k'] == 'comp')
    print('已生成思维导图（%d 个页面，%d 个组件）：' % (len(doc.pages()), n_comp))
    print('  %s　← 用浏览器打开' % (base / (stem + '.html')))
    print('  %s　← 可导入 XMind 等工具' % (base / (stem + '.opml')))
    print('  %s　← 纯文字大纲' % (base / (stem + '.md')))
    if empty:
        print('注意：这些页面还没有大纲，导图里是空的：%s' % '、'.join(empty))
    return 0


def _walk(n):
    yield n
    for c in n['c']:
        for x in _walk(c):
            yield x
