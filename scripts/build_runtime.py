"""Build the standard-library-only C++ runtime; no compilation at Python import."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

p=argparse.ArgumentParser();p.add_argument('--output',default='build/libvoice_runtime.so');p.add_argument('--sanitize',action='store_true');a=p.parse_args()
root=Path(__file__).resolve().parents[1];out=Path(a.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
compiler=shutil.which('clang++') or shutil.which('g++')
if compiler is None:raise SystemExit('C++17 compiler required')
flags=['-std=c++17','-O3','-Wall','-Wextra','-Werror','-pthread','-fPIC']
if a.sanitize:flags+=['-fsanitize=address,undefined','-fno-omit-frame-pointer']
subprocess.run([compiler,*flags,'-dynamiclib' if sys.platform=='darwin' else '-shared',str(root/'native/runtime.cpp'),'-o',str(out)],check=True)
print(out)
