# -*- coding: utf-8 -*-
"""PRD 解析：标题和节号、表格、页面大纲、组件规格卡。

约定见 references/prd-standard.md。这里只做读取，不做判断。
"""
import re
from pathlib import Path

LABELS = ['目的', '验收标准', '交互状态', '后台配置项', '文案', '数据字段和示例数据', '异常和边界']
ALIASES = {
    '功能目的': '目的',
    '交互态': '交互状态', '交互态展示': '交互状态', '交互状态展示': '交互状态', '状态机': '交互状态',
    '管理后台配置项': '后台配置项', '后台配置': '后台配置项', '配置项': '后台配置项',
    '数据字段': '数据字段和示例数据', '示例数据': '数据字段和示例数据',
    '数据字段与示例数据': '数据字段和示例数据', '数据和示例': '数据字段和示例数据',
    '异常与边界': '异常和边界', '边界和异常': '异常和边界', '异常边界': '异常和边界',
}
_ALL_LABELS = sorted(LABELS + list(ALIASES), key=len, reverse=True)

FENCE_RE = re.compile(r'^\s*(`{3,}|~{3,})(.*)$')
HEAD_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
NUM_RE = re.compile(r'^(\d+(?:\.\d+)*)\.?\s*(.*)$')
APPX_RE = re.compile(r'^附录\s*([A-Za-z])?\s*[:：.、]?\s*(.*)$')
CASE_RE = re.compile(r'^用例\s*(\d+)\s*[:：]?\s*(.*)$')
LIST_RE = re.compile(r'^(\s*)(?:[-*+]|\d+[.)])\s+(.*)$')
REF_RE = re.compile(r'[（(]\s*(?:(复用|全局)\s*)?(\d+(?:\.\d+)+)\s*(?:[，,][^）)]*)?[）)]')
LABEL_RE = re.compile(
    r'^(\s*)(?:[-*+]\s+)?(?:\*\*|__)?\s*(' + '|'.join(map(re.escape, _ALL_LABELS)) +
    r')\s*(?:\*\*|__)?\s*[:：]\s*(?:\*\*|__)?\s*(.*)$')
META_RE = re.compile(r'^>\s*(交付深度|产品形态|目标市场|状态)\s*[:：]\s*(.*)$')
NONE_WORDS = ('无', '暂无', '不涉及', '没有')


def load(path):
    """读文件，返回 (文本, 原来的换行符)。统一成 \\n 处理。"""
    text = Path(path).read_bytes().decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in text else '\n'
    return text.replace('\r\n', '\n').replace('\r', '\n'), newline


def save(path, text, newline='\n'):
    Path(path).write_bytes(text.replace('\n', newline).encode('utf-8'))


def strip_md(t):
    return re.sub(r'\*\*|__|`', '', t)


def strip_inline_code(t):
    return re.sub(r'`[^`]*`', '', t)


def clean_name(text):
    """去掉标记和强调符号，得到一个干净的名字。"""
    t = strip_md(text).replace('〔建议〕', '')
    t = re.sub(r'\[待定[^\]]*\].*$', '', t)
    return t.strip(' \t，,。；;：:')


def norm(name):
    """比较名字用：去掉所有空白。"""
    return re.sub(r'\s+', '', name or '')


def drop_paren(name):
    """去掉末尾的括号说明：「CTA 按钮区（核心）」→「CTA 按钮区」。"""
    return re.sub(r'\s*[（(][^（()）]*[)）]\s*$', '', name or '').strip()


def is_none_text(text):
    return re.sub(r'[\s\-*「」。.、]', '', text) in NONE_WORDS


def split_row(line):
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|') and not s.endswith('\\|'):
        s = s[:-1]
    return [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', s)]


class Head(object):
    def __init__(self, level, title, line):
        self.level, self.title, self.line = level, title, line
        self.num, self.name, self.kind, self.letter = None, title, 'other', None
        m = NUM_RE.match(title)
        if m and title[:1].isdigit():
            self.num, self.name, self.kind = m.group(1), m.group(2).strip(), 'num'
            return
        m = APPX_RE.match(title)
        if m:
            self.kind, self.letter = 'appx', (m.group(1) or '').upper()
            self.name = m.group(2).strip()
            return
        m = CASE_RE.match(title)
        if m:
            self.kind, self.num, self.name = 'case', m.group(1), m.group(2).strip()

    @property
    def label(self):
        if self.kind == 'num':
            return '%s %s' % (self.num, self.name)
        return self.title


class Table(object):
    def __init__(self, header, rows, line, end):
        self.header, self.rows, self.line, self.end = header, rows, line, end

    def col(self, *keys):
        """表头里第一个包含任一关键词的列号，找不到返回 None。"""
        for i, h in enumerate(self.header):
            if any(k in h for k in keys):
                return i
        return None

    @staticmethod
    def cell(row, idx):
        return row[idx].strip() if idx is not None and idx < len(row) else ''

    def data_rows(self):
        """至少有一格不为空的行。"""
        return [r for r in self.rows if any(c.strip() for c in r)]


class Node(object):
    """大纲里的一项。"""
    def __init__(self, text, line):
        self.text, self.line, self.children = text, line, []
        self.ref, self.kind = None, None
        ms = list(REF_RE.finditer(text))
        if ms:
            m = ms[-1]
            self.ref = m.group(2)
            self.kind = {'复用': 'reuse', '全局': 'global'}.get(m.group(1), 'own')
            text = text[:m.start()] + text[m.end():]
        self.name = clean_name(text)
        self.todo = '[待定' in self.text
        self.sugg = '〔建议〕' in self.text

    def walk(self):
        yield self
        for c in self.children:
            for n in c.walk():
                yield n


class Item(object):
    """规格卡里的一项：标签 + 内容。"""
    def __init__(self, label, line, first):
        self.label, self.line = label, line
        self.lines = [(line, first)]

    @property
    def end(self):
        return self.lines[-1][0] + 1

    def text(self):
        return '\n'.join(t for _, t in self.lines).strip()

    def is_empty(self):
        return not self.text()

    def is_none(self):
        return is_none_text(self.text())


class Doc(object):
    def __init__(self, text, path=None):
        self.path = Path(path) if path else None
        self.raw = text.split('\n')
        clean = re.sub(r'<!--.*?-->', lambda m: re.sub(r'[^\n]', '', m.group(0)), text, flags=re.S)
        self.lines = clean.split('\n')
        self.in_code, self.blocks = self._scan_code()
        self.heads, self.by_num, self.dups = [], {}, []
        for i, line in enumerate(self.lines):
            if self.in_code[i]:
                continue
            m = HEAD_RE.match(line)
            if not m:
                continue
            title = re.sub(r'\s+#+$', '', m.group(2)).replace('**', '').replace('&#x20;', ' ').strip()
            if not title:
                continue
            h = Head(len(m.group(1)), title, i)
            self.heads.append(h)
            if h.kind == 'num':
                if h.num in self.by_num:
                    self.dups.append(h)
                else:
                    self.by_num[h.num] = h
        self.meta = {}
        for line in self.lines[:40]:
            m = META_RE.match(line.strip())
            if m:
                self.meta[m.group(1)] = m.group(2).strip()

    # ---- 基础 ----
    def _scan_code(self):
        in_code, blocks, fence, start, info = [False] * len(self.raw), [], None, 0, ''
        for i, line in enumerate(self.raw):
            m = FENCE_RE.match(line)
            if fence is None:
                if m:
                    fence, start, info = m.group(1)[0], i, m.group(2).strip()
                    in_code[i] = True
            else:
                in_code[i] = True
                if m and m.group(1)[0] == fence and not m.group(2).strip():
                    blocks.append((start, i, info))
                    fence = None
        if fence is not None:
            blocks.append((start, len(self.raw) - 1, info))
        return in_code, blocks

    @property
    def product(self):
        for h in self.heads:
            if h.level == 1 and h.kind == 'other':
                name = re.sub(r'[\s\-—·]*PRD\s*$', '', h.title, flags=re.I).strip()
                if name:
                    return name
        if self.path:
            return re.sub(r'[\s\-—_]*PRD$', '', self.path.stem, flags=re.I) or self.path.stem
        return '产品'

    @property
    def level(self):
        v = self.meta.get('交付深度', '')
        for k in ('原型级', '前端级'):
            if k in v and '|' not in v:
                return k
        return None

    def sec(self, num):
        return self.by_num.get(num)

    def appx(self, letter):
        for h in self.heads:
            if h.kind == 'appx' and h.letter == letter:
                return h
        return None

    def end_full(self, h):
        for x in self.heads:
            if x.line > h.line and x.level <= h.level:
                return x.line
        return len(self.lines)

    def end_own(self, h):
        for x in self.heads:
            if x.line > h.line:
                return x.line
        return len(self.lines)

    def head_at(self, line):
        cur = None
        for h in self.heads:
            if h.line > line:
                break
            cur = h
        return cur

    def where(self, line):
        h = self.head_at(line)
        return h.label if h else '文件开头'

    def text_of(self, start, end, code=False):
        return '\n'.join(self.lines[i] for i in range(start, end) if code or not self.in_code[i])

    # ---- 第 3 章 ----
    def pages(self):
        return [h for h in self.heads if h.kind == 'num' and re.fullmatch(r'3\.[1-9]\d*', h.num)]

    def globals_(self):
        return [h for h in self.heads if h.kind == 'num' and re.fullmatch(r'3\.0\.\d+', h.num)]

    def comps(self, page=None):
        pat = r'3\.%s\.\d+' % (re.escape(page.num.split('.')[1]) if page else r'[1-9]\d*')
        return [h for h in self.heads if h.kind == 'num' and re.fullmatch(pat, h.num)]

    @staticmethod
    def is_reuse(h):
        return '复用' in h.name

    def cards(self):
        """所有要按七项检查的组件：全局组件 + 各页组件（不含「复用」节）。"""
        return [h for h in self.globals_() + self.comps() if not self.is_reuse(h)]

    def ch3_range(self):
        h = self.sec('3')
        if h:
            return h.line, self.end_full(h)
        hs = [x for x in self.heads if x.kind == 'num' and x.num.startswith('3.')]
        if not hs:
            return 0, 0
        return hs[0].line, max(self.end_full(x) for x in hs)

    def cases(self):
        h = self.sec('4.3')
        if not h:
            return []
        e = self.end_full(h)
        return [x for x in self.heads if x.kind == 'case' and h.line < x.line < e]

    # ---- 表格 ----
    def tables(self, start, end):
        out, i = [], start
        while i < end - 1:
            a = self.lines[i].strip()
            if not self.in_code[i] and a.startswith('|'):
                b = self.lines[i + 1].strip()
                sep = split_row(b)
                if b.startswith('|') and sep and all(re.fullmatch(r':?-+:?', c.replace(' ', '')) for c in sep):
                    rows, j = [], i + 2
                    while j < end and not self.in_code[j] and self.lines[j].strip().startswith('|'):
                        rows.append(split_row(self.lines[j]))
                        j += 1
                    out.append(Table(split_row(a), rows, i, j))
                    i = j
                    continue
            i += 1
        return out

    # ---- 大纲 ----
    def outline(self, page):
        """返回 (第一层节点列表, 有没有「页面结构」标记行)。"""
        start, end = page.line + 1, self.end_own(page)
        marked = False
        for i in range(start, end):
            if not self.in_code[i] and '页面结构' in self.lines[i] and not LIST_RE.match(self.lines[i]):
                start, marked = i + 1, True
                break
        roots, stack, started = [], [], False
        for i in range(start, end):
            line = self.lines[i]
            if self.in_code[i]:
                if started:
                    break
                continue
            m = LIST_RE.match(line)
            if m:
                started = True
                indent = len(m.group(1).expandtabs(4))
                node = Node(m.group(2).strip(), i)
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                (stack[-1][1].children if stack else roots).append(node)
                stack.append((indent, node))
            elif line.strip() and started and not line.startswith((' ', '\t')):
                break
        return roots, marked

    # ---- 规格卡 ----
    def card(self, head):
        """返回 {标准标签: Item}。"""
        items, cur, base = {}, None, None
        for i in range(head.line + 1, self.end_full(head)):
            line = self.lines[i]
            m = None if self.in_code[i] else LABEL_RE.match(line)
            if m:
                indent = len(m.group(1).expandtabs(4))
                if base is None:
                    base = indent
                if indent <= base + 1:
                    label = ALIASES.get(m.group(2), m.group(2))
                    if label in items:
                        cur = items[label]
                        cur.lines.append((i, m.group(3)))
                    else:
                        cur = items[label] = Item(label, i, m.group(3))
                    continue
            if cur is not None:
                cur.lines.append((i, line))
        return items

    def item_tables(self, item):
        return self.tables(item.line, item.end)


def open_doc(path):
    text, newline = load(path)
    doc = Doc(text, path)
    doc.newline = newline
    return doc
