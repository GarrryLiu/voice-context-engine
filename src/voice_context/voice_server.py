"""Compatible command entry point; HTTP composition and runtime live separately."""
import argparse
import os
from .server.app import create_app
from .server.compat import VoiceService
from .infra.runtime.service import TurnLease
from .server.http import limited_body
from .openai_provider import settings

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',default=None)
    parser.add_argument('--env-file',default='.env');parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--redis-url',default=os.environ.get('VOICE_REDIS_URL'))
    parser.add_argument('--mode',choices=['connected','demo'],default='connected')
    args=parser.parse_args()
    database=args.db or ('voice-demo.db' if args.mode=='demo' else os.environ.get('VOICE_DATABASE_URL','voice-local.db'))
    if args.mode=='connected':settings(args.env_file) # Validate privately before opening the listener.
    import uvicorn
    uvicorn.run(create_app(database,args.env_file,redis_url=args.redis_url,mode=args.mode),host='127.0.0.1',port=args.port,access_log=False,ws_max_size=16384,ws_max_queue=8)


if __name__=='__main__':main()
