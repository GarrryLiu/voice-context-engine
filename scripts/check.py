"""Explicit test tracks; no model calls or Docker startup are performed here."""
import argparse
import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
INFRA={'test_broker_recovery.py','test_capture_worklet.py','test_conversation.py','test_engine.py','test_merge.py',
       'test_models.py','test_native.py','test_openai_provider.py','test_pipeline.py',
       'test_retrieval.py','test_routing.py','test_sessions.py','test_tasks.py','test_transcripts.py'}
PRODUCT={'test_documents.py','test_product_workspace.py'}
INTEGRATION={'test_broker.py','test_cache.py','test_postgres.py','test_realtime_stt.py',
             'test_voice_browser.py','test_voice_faults.py','test_voice_server.py'}


def owner(path):
    if path.parts[0] in {'contracts','product'}:return path.parts[0]
    if path.name in INFRA:return 'infra'
    if path.name in PRODUCT:return 'product'
    if path.name in INTEGRATION:return 'integration'
    raise ValueError(f'Assign test ownership in scripts/check.py: {path}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('track',choices=['contracts','product','infra','integration','all'])
    parser.add_argument('--browser',action='store_true')
    parser.add_argument('--native',action='store_true')
    parser.add_argument('--services',action='store_true',help='require explicitly configured local service DSNs')
    parser.add_argument('--strict',action='store_true',help='fail if any selected test is skipped')
    parser.add_argument('--list',action='store_true')
    args=parser.parse_args();os.chdir(ROOT)
    os.environ['PYTHONPATH']=str(ROOT/'src')+os.pathsep+os.environ.get('PYTHONPATH','')
    files=sorted((ROOT/'tests').rglob('test*.py'));assigned=[(p,owner(p.relative_to(ROOT/'tests'))) for p in files]
    selected=[p for p,track in assigned if args.track=='all' or track==args.track]
    if args.list:
        for p,track in assigned:print(f'{track:12} {p.relative_to(ROOT)}')
        return 0
    if args.track in {'product','contracts'}:
        os.environ.pop('VOICE_RUNTIME_LIBRARY',None)
        for key in ['VOICE_TEST_POSTGRES','VOICE_TEST_KAFKA','VOICE_TEST_REDIS']:os.environ.pop(key,None)
        if args.native or args.services:parser.error('product/contracts tracks do not need native or external services')
    if args.browser:os.environ['VOICE_BROWSER_TEST']='1'
    else:os.environ.pop('VOICE_BROWSER_TEST',None)
    if args.native:
        subprocess.run([sys.executable,str(ROOT/'scripts/build_runtime.py')],check=True)
        os.environ['VOICE_RUNTIME_LIBRARY']=str(ROOT/'build/libvoice_runtime.so')
    if args.services:
        required=['VOICE_TEST_POSTGRES','VOICE_TEST_KAFKA','VOICE_TEST_REDIS']
        if any(not os.environ.get(k) for k in required):parser.error('set all VOICE_TEST_POSTGRES, VOICE_TEST_KAFKA, VOICE_TEST_REDIS variables')
        subprocess.run([sys.executable,str(ROOT/'scripts/wait_infra.py')],check=True)
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
    loader=unittest.TestLoader();suite=unittest.TestSuite()
    for path in selected:
        name='.'.join(path.relative_to(ROOT/'tests').with_suffix('').parts)
        suite.addTests(loader.loadTestsFromModule(importlib.import_module(name)))
    print(f'Track: {args.track}; files: {len(selected)}; browser: {args.browser}; native build: {args.native}',flush=True)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if args.strict and result.skipped:
        print(f'Strict profile rejected {len(result.skipped)} skipped checks.',file=sys.stderr);return 1
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
