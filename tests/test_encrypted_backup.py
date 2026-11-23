import tempfile,sqlite3,unittest
from pathlib import Path
from contextlib import closing
import encrypted_backup as backup

class BackupTests(unittest.TestCase):
 def test_roundtrip_tamper_wrong_password_and_no_overwrite(self):
  with tempfile.TemporaryDirectory()as d:
   src=Path(d)/'live.db';enc=Path(d)/'safe.enc';restored=Path(d)/'restored.db'
   with closing(sqlite3.connect(src)) as c, c:
    c.execute('CREATE TABLE drugs(id integer,name text)');c.execute("INSERT INTO drugs VALUES(1,'Synthetic private record')")
   password='synthetic passphrase only'
   backup.create(src,enc,password)
   self.assertNotIn(b'Synthetic private record',enc.read_bytes())
   backup.decrypt_to_new_file(enc,restored,password)
   with closing(sqlite3.connect(restored)) as c:self.assertEqual(c.execute('SELECT name FROM drugs').fetchone()[0],'Synthetic private record')
   with self.assertRaises(ValueError):backup.decrypt_to_new_file(enc,src,password)
   with self.assertRaises(ValueError):backup.create(src,enc,password)
   with self.assertRaises(ValueError):backup.decrypt_to_new_file(enc,Path(d)/'bad.db','incorrect password')
   self.assertFalse((Path(d)/'bad.db').exists())
   data=bytearray(enc.read_bytes());data[-1]^=1;enc.write_bytes(data)
   with self.assertRaises(ValueError):backup.decrypt_to_new_file(enc,Path(d)/'tampered.db',password)
   self.assertFalse((Path(d)/'tampered.db').exists())

if __name__=='__main__':unittest.main()
