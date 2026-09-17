"""Create/verify/restore an offline private bundle. No overwrite or service control."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from backend.app.services.local_backup import create_bundle, verify_bundle, restore_to_new_directory

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('create');create.add_argument('--database',type=Path,required=True);create.add_argument('--data-root',type=Path,required=True);create.add_argument('--destination',type=Path,required=True);create.add_argument('--writers-stopped',action='store_true')
    verify=sub.add_parser('verify');verify.add_argument('bundle',type=Path)
    restore=sub.add_parser('restore');restore.add_argument('bundle',type=Path);restore.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='create':create_bundle(args.database,args.data_root,args.destination,writers_stopped=args.writers_stopped)
    elif args.command=='verify':verify_bundle(args.bundle)
    else:restore_to_new_directory(args.bundle,args.destination)
    print('Offline recovery operation verified; no running service was changed.')
if __name__=='__main__':main()
