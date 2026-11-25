#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LUNA_HOME = Path(os.environ.get('LUNA_HOME', str(ROOT.parent / 'LUNA')))
DEFAULT_BACKUP_DIR = ROOT / 'backups' / 'local'


def integrity_check(path):
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    conn.close()
    if result != 'ok':
        raise RuntimeError(f'数据库完整性检查失败: {path} -> {result}')


def backup_database(source, destination):
    source_conn = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_conn = sqlite3.connect(destination)
    source_conn.backup(destination_conn)
    destination_conn.close()
    source_conn.close()
    integrity_check(destination)


def add_tree(zf, source, prefix):
    if not source.exists():
        return 0
    count = 0
    for file in source.rglob('*'):
        if file.is_file():
            zf.write(file, f'{prefix}/{file.relative_to(source).as_posix()}')
            count += 1
    return count


def add_configs(zf):
    count = 0
    for file in (ROOT / 'data').iterdir():
        if file.is_file() and file.suffix in ('.json', '.txt') and file.name != 'ngrok_changes.log':
            zf.write(file, f'trainer/data/{file.name}')
            count += 1
    return count


def encrypt_file(source):
    openssl = shutil.which('openssl')
    if not openssl:
        raise RuntimeError('未找到 openssl，无法加密备份')
    destination = source.with_suffix(source.suffix + '.enc')
    subprocess.run([openssl, 'enc', '-aes-256-cbc', '-pbkdf2', '-salt',
                    '-in', str(source), '-out', str(destination), '-pass', 'env:BACKUP_PASSWORD'], check=True)
    source.unlink()
    return destination


def decrypt_file(source, destination):
    openssl = shutil.which('openssl')
    if not openssl:
        raise RuntimeError('未找到 openssl，无法解密备份')
    subprocess.run([openssl, 'enc', '-d', '-aes-256-cbc', '-pbkdf2',
                    '-in', str(source), '-out', str(destination), '-pass', 'env:BACKUP_PASSWORD'], check=True)


def backup_time(path):
    return datetime.strptime(path.name[15:30], '%Y%m%dT%H%M%S')


def prune_local_backups(directory):
    files = sorted(directory.glob('trainer-backup-*'), key=lambda p: p.name, reverse=True)
    keep = set(files[:7])
    weekly = [p for p in files if backup_time(p).weekday() == 6][:4]
    monthly = [p for p in files if backup_time(p).day == 1][:3]
    keep.update(weekly)
    keep.update(monthly)
    for file in files:
        if file not in keep:
            file.unlink()


def create_backup():
    output_dir = Path(os.environ.get('BACKUP_DIR', str(DEFAULT_BACKUP_DIR)))
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now()
    basename = f'trainer-backup-{created_at:%Y%m%dT%H%M%S}'
    remote = os.environ.get('BACKUP_REMOTE', '').strip()
    password = os.environ.get('BACKUP_PASSWORD', '')
    if remote and not password:
        raise RuntimeError('异地上传必须设置 BACKUP_PASSWORD，禁止上传未加密备份')
    with tempfile.TemporaryDirectory(prefix='trainer-backup-') as tmp:
        stage = Path(tmp)
        databases = {}
        for name, source in [('trainer/data/stats.db', ROOT / 'data' / 'stats.db'),
                             ('luna/data.db', LUNA_HOME / 'data.db')]:
            if source.exists():
                backup_database(source, stage / name)
                databases[name] = {'bytes': source.stat().st_size, 'integrity_check': 'ok'}
        zip_path = output_dir / f'{basename}.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name in databases:
                zf.write(stage / name, name)
            file_count = add_configs(zf)
            file_count += add_tree(zf, ROOT / 'backend' / 'static' / 'img', 'trainer/static/img')
            file_count += add_tree(zf, ROOT / 'data' / 'banner_uploads', 'trainer/data/banner_uploads')
            file_count += add_tree(zf, LUNA_HOME / 'uploads', 'luna/uploads')
            file_count += add_tree(zf, LUNA_HOME / 'secrets', 'luna/secrets')
            file_count += add_tree(zf, LUNA_HOME / 'public' / 'course-pages', 'luna/public/course-pages')
            manifest = {'created_at': created_at.isoformat(), 'databases': databases, 'other_files': file_count}
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        final_path = encrypt_file(zip_path) if password else zip_path
    prune_local_backups(output_dir)
    result = {'status': 'backup_created', 'archive': str(final_path),
              'encrypted': bool(password), 'offsite': 'pending'}
    if remote:
        if not shutil.which('rclone'):
            raise RuntimeError('已配置 BACKUP_REMOTE，但未安装 rclone；本地加密备份已保留')
        subprocess.run(['rclone', 'copy', str(final_path), remote, '--checksum'], check=True)
        result['offsite'] = remote
    print(json.dumps(result, ensure_ascii=False, indent=2))


def safe_extract(zf, destination):
    root = destination.resolve()
    for member in zf.infolist():
        target = (root / member.filename).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError(f'备份包含不安全路径: {member.filename}')
    zf.extractall(root)


def restore_backup(args):
    archive = Path(args.archive).resolve()
    if not archive.exists():
        raise RuntimeError(f'备份不存在: {archive}')
    destination = Path(args.dest).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError('恢复目录必须不存在或为空，禁止覆盖现有数据')
    with tempfile.TemporaryDirectory(prefix='trainer-restore-') as tmp:
        zip_path = archive
        if archive.suffix == '.enc':
            if not os.environ.get('BACKUP_PASSWORD'):
                raise RuntimeError('解密备份需要设置 BACKUP_PASSWORD')
            zip_path = Path(tmp) / 'backup.zip'
            decrypt_file(archive, zip_path)
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            safe_extract(zf, destination)
    checks = {}
    for name in ('trainer/data/stats.db', 'luna/data.db'):
        path = destination / name
        if path.exists():
            integrity_check(path)
            checks[name] = 'ok'
    if len(checks) != 2:
        raise RuntimeError('恢复结果缺少培训师或 LUNA 数据库，不能判定为恢复成功')
    print(json.dumps({'status': 'restore_verified', 'destination': str(destination),
                      'database_integrity': checks}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='培训师系统安全备份与独立恢复验证')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('backup')
    restore = sub.add_parser('restore')
    restore.add_argument('archive')
    restore.add_argument('--dest', required=True)
    args = parser.parse_args()
    if args.command == 'backup':
        create_backup()
    else:
        restore_backup(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'[BACKUP-ERROR] {e}', file=sys.stderr)
        sys.exit(1)
