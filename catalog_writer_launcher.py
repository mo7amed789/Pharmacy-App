# -*- coding: utf-8 -*-
"""Optional owner-only catalog publishing session, then the normal desktop app.
Run: py catalog_writer_launcher.py. No credential is written to disk.
"""
import getpass
import catalog_writer
import main


def run():
    print('Catalog writer session. Use only the approved Supabase Auth owner account.')
    print('Local changes remain saved when the publishing session expires.')
    email = input('Writer email: ').strip()
    if not email:
        return
    password = getpass.getpass('Writer password (not saved): ')
    try:
        catalog_writer.sign_in(email, password)
    except Exception:
        print('Sign-in failed. Check account, MFA requirements and connection.')
        return
    finally:
        password = None
    try:
        main.main()
    finally:
        catalog_writer.sign_out()


if __name__ == '__main__':
    run()
