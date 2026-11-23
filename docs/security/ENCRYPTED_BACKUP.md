# Optional encrypted portable backup

This separate CLI requires Python 3.11 or later (the documented Windows launcher uses 3.11) and cryptography from requirements-backup.txt. Default automatic backups remain unchanged, unencrypted and local. Installing the optional package on the owner's computer is a separate step, not performed by this PR.

Create: `py encrypted_backup.py create pharmacy.db D:\backups\pharmacy.enc`
Decrypt for inspection: `py encrypted_backup.py decrypt D:\backups\pharmacy.enc recovered.db`

Enter a long unique passphrase in the local hidden terminal prompt, never in chat. It is not saved or recoverable. Keep it separately from the backup. Losing it means losing recovery access. Create refuses an existing destination; decrypt creates a NEW file, never overwrites the active database. Use the normal reviewed restore process only after inspecting the recovered database.

Uses SQLite online backup to memory, integrity checks, random salt and nonce, scrypt(32768,8,1) and AES-256-GCM authenticated encryption. Temporary plaintext is not written to disk. Memory use is proportional to database size, with a 1GB safety limit. Destination must be a private path, not a shared temporary folder. No uploads or schedules are created. An encrypted file on the same disk is not off-device backup; manually copy to a separate protected device or approved storage and test recovery. No cloud destination has been selected.

Tests cover roundtrip, hidden record text, wrong password, tampering and refusing overwrite. Target Windows recovery still needs validation before relying on the tool for real data.
