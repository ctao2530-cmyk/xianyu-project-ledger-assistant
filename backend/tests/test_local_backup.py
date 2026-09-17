import json
import sqlite3
import pytest
from backend.app.services.local_backup import create_bundle,verify_bundle,restore_to_new_directory

def test_recovery_preserves_database_original_bytes_and_excludes_credentials(tmp_path):
    root=tmp_path/'source';root.mkdir();db=root/'source.db'
    with sqlite3.connect(db) as conn:conn.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)');conn.execute("INSERT INTO sample VALUES(1,'synthetic')")
    (root/'.env').write_text('NEVER_INCLUDE=synthetic');image=root/'customer-images'/'2026'/'original.png';image.parent.mkdir(parents=True);image.write_bytes(b'original bytes including synthetic EXIF')
    bundle=tmp_path/'bundle'
    with pytest.raises(ValueError):create_bundle(db,root,bundle)
    create_bundle(db,root,bundle,writers_stopped=True);manifest=verify_bundle(bundle)
    assert not any('.env' in f for f in manifest['files'])
    restored=tmp_path/'restored';restore_to_new_directory(bundle,restored)
    assert (restored/'assets/customer-images/2026/original.png').read_bytes()==image.read_bytes()
    with sqlite3.connect(restored/'database.sqlite3') as conn:assert conn.execute('SELECT value FROM sample').fetchone()==('synthetic',)
    with pytest.raises(ValueError):restore_to_new_directory(bundle,restored)
    (bundle/'assets/customer-images/2026/original.png').write_bytes(b'tampered')
    with pytest.raises(ValueError):verify_bundle(bundle)

def test_backup_rejects_symlinks_and_unlisted_files(tmp_path):
    db=tmp_path/'source.db'
    with sqlite3.connect(db) as conn:conn.execute('CREATE TABLE sample(id INTEGER)')
    assets=tmp_path/'customer-images';assets.mkdir();(assets/'link').symlink_to(db)
    with pytest.raises(ValueError):create_bundle(db,tmp_path,tmp_path/'backup',writers_stopped=True)
    assert not (tmp_path/'backup').exists()
