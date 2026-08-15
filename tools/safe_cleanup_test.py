#!/usr/bin/env python3
"""
safe_cleanup_test.py — 安全清理测试沙箱

用法：
    # 只打印会删什么，不删任何文件（推荐先跑这个）
    python3 tools/safe_cleanup_test.py

    # 真正执行（回收站模式，不直接删）
    python3 tools/safe_cleanup_test.py --live

    # 查看回收站
    python3 tools/safe_cleanup_test.py --trash

    # 清空回收站（7天前的文件）
    python3 tools/safe_cleanup_test.py --purge

安全设计：
    - 默认 dry-run，不碰任何文件
    - 正式模式也是移入 .trash/，不直接 unlink
    - 单独查看回收站命令
    - 永远不删 .py / .db / .key / .yaml
"""
import os, sys, json, time, logging
from pathlib import Path

BASE = Path('/opt/xiaonai')
logging.basicConfig(level=logging.INFO, format='[test] %(message)s')
log = logging.getLogger('test')

def show_plan():
    """Dry-run: show what would be cleaned (safe, no changes)."""
    print('═' * 50)
    print('🔍 清理预览模式 (dry-run) — 不删任何文件')
    print('═' * 50)

    # 模拟 cleanup_all_redundant 的逻辑但只打印不操作
    now = time.time()
    max_age = 72 * 3600
    ALLOWED = {'.docx','.doc','.xlsx','.txt','.md','.json','.mp3','.wav','.ogg','.bak','.bak2','.log','.temp','.tmp'}
    BLOCKED = {'knowledge','memory','diary'}
    total = 0

    def _preview(paths, label):
        nonlocal total
        found = 0
        for f in sorted(paths):
            if not f.exists():
                continue
            age_h = (now - f.stat().st_mtime) / 3600
            if age_h > 72:
                status = '🗑 待清理' if f.suffix.lower() in ALLOWED else '🔒 白名单拦截'
                if any(b in str(f.resolve()) for b in BLOCKED):
                    status = '🛡 黑名单拦截'
                print(f'  {status}  {f.name:40s} ({age_h:.0f}h)')
                found += 1
                total += 1
            else:
                print(f'  📄 保留(未到期)  {f.name:40s} ({age_h:.0f}h < 72h)')
        if not found:
            print(f'  (无)')
        print()

    print(f'\n📁 exports/:')
    _preview((BASE/'exports').iterdir() if (BASE/'exports').exists() else [], 'exports')

    print(f'\n📁 data/*.bak:')
    _preview([f for f in (BASE/'data').iterdir() if f.suffix in ('.bak','.bak2')] if (BASE/'data').exists() else [], 'bak')

    print(f'\n📁 data/voice_cache/:')
    _preview((BASE/'data/voice_cache').iterdir() if (BASE/'data/voice_cache').exists() else [], 'voice')

    print(f'\n📁 archive_bak/:')
    _preview((BASE/'archive_bak').iterdir() if (BASE/'archive_bak').exists() else [], 'archive')

    print(f'\n📁 根目录 tmp_*:')
    _preview([f for f in BASE.iterdir() if f.name.startswith('tmp_')], 'tmp')

    print(f'═' * 50)
    print(f'共计 {total} 个文件待清理（其中白名单拦截的不会删）')
    print(f'确认无误后运行: python3 {sys.argv[0]} --live')
    print('═' * 50)

def show_trash():
    """Show trash contents."""
    trash = BASE / '.trash'
    if not trash.exists():
        print('回收站为空')
        return
    total_size = 0
    now = time.time()
    print(f'{"文件名":40s} {"大小":8s} {"回收时长":12s}')
    print('-' * 62)
    for f in sorted(trash.iterdir()):
        if f.is_file():
            size = f.stat().st_size
            age_h = (now - f.stat().st_mtime) / 3600
            total_size += size
            mark = '⚠️ <7天' if age_h < 168 else '✅ 可清空'
            print(f'{f.name:40s} {size:>7d}  {age_h:>5.0f}h {mark}')
    print('-' * 62)
    print(f'共 {len(list(trash.iterdir()))} 个文件，{total_size/1024:.0f} KB')

def purge_trash():
    """Purge trash older than 7 days."""
    trash = BASE / '.trash'
    if not trash.exists():
        print('回收站为空')
        return
    now = time.time()
    count = 0
    for f in list(trash.iterdir()):
        if f.is_file() and (now - f.stat().st_mtime) > 7*86400:
            f.unlink()
            count += 1
    print(f'已清空 {count} 个过期文件')

def run_live():
    """Run real cleanup via scheduler_v5."""
    sys.path.insert(0, str(BASE))
    from scheduler_v5 import cleanup_all_redundant
    n = cleanup_all_redundant(dry_run=False)
    print(f'✅ 清理完成，{n} 个文件移入回收站')

if __name__ == '__main__':
    if '--live' in sys.argv:
        run_live()
    elif '--trash' in sys.argv:
        show_trash()
    elif '--purge' in sys.argv:
        purge_trash()
    else:
        show_plan()
