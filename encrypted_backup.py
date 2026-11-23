# -*- coding: utf-8 -*-
"""Optional portable encrypted SQLite backup. No changes to default backups.
Requires the separate cryptography package. No network or upload.
"""
import getpass
import os
import sqlite3
import sys
from pathlib import Path

MAGIC = b'PHARMACY-BACKUP-1\n'
MAX_SIZE = 1024 * 1024 * 1024


def _crypto():
    if sys.version_info < (3, 11) or not hasattr(sqlite3.Connection, "serialize"):
        raise RuntimeError("Encrypted backups require Python 3.11 or later with SQLite serialize support.")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        return AESGCM, Scrypt
    except ImportError:
        raise RuntimeError('Optional encrypted backups require cryptography. Default app remains stdlib-only.') from None


def _key(password, salt):
    if len(password) < 12:
        raise ValueError('Use a passphrase of at least 12 characters.')
    _, scrypt = _crypto()
    return scrypt(salt=salt,length=32,n=2**15,r=8,p=1).derive(password.encode('utf-8'))


def _new_file(path, data):
    # Exclusive creation avoids accidentally replacing the only recovery copy.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise



def create(source, destination, password):
    aes, _ = _crypto()
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError('Destination must be a new file.')
    if source.stat().st_size > MAX_SIZE:
        raise ValueError("Source exceeds 1GB safety limit.")
    # SQLite online backup handles a live source without a torn file copy.
    src = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    snapshot = sqlite3.connect(':memory:')
    try:
        src.backup(snapshot)
        if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Source integrity check failed.')
        snapshot.execute('SELECT count(*) FROM drugs').fetchone()
        raw = snapshot.serialize()
    finally:
        snapshot.close();src.close()
    if len(raw)>MAX_SIZE:
        raise ValueError('Backup exceeds 1GB safety limit.')
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC+salt+nonce
    encrypted = aes(_key(password,salt)).encrypt(nonce,raw,header)
    _new_file(destination,header+encrypted)


def decrypt_to_new_file(source, destination, password):
    aes, _ = _crypto()
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError('Destination must be a new file, never the live database.')
    if source.stat().st_size>MAX_SIZE+128:
        raise ValueError('Backup exceeds safety limit.')
    data=source.read_bytes();size=len(MAGIC)+28
    if not data.startswith(MAGIC) or len(data)<size+16:
        raise ValueError('Unrecognized encrypted backup.')
    header=data[:size];salt=data[len(MAGIC):len(MAGIC)+16];nonce=header[-12:]
    try:
        raw=aes(_key(password,salt)).decrypt(nonce,data[size:],header)
    except Exception:
        raise ValueError('Wrong passphrase or damaged backup.') from None
    check=sqlite3.connect(':memory:')
    try:
        check.deserialize(raw)
        if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('Decrypted backup failed integrity check.')
        check.execute('SELECT count(*) FROM drugs').fetchone()
    finally:check.close()
    _new_file(destination,raw)


def main():
    if len(sys.argv)!=4 or sys.argv[1] not in ('create','decrypt'):
        print('Usage: py encrypted_backup.py create|decrypt SOURCE NEW_DESTINATION')
        return 2
    password=getpass.getpass('Backup passphrase (not saved): ')
    if sys.argv[1]=='create' and password!=getpass.getpass('Confirm passphrase: '):
        raise ValueError('Passphrases do not match.')
    try:
        (create if sys.argv[1]=='create' else decrypt_to_new_file)(sys.argv[2],sys.argv[3],password)
    finally:password=None
    print('Verified backup file created. Keep the passphrase separate. No upload was performed.')
    return 0

if __name__=='__main__':sys.exit(main())
