"""Start an isolated local profile. Daily mode validates private configuration and backs up existing data."""
import argparse
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('profile',choices=['product','infra','integration','daily'])
p.add_argument('--port',type=int);p.add_argument('--db');p.add_argument('--env-file',default='.env')
p.add_argument('--map-llm',action='store_true',help='Enable real model map suggestions in product demo')
a=p.parse_args()
a.env_file=str(Path(a.env_file).expanduser().resolve())
profiles={'product':('demo',8766,'/product'),'infra':('connected',8767,'/lab'),'integration':('connected',8765,'/product'),'daily':('connected',8768,'/product')}
mode,port,route=profiles[a.profile];port=a.port or port
folder=root/'.local'/a.profile;folder.mkdir(parents=True,exist_ok=True)
database=str(Path(a.db).expanduser().resolve()) if a.db else str(folder/'workspace.db')
env=dict(os.environ);env['PYTHONPATH']=str(root/'src')+os.pathsep+env.get('PYTHONPATH','')
if a.profile=='daily':
    sys.path.insert(0,str(root/'src'))
    from voice_context.openai_provider import settings
    settings(a.env_file) # Validate without printing credentials or making calls.
    library=Path(env.get('VOICE_RUNTIME_LIBRARY',str(root/'build/libvoice_runtime.so')))
    if not library.is_file():p.error('Build the voice runtime first: python scripts/build_runtime.py')
    if Path(database).is_file():
        from voice_context.product.backup import snapshot
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup=snapshot(database,folder/'backups'/f'workspace-{stamp}.db')
        print(f'Verified startup backup: {backup}',flush=True)
if mode=='demo':
    env.pop('VOICE_RUNTIME_LIBRARY',None);env.pop('VOICE_DATABASE_URL',None);env.pop('VOICE_REDIS_URL',None)
else:env.setdefault('VOICE_RUNTIME_LIBRARY',str(root/'build/libvoice_runtime.so'))
print(f'{a.profile}: http://127.0.0.1:{port}{route} (mode={mode})',flush=True)
os.chdir(root)
os.execve(sys.executable,[sys.executable,'-m','voice_context.voice_server','--mode',mode,'--port',str(port),'--db',database,'--env-file',a.env_file]+(['--map-llm'] if a.map_llm else []),env)
