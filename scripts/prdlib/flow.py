# -*- coding: utf-8 -*-
"""流程图预览：把 2.1 里的 Mermaid 流程图做成一个用浏览器就能打开的网页。

画图用的是 Mermaid，从 cdnjs 加载，所以打开网页时要联网；没网时网页会直接显示流程图的文字。
"""
import re
import html
from pathlib import Path

from .parse import strip_md, save, open_doc
from .gen import safe_name

MERMAID_JS = 'https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js'

PAGE = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#F5F6F8;--card:#FFFFFF;--ink:#16202E;--ink2:#3F4C5E;--ink3:#748094;--line:#D3D9E1;--warn:#B45309}
@media (prefers-color-scheme:dark){:root{--bg:#11151B;--card:#1B212A;--ink:#E7EBF1;--ink2:#BAC4D1;--ink3:#8793A5;--line:#343D4A;--warn:#FBBF24}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--ink3);font-size:13px;margin-bottom:22px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 18px 14px;margin-bottom:18px}
h2{font-size:16px;margin:0 0 12px}
.chart{overflow-x:auto;text-align:center}
.chart svg{max-width:100%;height:auto}
.note{color:var(--ink2);font-size:13px;margin:12px 0 0;border-top:1px dashed var(--line);padding-top:10px}
.tip{display:none;color:var(--warn);font-size:13px;margin-bottom:14px}
pre.src{display:none;white-space:pre-wrap;font-size:12px;color:var(--ink2);text-align:left;margin:0}
.offline .tip,.offline pre.src{display:block}
.offline pre.mermaid{display:none}
</style>
</head>
<body>
<main>
<h1>__TITLE__</h1>
<div class="sub">__SUB__</div>
<div class="tip">画图的脚本没加载成功（多半是没联网），下面先显示流程图的文字。联网后刷新这一页就能看到图。</div>
__SECTIONS__
</main>
<script src="__MERMAID__"></script>
<script>
(function(){
  if (!window.mermaid) { document.body.classList.add('offline'); return; }
  var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  mermaid.initialize({startOnLoad: false, theme: dark ? 'dark' : 'neutral', securityLevel: 'loose',
                      flowchart: {htmlLabels: true, useMaxWidth: true, curve: 'basis'}});
  mermaid.run({querySelector: 'pre.mermaid'}).catch(function(){ document.body.classList.add('offline'); });
})();
</script>
</body>
</html>
'''


def collect(doc):
    """2.1 里的每张流程图：[(图名, Mermaid 文字, 图下面的说明)]。"""
    h = doc.sec('2.1')
    if not h:
        return []
    end, blocks = doc.end_full(h), []
    for s, e, info in doc.blocks:
        if h.line < s < end:
            body = [doc.raw[i] for i in range(s + 1, e)]
            first = next((x.strip() for x in body if x.strip()), '')
            if info.lower().startswith('mermaid') or re.match(r'(flowchart|graph)\b', first):
                blocks.append((s, e, body))
    out = []
    for n, (s, e, body) in enumerate(blocks):
        i = s - 1
        while i > h.line and not doc.lines[i].strip():
            i -= 1
        title = strip_md(doc.lines[i]).strip() if i > h.line and not doc.in_code[i] else ''
        if not title or len(title) > 40:
            title = '流程图 %d' % (n + 1) if len(blocks) > 1 else '用户流程图'
        stop = blocks[n + 1][0] if n + 1 < len(blocks) else end
        notes = []
        for j in range(e + 1, stop):
            t = doc.lines[j].strip()
            if not t or doc.in_code[j]:
                continue
            if t.startswith('**') and t.endswith('**'):
                break
            notes.append(strip_md(t))
        out.append((title, '\n'.join(body), notes))
    return out


def to_html(doc, charts):
    title = '%s · 用户流程图' % doc.product
    parts = []
    for name, src, notes in charts:
        src_e = html.escape(src)
        note = ''.join('<p class="note">%s</p>' % html.escape(t) for t in notes)
        parts.append('<section>\n<h2>%s</h2>\n<div class="chart"><pre class="mermaid">%s</pre></div>\n'
                     '<pre class="src">%s</pre>\n%s\n</section>' % (html.escape(name), src_e, src_e, note))
    sub = '共 %d 张图，来自《%s》的 2.1。图是照着 PRD 画的，要改就改 PRD，再重新生成。' % (len(charts), doc.path.name)
    return (PAGE.replace('__TITLE__', html.escape(title)).replace('__SUB__', html.escape(sub))
            .replace('__MERMAID__', MERMAID_JS).replace('__SECTIONS__', '\n'.join(parts)))


def cmd_flow(path, out_dir=None):
    doc = open_doc(path)
    charts = collect(doc)
    if not charts:
        print('2.1 里还没有流程图（Mermaid 的 flowchart 代码块），先不生成。')
        return 1
    base = Path(out_dir) if out_dir else doc.path.parent
    base.mkdir(parents=True, exist_ok=True)
    out = base / ('%s-流程图.html' % safe_name(doc.product))
    save(out, to_html(doc, charts))
    print('已生成流程图预览（%d 张图）：%s' % (len(charts), out))
    print('用浏览器打开。画图的脚本从网上加载，打开时要联网。')
    return 0
