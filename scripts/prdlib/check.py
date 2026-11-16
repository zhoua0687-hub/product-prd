# -*- coding: utf-8 -*-
"""PRD 一致性检查：找出做原型的 AI 会停下来猜的地方。"""
import re
import difflib
from collections import OrderedDict

from .parse import (LABELS, REF_RE, LIST_RE, strip_inline_code, strip_md, clean_name,
                    norm, drop_paren, split_row)

VAGUE = ['流畅', '顺畅', '丝滑', '友好', '美观', '好看', '精美', '合理', '适当', '适量', '适中',
         '尽量', '尽可能', '清晰', '显著', '明显', '醒目', '若干', '等等', '之类', '较长', '较短',
         '较大', '较小', '较多', '较少', '几秒', '一些', '大概', '大约']
TYPES = ['文本', '长文本', '富文本', '图片列表', '图片', '视频', '链接', '数字', '开关', '时间',
         '单选', '多选', '列表']
MARKET_ROWS = ['主市场', '时区', '登录', '分享', '合规', '设备']
CJK_LANG = ('中文', '汉语', '简体', '繁体', '粤语', '国语', '普通话', 'Chinese', '日语', '日文',
            '韩语', '韩文', 'Japanese', 'Korean')
REQUIRED = [('1.1', '项目背景'), ('1.2', '产品定位'), ('1.3', '核心价值'), ('1.4', '目标市场'),
            ('1.5', '范围和优先级'), ('2.1', '用户流程图'), ('2.2', '状态字典'),
            ('3.0', '全局组件和通用规则'), ('4.1', '平台和技术约束'), ('4.2', '后台配置总表'),
            ('4.3', '整页验收用例')]
TODO_RE = re.compile(r'\[待定\s*Q?\s*(\d+)\s*\]')
TODO_BARE_RE = re.compile(r'\[待定\s*\]')
BRACKET_RE = re.compile(r'【([^【】\n]+)】')


class Report(object):
    def __init__(self):
        self.errors, self.warns, self.stats = [], [], OrderedDict()

    def err(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warns.append((where, msg))


def _has_content(doc, start, end):
    """这一段除了表头、空表格行、空标签之外，有没有实际内容。"""
    for i in range(start, end):
        s = doc.lines[i].strip()
        if not s or s.startswith('#') or s.startswith('|'):
            continue
        if doc.in_code[i]:
            return True
        s = re.sub(r'^([-*+]|\d+[.)])\s*', '', s)
        s = re.sub(r'^\*\*[^*]+\*\*\s*[:：]?\s*', '', s)
        s = re.sub(r'^\*\*[^*]+[:：]\*\*\s*', '', s)
        if s.strip('：: '):
            return True
    for t in doc.tables(start, end):
        for row in t.rows:
            if any(c.strip() for c in (row[1:] if len(row) > 1 else row)):
                return True
    return False


def check_header(doc, r):
    if not doc.level:
        r.err('文件头', '「交付深度」要写成「原型级」或「前端级」其中一个')
    for k in ('产品形态', '目标市场'):
        if not doc.meta.get(k):
            r.warn('文件头', '「%s」还没填' % k)
    if not any(h.level == 1 and h.kind == 'other' for h in doc.heads):
        r.warn('文件头', '第一行应是「# <产品名> PRD」')


def check_sections(doc, r):
    for num, name in REQUIRED:
        h = doc.sec(num)
        if not h:
            r.err('结构', '缺少 %s %s' % (num, name))
        elif num not in ('4.2', '4.3') and not _has_content(doc, h.line + 1, doc.end_full(h)):
            r.err(h.label, '这一节是空的')
    for h in doc.dups:
        r.err(h.label, '节号 %s 重复了（第 %d 行）' % (h.num, h.line + 1))
    if not doc.appx('A'):
        r.err('结构', '缺少 附录 A 待定问题清单')
    b = doc.appx('B')
    if not b:
        r.err('结构', '缺少 附录 B 决策记录')
    elif not any(t.data_rows() for t in doc.tables(b.line, doc.end_full(b))):
        r.warn('附录 B', '决策记录是空的：使用者定过的事记一笔')
    pages = doc.pages()
    if not pages:
        r.err('结构', '第 3 章至少要有一个页面（## 3.1 页面名）')
    for p in pages:
        if not p.name:
            r.err(p.label, '页面没有名字')
        if not doc.comps(p):
            r.err(p.label, '这个页面下面没有组件说明（### %s.1 组件名）' % p.num)


def check_market(doc, r):
    """返回界面语言那一格的内容。"""
    h = doc.sec('1.4')
    if not h:
        return ''
    rows = {}
    for t in doc.tables(h.line, doc.end_full(h)):
        for row in t.rows:
            if row and row[0].strip():
                rows[strip_md(row[0])] = ' '.join(row[1:]).strip()
    if not rows:
        if _has_content(doc, h.line + 1, doc.end_full(h)):
            r.warn(h.label, '建议用表格逐项写（主市场、界面语言、时区和格式、登录渠道……）')
        return ''
    lang = next((v for k, v in rows.items() if '界面语言' in k or k.strip() == '语言'), '')
    if not lang:
        r.err(h.label, '「界面语言」没定：AI 会中英文混着写文案')
    for key in MARKET_ROWS:
        hit = [v for k, v in rows.items() if key in k]
        if not hit:
            r.warn(h.label, '表里没有「%s」这一项' % key)
        elif not hit[0]:
            r.warn(h.label, '「%s」是空的；不涉及就写「不涉及」' % key)
    return lang


def check_scope(doc, r):
    h = doc.sec('1.5')
    if not h:
        return
    keys = ('这一版要做', '这一版简化', '这一版不做')
    lines = [doc.lines[i] for i in range(h.line + 1, doc.end_full(h))]
    pos = {}
    for i, line in enumerate(lines):
        for k in keys:
            if k not in pos and re.search(re.escape(k) + r'\s*(?:\*\*)?\s*[:：]', line):
                pos[k] = i
    for k in keys:
        if k not in pos:
            r.err(h.label, '缺少「%s」' % k)
            continue
        nxt = min([v for v in pos.values() if v > pos[k]] or [len(lines)])
        first = re.split(re.escape(k) + r'\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?', lines[pos[k]], 1)[-1]
        body = (first + '\n' + '\n'.join(lines[pos[k] + 1:nxt])).strip()
        if not re.sub(r'[-*+\s]', '', body):
            r.err(h.label, '「%s」是空的；没有就写「无」' % k)


def _decisions(lines):
    """从 Mermaid 流程图里找判断节点和它们的出路数。返回 [(节点文字, 出路数)]。"""
    names, outs = OrderedDict(), {}
    for line in lines:
        s = line.strip()
        if not s or s.startswith('%%') or re.match(r'(classDef|class|style|linkStyle|subgraph|end|direction|flowchart|graph)\b', s):
            continue
        s = re.sub(r'\|[^|]*\|', '', s)
        for m in re.finditer(r'(\w+)\{(?!\{)([^{}]*)\}', s):
            names.setdefault(m.group(1), re.sub(r'<br\s*/?>', ' ', m.group(2)).strip('" '))
        s = re.sub(r'"[^"]*"', '', s)
        for _ in range(4):
            s = re.sub(r'\[[^\[\]]*\]|\([^()]*\)|\{[^{}]*\}', '', s)
        s = re.sub(r'-\.[^>\n]*?\.?->|==[^>\n]*?=>|--[^>\n]*?-->|--[ox]|---', '-->', s)
        segs = [re.findall(r'\w+', seg) for seg in s.split('-->')]
        for a, b in zip(segs, segs[1:]):
            for x in a:
                outs.setdefault(x, set()).update(b)
    return [(text or nid, len(outs.get(nid, ()))) for nid, text in names.items()]


def check_flow(doc, r):
    h = doc.sec('2.1')
    if not h:
        return
    end = doc.end_full(h)
    charts, untagged = [], False   # 流程多的产品会分成几张图，逐张查
    for s, e, info in doc.blocks:
        if h.line < s < end:
            body = [doc.raw[i] for i in range(s + 1, e)]
            first = next((x.strip() for x in body if x.strip()), '')
            tagged = info.lower().startswith('mermaid')
            if tagged or re.match(r'(flowchart|graph)\b', first):
                charts.append(body)
                untagged = untagged or not tagged
    if not charts:
        r.err(h.label, '没有找到流程图（Mermaid 的 flowchart 代码块）')
        return
    if untagged:
        r.warn(h.label, '流程图的代码块没有标注 mermaid，粘到文档工具里不会显示成图')
    for n_chart, body in enumerate(charts, 1):
        where = '第 %d 张图的' % n_chart if len(charts) > 1 else ''
        for text, n in _decisions(body):
            if n < 2:
                r.warn(h.label, '%s判断节点「%s」只有 %d 条出路：另一种情况去哪要画出来' % (where, text, n))


def check_states(doc, r):
    h = doc.sec('2.2')
    if not h:
        return []
    states = []
    for t in doc.tables(h.line, doc.end_full(h)):
        ci = t.col('状态名')
        if ci is None:
            ci = t.col('状态')
        if ci is None:
            continue
        di, ki = t.col('维度'), t.col('判断条件', '条件')
        for row in t.rows:
            name = strip_md(t.cell(row, ci))
            if name:
                states.append((strip_md(t.cell(row, di)), name, t.cell(row, ki)))
    if not states:
        r.err(h.label, '状态字典是空的：用表格写（维度 | 状态名 | 判断条件 | 备注）')
        return []
    s, e = doc.ch3_range()
    ch3 = norm(doc.text_of(s, e))
    seen = {}
    for dim, name, cond in states:
        if not cond:
            r.err(h.label, '状态「%s」没有判断条件' % name)
        if norm(name) not in ch3:
            r.err(h.label, '状态「%s」在第 3 章里没有任何组件提到：它出现时页面什么样没写' % name)
        if name in seen and seen[name] != dim:
            r.warn(h.label, '「%s」在「%s」和「%s」两个维度里都有，引用时会分不清：改一个名字' % (name, seen[name], dim))
        seen.setdefault(name, dim)
    return states


def check_outlines(doc, r):
    """返回 (名字表 {归一化名字: 原名}, 被大纲引用的节号集合)。"""
    names, used, own = {}, set(), {}   # own：每个页面的大纲里出现的本页节号

    def reg(name):
        for n in (name, drop_paren(name)):
            if n:
                names.setdefault(norm(n), n)

    for h in doc.pages() + doc.globals_() + doc.comps():
        if not doc.is_reuse(h):
            reg(h.name)
            if '：' in h.name:   # 页面标题「入口名：页面名」，引用时可以只写页面名
                reg(h.name.split('：', 1)[1])
    for p in doc.pages():
        roots, marked = doc.outline(p)
        if not roots:
            r.err(p.label, '没有页面结构（大纲）：标题下面用嵌套列表，从页面顶部写到底部')
            continue
        if not marked:
            r.warn(p.label, '大纲前面加一行「**页面结构（大纲）**」')
        pn, seen = p.num.split('.')[1], set()
        for root in roots:
            nodes = list(root.walk())
            for n in nodes:
                reg(n.name)
            if not any(n.ref for n in nodes):
                r.err(p.label, '大纲里的「%s」没有节号：末尾写上（%s.M），复用的写（复用 3.X.Y）' % (root.name, p.num))
            for n in nodes:
                if not n.ref:
                    continue
                used.add(n.ref)
                t = doc.sec(n.ref)
                if not t:
                    r.err(p.label, '大纲里的「%s（%s）」找不到对应的说明：文档里没有 %s 这一节' % (n.name, n.ref, n.ref))
                    continue
                a, b = norm(n.name), norm(t.name)
                if a != b and a != norm(drop_paren(t.name)) and norm(drop_paren(n.name)) != b:
                    r.warn(p.label, '大纲里叫「%s」，%s 的标题是「%s」：名字统一成一个' % (n.name, n.ref, t.name))
                sec = n.ref.split('.')[1]
                if n.kind == 'own':
                    if sec == '0':
                        r.warn(p.label, '「%s」指向全局组件，写成（全局 %s）' % (n.name, n.ref))
                    elif sec != pn:
                        r.warn(p.label, '「%s」指向别的页面的组件，写成（复用 %s）' % (n.name, n.ref))
                    elif n.ref in seen:
                        r.warn(p.label, '节号 %s 在这一页的大纲里出现了两次' % n.ref)
                    seen.add(n.ref)
                    own.setdefault(p.num, set()).add(n.ref)
                elif n.kind == 'global' and sec != '0':
                    r.warn(p.label, '「%s」写了「全局」，但 %s 不在 3.0 下面' % (n.name, n.ref))
    for h in doc.comps():
        page = '3.' + h.num.split('.')[1]
        if not doc.is_reuse(h) and h.num not in own.get(page, ()):
            r.err(h.label, '有说明，但没出现在 %s 的大纲里：加进大纲，或者删掉这一节' % page)
    return names, used


def check_brackets(doc, r, names):
    """【】引用的名字都要有定义。返回被引用到的名字集合。"""
    hit, bad = set(), OrderedDict()
    for i, line in enumerate(doc.lines):
        if doc.in_code[i]:
            continue
        for m in BRACKET_RE.finditer(strip_inline_code(line)):
            inner = clean_name(REF_RE.sub('', m.group(1)))
            keys = [norm(inner), norm(drop_paren(inner))]
            ok = [k for k in keys if k in names]
            if ok:
                hit.update(ok)
            else:
                bad.setdefault(inner, []).append(i)
    for inner, at in bad.items():
        near = difflib.get_close_matches(norm(inner), list(names), n=1, cutoff=0.5)
        tip = '最接近的是【%s】' % names[near[0]] if near else '文档里没有叫这个名字的组件、弹窗或页面'
        more = '（共 %d 处）' % len(at) if len(at) > 1 else ''
        r.err(doc.where(at[0]), '第 %d 行的【%s】没有定义%s：%s' % (at[0] + 1, inner, more, tip))
    return hit


def _cjk_cells(t):
    """文案表里含中文的格子。跳过第一列和备注、原文这类列。"""
    skip = {0} | {i for i, h in enumerate(t.header) if any(k in h for k in ('备注', '说明', '原文'))}
    out = []
    for row in t.rows:
        for i, c in enumerate(row):
            if i in skip:
                continue
            c = re.sub(r'\{[^{}]*\}', '', strip_inline_code(c))
            c = re.sub(r'\[待定[^\]]*\].*$|〔建议〕', '', c)
            if re.search(r'[一-鿿]', c):
                out.append(row[i])
    return out


def check_cards(doc, r, lang):
    """逐张规格卡检查七项。返回后台配置项的总数。"""
    n_cfg = 0
    lang_on = bool(lang) and not any(k in lang for k in CJK_LANG)
    lang_show = re.sub(r'\[待定[^\]]*\]\s*(默认假设)?[:：]?\s*', '', lang).strip('。 ')
    for h in doc.cards():
        if not h.name:
            r.err(h.label, '组件没有名字')
        items = doc.card(h)
        missing = [l for l in LABELS if l not in items]
        if missing:
            r.err(h.label, '缺少：%s（没有内容就写「无」，标签不要删）' % '、'.join(missing))
        for label in LABELS:
            it = items.get(label)
            if it is None:
                continue
            if it.is_empty():
                r.err(h.label, '「%s」是空的；没有内容就写「无」' % label)
                continue
            if it.is_none():
                if label in ('目的', '验收标准'):
                    r.err(h.label, '「%s」不能写「无」' % label)
                elif label == '交互状态':
                    r.warn(h.label, '「交互状态」写了「无」：至少有一个默认状态')
                continue
            if label == '验收标准':
                txt = strip_inline_code(it.text())
                words = [w for w in VAGUE if w in txt]
                if words:
                    r.warn(h.label, '验收标准里有各人理解不同的词：%s。换成看得见的结果或具体数字' % '、'.join('「%s」' % w for w in words))
                continue
            if label in ('目的', '异常和边界'):
                continue
            ts = doc.item_tables(it)
            if not ts:
                if label == '后台配置项':
                    r.err(h.label, '「后台配置项」要写成表格（配置项 | 类型 | 默认值 | 限制 | 说明），否则汇总不进后台配置总表')
                else:
                    r.warn(h.label, '「%s」建议写成表格' % label)
                continue
            if not any(t.data_rows() for t in ts):
                r.err(h.label, '「%s」的表是空的；没有内容就写「无」' % label)
                continue
            if label == '后台配置项':
                for t in ts:
                    ci, ti = t.col('配置项'), t.col('类型')
                    if ci is None:
                        r.err(h.label, '「后台配置项」的表头要有「配置项」一列')
                        continue
                    for row in t.data_rows():
                        name, typ = strip_md(t.cell(row, ci)), strip_md(t.cell(row, ti))
                        if name:
                            n_cfg += 1
                        if typ and not any(typ.startswith(x) for x in TYPES):
                            r.warn(h.label, '配置项「%s」的类型「%s」不在约定里（%s）' % (name, typ, '、'.join(TYPES)))
            elif label == '数据字段和示例数据' and doc.level == '前端级':
                if any(t.col('类型') is None or t.col('来源') is None for t in ts):
                    r.err(h.label, '前端级的「数据字段和示例数据」要有「类型」「来源」两列')
            elif label == '文案' and lang_on:
                cells = [c for t in ts for c in _cjk_cells(t)]
                if cells:
                    r.warn(h.label, '文案里有 %d 句是中文，但 1.4 定的界面语言是「%s」。例如：%s' % (len(cells), lang_show, cells[0]))
        a, c = items.get('验收标准'), items.get('后台配置项')
        if a and c and c.is_none() and re.search(r'可配置|后台读取|后台配置|配置化|可由.{0,6}配置', a.text()):
            r.warn(h.label, '验收标准里提到了可配置，但「后台配置项」写的是「无」')
    for h in doc.globals_() + doc.comps():
        if doc.is_reuse(h) and not any(t.data_rows() for t in doc.tables(h.line, doc.end_full(h))):
            r.warn(h.label, '「复用」这一节用表格写（组件 | 在本页的变化）')
    return n_cfg


def check_todo(doc, r):
    """[待定] 和附录 A 对账。返回还没定的条数。"""
    a = doc.appx('A')
    a_range = (a.line, doc.end_full(a)) if a else (0, 0)
    table = OrderedDict()
    if a:
        for t in doc.tables(*a_range):
            ci, si, di = t.col('编号'), t.col('状态'), t.col('默认假设', '默认')
            if ci is None:
                continue
            for row in t.rows:
                m = re.search(r'\d+', t.cell(row, ci))
                if m:
                    table[int(m.group(0))] = (t.cell(row, si), t.cell(row, di))
    body = OrderedDict()
    for i, line in enumerate(doc.lines):
        if doc.in_code[i] or a_range[0] <= i < a_range[1]:
            continue
        s = strip_inline_code(line)
        if TODO_BARE_RE.search(s):
            r.err(doc.where(i), '第 %d 行的待定没有编号：写成 [待定 Q数字]，并登记到附录 A' % (i + 1))
        for m in TODO_RE.finditer(s):
            body.setdefault(int(m.group(1)), []).append((i, '默认' in s[m.end():]))
    for q, at in body.items():
        if q not in table:
            r.err(doc.where(at[0][0]), '第 %d 行的 [待定 Q%d] 没有登记到附录 A' % (at[0][0] + 1, q))
    n_open = 0
    for q, (status, default) in table.items():
        if '已定' in status:
            if q in body:
                r.err('附录 A', 'Q%d 已经定了，正文第 %d 行的标记还没去掉' % (q, body[q][0][0] + 1))
            continue
        n_open += 1
        if not default:
            r.err('附录 A', 'Q%d 没有默认假设：AI 会自己猜' % q)
        if q not in body:
            r.warn('附录 A', 'Q%d 在正文里找不到对应的 [待定 Q%d] 标记' % (q, q))
        elif not any(ok for _, ok in body[q]):
            r.warn(doc.where(body[q][0][0]), '第 %d 行的 [待定 Q%d] 后面写上默认假设' % (body[q][0][0] + 1, q))
    return n_open


def check_sugg(doc, r, final):
    from . import gen
    span = gen.find_markers(doc) or (0, 0)   # 4.2 的汇总表是各组件配置项的副本，不重复数
    groups, total = OrderedDict(), 0
    for i, line in enumerate(doc.lines):
        if doc.in_code[i] or span[0] < i < span[1]:
            continue
        n = strip_inline_code(line).count('〔建议〕')
        if n:
            total += n
            w = doc.where(i)
            groups[w] = groups.get(w, 0) + n
    if total:
        parts = ['%s ×%d' % kv for kv in groups.items()]
        msg = '还有 %d 处〔建议〕没确认：%s' % (total, '、'.join(parts[:12]) + ('……' if len(parts) > 12 else ''))
        if final:
            r.err('全文', msg + '。确认的去掉标记，不要的删掉')
        else:
            r.warn('全文', msg)
    return total


def check_delivery(doc, r):
    """第 4 章：平台约束、后台配置总表、整页验收用例。"""
    h = doc.sec('4.1')
    if h:
        for t in doc.tables(h.line, doc.end_full(h)):
            for row in t.rows:
                if len(row) > 1 and row[0].strip() and not ''.join(row[1:]).strip():
                    r.warn(h.label, '「%s」是空的' % strip_md(row[0]))
    h = doc.sec('4.2')
    if h:
        from . import gen
        span = gen.find_markers(doc, h)
        if not span:
            r.warn(h.label, '没有 config 标记：运行 prd.py config 会补上并汇总各组件的配置项')
        else:
            old = [x.rstrip() for x in doc.raw[span[0] + 1:span[1]] if x.strip()]
            new = [x.rstrip() for x in gen.config_block(doc) if x.strip()]
            if old != new:
                r.warn(h.label, '后台配置总表不是最新的：运行 prd.py config 刷新')
    h = doc.sec('4.3')
    if not h:
        return 0
    cases = doc.cases()
    if not cases:
        r.err(h.label, '一条用例都没有（### 用例 1：名称）')
    elif len(cases) < 4:
        r.warn(h.label, '只有 %d 条用例，通常要 4～8 条：流程图里的每一种结局至少有一条用例走到' % len(cases))
    for c in cases:
        txt = doc.text_of(c.line + 1, doc.end_full(c))
        lost = [k for k in ('前置条件', '步骤', '期望结果') if k not in txt]
        if lost:
            r.err(c.title, '缺少：%s' % '、'.join(lost))
    return len(cases)


def run(doc, final=False):
    r = Report()
    check_header(doc, r)
    check_sections(doc, r)
    lang = check_market(doc, r)
    check_scope(doc, r)
    check_flow(doc, r)
    states = check_states(doc, r)
    names, used = check_outlines(doc, r)
    hit = check_brackets(doc, r, names)
    for g in doc.globals_():
        if not doc.is_reuse(g) and g.num not in used and not ({norm(g.name), norm(drop_paren(g.name))} & hit):
            r.warn(g.label, '全局组件没有被任何页面的大纲或正文用到')
    n_cfg = check_cards(doc, r, lang)
    n_case = check_delivery(doc, r)
    n_open = check_todo(doc, r)
    n_sugg = check_sugg(doc, r, final)
    n_glob = len([g for g in doc.globals_() if not doc.is_reuse(g)])
    r.stats['页面'] = '%d 个' % len(doc.pages())
    r.stats['组件'] = '%d 个（其中全局组件 %d 个）' % (len(doc.cards()), n_glob)
    r.stats['状态'] = '%d 个' % len(states)
    r.stats['后台配置项'] = '%d 项' % n_cfg
    r.stats['整页验收用例'] = '%d 条' % n_case
    r.stats['待定'] = '%d 条' % n_open
    r.stats['未确认的建议'] = '%d 处' % n_sugg
    return r


def render(doc, r, final=False):
    out = ['PRD 检查报告：%s' % (doc.path.name if doc.path else ''),
           '交付深度：%s%s' % (doc.level or '未填', '　（交付前检查）' if final else ''), '']

    def block(title, rows):
        out.append('%s（%d 条）' % (title, len(rows)))
        groups = OrderedDict()
        for where, msg in rows:
            groups.setdefault(where, []).append(msg)
        for where, msgs in groups.items():
            out.append('  [%s]' % where)
            out.extend('    - %s' % m for m in msgs)
        out.append('')

    if r.errors:
        block('✗ 必须修', r.errors)
    if r.warns:
        block('! 建议修', r.warns)
    out.append('统计')
    for k, v in r.stats.items():
        out.append('  %s：%s' % (k, v))
    out.append('')
    if r.errors:
        out.append('结论：有 %d 条必须修的问题，修完再往下。' % len(r.errors))
    elif final:
        out.append('结论：可以交给 AI 了。%s' % ('建议修的 %d 条再看一眼。' % len(r.warns) if r.warns else ''))
    else:
        out.append('结论：没有必须修的问题。%s' % ('建议修的 %d 条看一下。' % len(r.warns) if r.warns else ''))
    return '\n'.join(out)
