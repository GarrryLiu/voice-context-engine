#!/usr/bin/env python3
"""Bootstrap and run the local web product. Requires Python 3.11+."""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser

ROOT = Path(__file__).resolve().parent


def dependency_stamp():
    return hashlib.sha256((ROOT / 'pyproject.toml').read_bytes() +
                          str(sys.version_info[:2]).encode()).hexdigest()


def choose_port(requested):
    candidates = [requested] if requested else range(8780, 8800)
    for port in candidates:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise ValueError('Port unavailable. Choose another with --port; no running server was stopped.')


def choose_mode(mode, env_file):
    if mode == 'demo':
        return mode
    from dotenv import dotenv_values
    values = dotenv_values(env_file)
    configured = any(os.environ.get(k) or values.get(k)
                     for k in ('LLM_API_KEY', 'LLM_MODEL'))
    if mode == 'connected' or configured:
        from voice_context.openai_provider import settings
        settings(env_file)
        return 'connected'
    return 'demo'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['auto', 'demo', 'connected'], default='auto')
    parser.add_argument('--env-file', default=str(ROOT / '.env'))
    parser.add_argument('--port', type=int)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='Reinstall Python dependencies')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error('Install Python 3.11 or newer first.')
    if os.name == 'nt':
        parser.error('Use WSL with Python 3.11+ on Windows.')
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    folder = ROOT / '.local' / 'quickstart'
    folder.mkdir(parents=True, exist_ok=True)
    environment = folder / 'venv'
    python = environment / 'bin' / 'python'
    marker = environment / '.dependencies'
    # Re-enter in the managed environment before importing optional packages.
    if Path(sys.prefix).resolve() != environment.resolve():
        if not python.exists():
            print('Preparing isolated Python environment…', flush=True)
            venv.EnvBuilder(with_pip=True).create(environment)
        os.execv(str(python), [str(python), str(ROOT / 'run.py'), *sys.argv[1:]])
    stamp = dependency_stamp()
    if args.refresh or not marker.exists() or marker.read_text() != stamp:
        print('Installing web dependencies (internet required on first launch)…', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-e', str(ROOT) + '[voice]'], check=True)
        marker.write_text(stamp)
    env_file = str(Path(args.env_file).expanduser().resolve())
    mode = choose_mode(args.mode, env_file)
    port = choose_port(args.port)
    if mode == 'connected':
        library = ROOT / 'build' / 'libvoice_runtime.so'
        sources = [ROOT / 'scripts/build_runtime.py', *list((ROOT / 'native').rglob('*'))]
        if not library.exists() or any(p.is_file() and p.stat().st_mtime > library.stat().st_mtime for p in sources):
            print('Building C++ voice runtime (C++17 compiler required)…', flush=True)
            subprocess.run([str(python), str(ROOT / 'scripts/build_runtime.py')], cwd=ROOT, check=True)
    env = dict(os.environ)
    # Keep this local product independent of optional external infrastructure.
    for key in ('VOICE_DATABASE_URL', 'VOICE_REDIS_URL', 'VOICE_RUNTIME_LIBRARY'):
        env.pop(key, None)
    database = folder / (mode + '.db')
    url = f'http://127.0.0.1:{port}/product'
    print(f'Local {mode} workspace: {url}\nDatabase: {database}', flush=True)
    if mode == 'demo':
        print('Demo: typed input, fixed replies and silent audio. Real voice and AI maps require an API key.\nSee README for connected setup.', flush=True)
    else:
        print('Connected: model requests use your API account and may incur charges.', flush=True)
    process = subprocess.Popen([str(python), str(ROOT / 'scripts/dev.py'),
                                'daily' if mode == 'connected' else 'product',
                                '--port', str(port), '--db', str(database), '--env-file', env_file],
                               cwd=ROOT, env=env)
    try:
        for _ in range(200):
            if process.poll() is not None:
                raise RuntimeError('Web server exited before becoming ready; see the startup message above.')
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (OSError, ValueError):
                time.sleep(0.1)
        else:
            raise RuntimeError('Web server did not become ready within the startup window.')
        print('Ready. Press Ctrl+C to stop; your workspace remains saved.', flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        # Configuration validation errors contain no credential values.
        print(f'Startup failed: {exc}', file=sys.stderr)
        sys.exit(1)
