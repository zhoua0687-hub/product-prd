# -*- coding: utf-8 -*-
"""生成类命令：init（建 PRD 文件）、config（汇总后台配置）、brief（AI 任务书）。"""
import re
import datetime
from pathlib import Path

from .parse import LIST_RE, strip_md, save, open_doc

CFG_START = '<!-- config:start -->'
CFG_END = '<!-- config:end -->'
CFG_COLS = ['配置项', '类型', '默认值', '限制', '说明']
SKILL_ROOT = Path(__file__).resolve().parents[2]


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|]+', '-', name).strip() or '产品'


# ---------- init ----------
def cmd_init(name, out_dir='.', level='原型级', force=False):
    if level not in ('原型级', '前端级'):
        print('交付深度只能是「原型级」或「前端级」。')
        return 1
    tpl = SKILL_ROOT / 'templates' / 'prd-template.md'
    if not tpl.exists():
        print('找不到模板：%s' % tpl)
        return 1
    out = Path(out_dir) / ('%s-PRD.md' % safe_name(name))
    if out.exists() and not force:
        print('文件已经存在，没有覆盖：%s\n要重建就加 --force。' % out)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    text = tpl.read_text(encoding='utf-8').replace('{{产品名}}', name).replace('{{交付深度}}', level)
    save(out, text)
    print('已建好：%s\n交付深度：%s\n接下来从第 1 章开始，一个阶段一个阶段往里写。' % (out, level))
    return 0


# ---------- config ----------
def find_markers(doc, h=None):
    """4.2 里 config 标记的行号 (start, end)，没有就返回 None。"""
    h = h or doc.sec('4.2')
    if not h:
        return None
    s = None
    for i in range(h.line, doc.end_full(h)):
        t = doc.raw[i].strip()
        if t == CFG_START and s is None:
            s = i
        elif t == CFG_END and s is not None:
            return s, i
    return None


def collect_config(doc):
    """[(组件标题, [配置项, 类型, 默认值, 限制, 说明])]，按文档顺序。"""
    rows = []
    for h in doc.cards():
        it = doc.card(h).get('后台配置项')
        if not it or it.is_none():
            continue
        for t in doc.item_tables(it):
            idx = [t.col(c) for c in CFG_COLS]
            if idx[0] is None:
                continue
            for row in t.data_rows():
                cells = [t.cell(row, i) for i in idx]
                if cells[0]:
                    rows.append((h, cells))
    return rows


def _esc(c):
    return c.replace('|', '\\|')


def config_block(doc):
    """标记中间应该放的内容（行的列表）。"""
    rows = collect_config(doc)
    if not rows:
        return ['', '这一版没有后台配置项。', '']
    comps = []
    for h, _ in rows:
        if h.num not in comps:
            comps.append(h.num)
    out = ['',
           '共 %d 项，来自 %d 个组件。这张表由 `prd.py config` 汇总，不要手改；'
           '要改就改对应组件的「后台配置项」，再重新汇总。' % (len(rows), len(comps)),
           '',
           '| 所属组件 | %s |' % ' | '.join(CFG_COLS),
           '|' + '---|' * (len(CFG_COLS) + 1)]
    for h, cells in rows:
        out.append('| %s | %s |' % (_esc(h.label), ' | '.join(_esc(c) for c in cells)))
    out.append('')
    return out


def cmd_config(path):
    doc = open_doc(path)
    h = doc.sec('4.2')
    if not h:
        print('PRD 里没有「4.2 后台配置总表」这一节，先把这一节的标题加上。')
        return 1
    block, span = config_block(doc), find_markers(doc, h)
    if span:
        raw = doc.raw[:span[0] + 1] + block + doc.raw[span[1]:]
    else:
        end = doc.end_full(h)
        while end > h.line + 1 and not doc.raw[end - 1].strip():
            end -= 1
        raw = doc.raw[:end] + ['', CFG_START] + block + [CFG_END, ''] + doc.raw[end:]
    save(path, '\n'.join(raw), doc.newline)
    n = len(collect_config(doc))
    print('已把 %d 项后台配置汇总到 4.2。' % n if n else '各组件都没有后台配置项，4.2 已写明「没有」。')
    return 0


# ---------- brief ----------
RULES = [
    ('只做 PRD 列出的。', '页面、组件、状态、文案都以 PRD 为准，不增加 PRD 没有的页面、组件、功能和文案，也不删减。'
     '每个页面按第 3 章大纲的顺序从上到下排。1.5 里「这一版不做」的内容一律不做。'),
    ('状态做全。', '每个组件「交互状态」表里的每一行都要做出来。状态名和判断条件以 2.2 状态字典为准。'),
    ('文案照抄。', '界面上的每一句话用 PRD「文案」表里的原文，不改写、不翻译、不自己补。'),
    ('示例数据用 PRD 的。', '「数据字段和示例数据」里给了什么就用什么，不另编。'),
    ('待定按默认假设做。', 'PRD 里标了 `[待定 Q编号]` 的地方，按后面写的默认假设做（汇总在本文件第七节），'
     '并在交付时列出来。行尾带 `〔建议〕` 的内容视同已确认，照做。'),
    ('PRD 没写的，选最简单的做法并报告。', '遇到 PRD 没有规定的地方，不要自由发挥，选最简单、最常见的做法，'
     '并记进交付时的「PRD 未规定」清单。'),
]
LEVEL_NOTES = {
    '原型级': ('这一次要做的是**可点击的原型**：看得见、点得动、状态都对。', [
        '数据直接写在原型里，用 PRD 的示例数据，不接真实接口。',
        '需要等待或依赖后端的动作（登录、验证、提交）直接模拟成功；PRD 写了失败表现的，另留一个能演示失败的入口。',
        '做一个只在原型里出现的状态切换面板，可以切换 2.2 状态字典里的每一个状态，方便逐条验收。'
        '面板不属于产品，放在不遮挡页面的位置。',
    ]),
    '前端级': ('这一次要做的是**前端代码**：能接数据、能上线。', [
        '技术栈、兼容范围、配置注入方式和接口约定以 PRD 4.1 为准。',
        'PRD 4.2 里的后台配置项全部从配置读取，不写死在代码里。',
        '数据字段的类型和来源以各组件的数据表为准。',
        '接口没就绪时用 PRD 的示例数据做本地模拟，模拟和真实接口的切换集中在一处。',
    ]),
}


def _body(doc, h, full=True):
    """一节的正文（去掉首尾空行）。"""
    if not h:
        return ['（PRD 里没有这一节）']
    lines = doc.lines[h.line + 1:(doc.end_full(h) if full else doc.end_own(h))]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines or ['（PRD 里这一节是空的）']


def _clean(t):
    return re.sub(r'\s*〔建议〕', '', t).rstrip()


def _checklist(doc, item):
    """验收标准 → 勾选清单。第一层变成勾选框，下面的层级原样缩进。"""
    out, base = [], None
    first = _clean(item.lines[0][1].strip())
    if first:
        out.append('- [ ] %s' % first)
    for i, line in item.lines[1:]:
        if doc.in_code[i] or not line.strip():
            continue
        m = LIST_RE.match(line)
        if not m:
            if out:
                out[-1] += ' ' + _clean(line.strip())
            continue
        indent = len(m.group(1).expandtabs(4))
        if base is None:
            base = indent
        depth = max(0, (indent - base + 1) // 2)
        text = _clean(m.group(2).strip())
        out.append('- [ ] %s' % text if depth == 0 else '%s- %s' % ('  ' * depth, text))
    return out


def _first_col(doc, item, *keys):
    vals = []
    for t in doc.item_tables(item):
        ci = t.col(*keys)
        if ci is None:
            ci = 0
        for row in t.data_rows():
            v = _clean(strip_md(t.cell(row, ci)))
            if v:
                vals.append(v)
    return vals


def build_brief(doc):
    level = doc.level or '原型级'
    name = doc.product
    today = datetime.date.today().isoformat()
    o = ['# %s · AI 任务书' % name, '',
         '> 由 `prd.py brief` 从《%s》生成（%s）。不要手改；PRD 改了就重新生成。' % (doc.path.name, today),
         '> 交付深度：%s' % level, '',
         '你会同时拿到两份文件：PRD 说的是产品是什么样；这份任务书说的是照着做的时候守哪些规矩、'
         '按什么顺序做、做完怎么自查。两份有出入时以 PRD 为准。', '']
    intro, notes = LEVEL_NOTES[level]
    o += [intro, ''] + ['- %s' % n for n in notes] + ['']

    o += ['## 一、六条规矩', '']
    for i, (head, body) in enumerate(RULES, 1):
        o.append('%d. **%s** %s' % (i, head, body))
    o.append('')

    o += ['## 二、目标市场和范围', '', '### 目标市场（PRD 1.4）', ''] + _body(doc, doc.sec('1.4'))
    o += ['', '### 范围和优先级（PRD 1.5）', ''] + _body(doc, doc.sec('1.5')) + ['']

    o += ['## 三、状态字典（PRD 2.2）', ''] + _body(doc, doc.sec('2.2')) + ['']

    o += ['## 四、制作顺序', '']
    step = 1
    globs = [g for g in doc.globals_() if not doc.is_reuse(g)]
    if globs:
        o.append('%d. **全局组件（3.0）**：%s。先做，后面的页面会用到。' % (step, ' → '.join(g.label for g in globs)))
        step += 1
    for p in doc.pages():
        roots, _ = doc.outline(p)
        own, reuse, glob = [], [], []
        for root in roots:
            for n in root.walk():
                if not n.ref:
                    continue
                t = doc.sec(n.ref)
                label = t.label if t else '%s %s' % (n.ref, n.name)
                bucket = {'own': own, 'reuse': reuse, 'global': glob}[n.kind]
                if label not in bucket:
                    bucket.append(label)
        parts = []
        if own:
            parts.append('按大纲从上到下新做 %s' % ' → '.join(own))
        if reuse:
            change = next((c.label for c in doc.comps(p) if doc.is_reuse(c)), None)
            parts.append('复用 %s%s' % ('、'.join(reuse), '（在本页的变化见 %s）' % change if change else ''))
        if glob:
            parts.append('用到全局组件 %s' % '、'.join(glob))
        o.append('%d. **%s**：%s。' % (step, p.label, '；'.join(parts) or '见 PRD 这一节的大纲'))
        step += 1
    o.append('')

    o += ['## 五、逐组件验收清单', '', '每做完一个组件，对着清单过一遍。', '']
    for h in doc.cards():
        items = doc.card(h)
        o += ['### %s' % h.label, '']
        acc = items.get('验收标准')
        rows = _checklist(doc, acc) if acc and not acc.is_none() else []
        o += rows or ['- [ ] 按 PRD %s 的说明实现' % h.num]
        st = items.get('交互状态')
        if st and not st.is_none():
            names = _first_col(doc, st, '状态')
            if names:
                o.append('- [ ] 状态做全（共 %d 个）：%s' % (len(names), '、'.join(names)))
        cp = items.get('文案')
        if cp and not cp.is_none():
            n = sum(len(t.data_rows()) for t in doc.item_tables(cp))
            if n:
                o.append('- [ ] 文案和 PRD %s 的文案表一字不差（共 %d 句）' % (h.num, n))
        ex = items.get('异常和边界')
        if ex and not ex.is_none():
            o.append('- [ ] PRD %s「异常和边界」里的每种情况都处理了' % h.num)
        o.append('')
    for h in doc.globals_() + doc.comps():
        if doc.is_reuse(h):
            o += ['### %s' % h.label, '', '- [ ] 表里每个复用组件在本页的变化都做了', '']

    o += ['## 六、整页验收用例（PRD 4.3）', '', '全部做完后，按下面的用例从头到尾走一遍。', '']
    o += _body(doc, doc.sec('4.3')) + ['']

    o += ['## 七、待定项和默认假设（PRD 附录 A）', '']
    todo = []
    a = doc.appx('A')
    if a:
        for t in doc.tables(a.line, doc.end_full(a)):
            ci, pi, qi, di, si = t.col('编号'), t.col('位置'), t.col('问题'), t.col('默认假设', '默认'), t.col('状态')
            if ci is None:
                continue
            for row in t.data_rows():
                if '已定' not in t.cell(row, si):
                    todo.append([t.cell(row, x) for x in (ci, pi, qi, di)])
    if todo:
        o += ['下面这些使用者还没定。先按「默认假设」做，交付时把它们列出来。', '',
              '| 编号 | 位置 | 问题 | 默认假设（照这个做） |', '|---|---|---|---|']
        o += ['| %s |' % ' | '.join(_esc(c) for c in row) for row in todo]
    else:
        o.append('没有待定项。')
    o.append('')

    o += ['## 八、交付时附上', '',
          '1. **自查结果**：第五节的验收清单逐条标注「通过」「未通过」或「没做」，未通过的写原因。',
          '2. **「PRD 未规定」清单**：每条写清在哪个页面的哪个组件、PRD 缺了什么、你选了什么做法。',
          '3. **待定项清单**：按默认假设做的每一条，写上 Q 编号。',
          '4. **没做完的部分**：列出来，不要用占位内容冒充。', '']
    return '\n'.join(o)


def cmd_brief(path, out=None):
    doc = open_doc(path)
    if not doc.sec('3'):
        print('这份 PRD 还没有第 3 章，任务书先不生成。')
        return 1
    out = Path(out) if out else doc.path.parent / ('%s-AI任务书.md' % safe_name(doc.product))
    save(out, build_brief(doc))
    print('已生成：%s\n和 PRD 一起交给做原型或前端的 AI。' % out)
    return 0
