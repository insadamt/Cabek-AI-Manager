"""Initialize the Manager-owned private demo password without echoing it.

Depends on the installed native backend command and Manager Compose mounts. The
password is sent over stdin, never through arguments, logs, or public settings.
"""
import argparse
import getpass
import os
from pathlib import Path
from manager.storage import Store
from manager.system import compose_command
from manager.commands import CommandRunner


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path,default=Path(os.getenv('CABEK_MANAGER_HOME',Path(__file__).resolve().parents[1]/'.local')))
    parser.add_argument('--rotate',action='store_true')
    args=parser.parse_args()
    store=Store(args.home)
    if not store.read('installed',{}):parser.error('Install the ecosystem first.')
    password=getpass.getpass('Private demonstration password: ')
    confirmation=getpass.getpass('Confirm password: ')
    if password != confirmation:parser.error('Passwords do not match.')
    command=compose_command(store,'exec','-T','backend','python','scripts/demo_admin.py','--secret-file','/data/private-demo/secret.json','--stdin')
    if args.rotate:command.append('--rotate')
    CommandRunner([password]).run(command,input_text=password+'\n',quiet=True)
    print('Private demo password configured. Existing sessions are invalidated.')


if __name__=='__main__':main()
