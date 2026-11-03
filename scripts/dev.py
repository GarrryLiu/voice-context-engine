"""Start one isolated local development profile. Does not start Docker or load keys."""
import argparse
import os
from pathlib import Path
import sys

root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('profile',choices=['product','infra','integration'])
p.add_argument('--port',type=int);p.add_argument('--db');p.add_argument('--env-file',default='.env')
a=p.parse_args()
profiles={'product':('demo',8766,'/product'),'infra':('connected',8767,'/lab'),'integration':('connected',8765,'/product')}
mode,port,route=profiles[a.profile];port=a.port or port
folder=root/'.local'/a.profile;folder.mkdir(parents=True,exist_ok=True)
database=a.db or str(folder/'workspace.db')
env=dict(os.environ);env['PYTHONPATH']=str(root/'src')+os.pathsep+env.get('PYTHONPATH','')
if mode=='demo':
    env.pop('VOICE_RUNTIME_LIBRARY',None);env.pop('VOICE_DATABASE_URL',None);env.pop('VOICE_REDIS_URL',None)
else:env.setdefault('VOICE_RUNTIME_LIBRARY',str(root/'build/libvoice_runtime.so'))
print(f'{a.profile}: http://127.0.0.1:{port}{route} (mode={mode})',flush=True)
os.chdir(root)
os.execve(sys.executable,[sys.executable,'-m','voice_context.voice_server','--mode',mode,'--port',str(port),'--db',database,'--env-file',a.env_file],env)
