#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""product-prd 的命令行工具。

    prd.py init "<产品名>" [--dir 目录] [--level 原型级|前端级] [--force]
    prd.py check <PRD.md> [--final]
    prd.py flow <PRD.md> [--out-dir 目录]
    prd.py mindmap <PRD.md> [--out-dir 目录]
    prd.py config <PRD.md>
    prd.py brief <PRD.md> [--out 文件]

只用 Python 标准库，不需要安装任何东西。
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prdlib import check, flow, gen, mindmap  # noqa: E402
from prdlib.parse import open_doc  # noqa: E402


def _utf8_output():
    """输出被管道接走时统一用 UTF-8，避免中文乱码；直接在终端里跑则不动。"""
    for s in (sys.stdout, sys.stderr):
        try:
            if not s.isatty():
                s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


def _need_file(path):
    if not Path(path).is_file():
        print('找不到文件：%s' % path)
        return False
    return True


def main(argv=None):
    _utf8_output()
    ap = argparse.ArgumentParser(prog='prd.py', description='PRD 的建档、检查、思维导图、配置汇总、AI 任务书')
    sub = ap.add_subparsers(dest='cmd')

    p = sub.add_parser('init', help='从模板建一份空白 PRD')
    p.add_argument('name', help='产品名')
    p.add_argument('--dir', default='.', help='放在哪个目录（默认当前目录）')
    p.add_argument('--level', default='原型级', help='交付深度：原型级 或 前端级')
    p.add_argument('--force', action='store_true', help='文件已存在时覆盖')

    p = sub.add_parser('check', help='一致性检查')
    p.add_argument('prd')
    p.add_argument('--final', action='store_true', help='交付前检查：未确认的〔建议〕也算必须修')

    p = sub.add_parser('flow', help='把 2.1 的流程图做成能用浏览器打开的网页')
    p.add_argument('prd')
    p.add_argument('--out-dir', default=None, help='输出目录（默认和 PRD 放一起）')

    p = sub.add_parser('mindmap', help='生成页面结构思维导图（html、md、opml）')
    p.add_argument('prd')
    p.add_argument('--out-dir', default=None, help='输出目录（默认和 PRD 放一起）')

    p = sub.add_parser('config', help='把各组件的后台配置项汇总进 4.2')
    p.add_argument('prd')

    p = sub.add_parser('brief', help='生成给 AI 的任务书')
    p.add_argument('prd')
    p.add_argument('--out', default=None, help='输出文件（默认 <产品名>-AI任务书.md）')

    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    if a.cmd == 'init':
        return gen.cmd_init(a.name, a.dir, a.level, a.force)
    if not _need_file(a.prd):
        return 2
    if a.cmd == 'check':
        doc = open_doc(a.prd)
        rep = check.run(doc, a.final)
        print(check.render(doc, rep, a.final))
        return 1 if rep.errors else 0
    if a.cmd == 'flow':
        return flow.cmd_flow(a.prd, a.out_dir)
    if a.cmd == 'mindmap':
        return mindmap.cmd_mindmap(a.prd, a.out_dir)
    if a.cmd == 'config':
        return gen.cmd_config(a.prd)
    if a.cmd == 'brief':
        return gen.cmd_brief(a.prd, a.out)
    return 2


if __name__ == '__main__':
    sys.exit(main())
