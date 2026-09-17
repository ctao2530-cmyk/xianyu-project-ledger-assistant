"""Offline, local-only recovery bundle. Never read .env or overwrite a workspace.
Caller must stop writers to obtain a consistent database + filesystem snapshot.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

ASSET_DIRS=('customer-images','customer-image-previews','requirement-attachments','requirement-exports','attachments')

def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):result.update(chunk)
    return result.hexdigest()

def check_database(path):
    with sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('backup database integrity failed')

def create_bundle(database, data_root, destination, *, writers_stopped=False):
    database,data_root,destination=map(Path,(database,data_root,destination))
    if not writers_stopped:raise ValueError('stop the service and confirm writers are stopped first')
    if destination.exists():raise ValueError('destination must not exist')
    if database.is_symlink() or not database.is_file():raise ValueError('invalid source database')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.xunying-backup-',dir=destination.parent));stage.chmod(0o700)
    try:
        target=stage/'database.sqlite3'
        with sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro',uri=True) as src, sqlite3.connect(target) as dst:src.backup(dst)
        target.chmod(0o600);check_database(target)
        for directory in ASSET_DIRS:
            source=data_root/directory
            if source.is_symlink():raise ValueError('symlinks are not allowed in backup assets')
            if not source.exists():continue
            for path in source.rglob('*'):
                if path.is_symlink():raise ValueError('symlinks are not allowed in backup assets')
                if path.is_file():
                    output=stage/'assets'/path.relative_to(data_root);output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    shutil.copyfile(path,output);output.chmod(0o600)
        files={str(p.relative_to(stage)):{'sha256':digest(p),'bytes':p.stat().st_size} for p in stage.rglob('*') if p.is_file()}
        manifest={'format':'xunying-local-recovery-v1','created_at':datetime.now(timezone.utc).isoformat(),'files':files,
                  'excluded':['environment credentials','logs','caches','pending download encryption keys'],
                  'restore_policy':'offline-only; do not start external integrations or reuse grants without review'}
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));(stage/'manifest.json').chmod(0o600)
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage);raise
    return manifest

def verify_bundle(bundle):
    bundle=Path(bundle)
    if bundle.is_symlink() or (bundle/'manifest.json').is_symlink():raise ValueError('invalid bundle')
    manifest=json.loads((bundle/'manifest.json').read_text())
    if manifest.get('format')!='xunying-local-recovery-v1':raise ValueError('unsupported backup format')
    actual=set()
    for path in bundle.rglob('*'):
        if path.is_symlink():raise ValueError('symlinks are not allowed')
        if path.is_file() and path!=bundle/'manifest.json':actual.add(str(path.relative_to(bundle)))
    if actual!=set(manifest['files']) or 'database.sqlite3' not in actual:raise ValueError('backup file inventory mismatch')
    for name,info in manifest['files'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or (name!='database.sqlite3' and (len(relative.parts)<3 or relative.parts[0]!='assets' or relative.parts[1] not in ASSET_DIRS)):
            raise ValueError('invalid backup member')
        path=bundle/relative
        if path.stat().st_size!=info['bytes'] or digest(path)!=info['sha256']:raise ValueError('backup checksum mismatch')
    check_database(bundle/'database.sqlite3')
    return manifest

def restore_to_new_directory(bundle,destination):
    bundle,destination=Path(bundle),Path(destination)
    verify_bundle(bundle)
    if destination.exists():raise ValueError('restore never overwrites an existing directory')
    destination.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.xunying-restore-',dir=destination.parent));stage.chmod(0o700)
    try:
        # Restores a reviewable offline bundle, not an automatically running app.
        shutil.copytree(bundle,stage,dirs_exist_ok=True)
        for path in stage.rglob('*'):path.chmod(0o700 if path.is_dir() else 0o600)
        verify_bundle(stage);stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage);raise
