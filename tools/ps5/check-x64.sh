#!/bin/sh
# x86-64 backend check: generate C++ and x64 code caches with sf3-gen --x64, build the C++ tree (reference)
# and a tree whose function bodies are the caches (p_*_x64.cpp stubs + x64_rt/code_cache/loader_posix),
# then compare the runtime statehash of both over the agent protocol at several vblanks.
#   tools/ps5/check-x64.sh WORK PROFILE RUNTIME_DIR CUE [SCRATCH] [VBLANK...]
# Everything under SCRATCH is game-derived: keep it outside the repo.
set -eu
work=$1 profile=$2 runtime=$3 cue=$4 tmp=${5:-${TMPDIR:-/tmp}/sf3-x64-check}
shift 4; [ $# -gt 0 ] && shift
here=$(cd "$(dirname "$0")/../.." && pwd)
g=$here/native/recomp/gen
mkdir -p "$tmp"
${CXX:-g++} -std=c++20 -O2 -Wall -Wno-unused-function -o "$tmp/sf3-gen" "$g/gen_main.cpp" "$g/profile_gen.cpp" \
    "$g/discovery.cpp" "$g/emit_cpp.cpp" "$g/emit_x64.cpp" "$g/code_cache.cpp" "$g/sh2_text.cpp"
rm -rf "$tmp/out" "$tmp/ref" "$tmp/x64"
"$tmp/sf3-gen" --work "$work" --profile "$profile" --out "$tmp/out" --runtime "$runtime" --x64 >/dev/null
mkdir -p "$tmp/ref" "$tmp/x64"
cp -r "$tmp/out" "$tmp/ref/gen"; rm -rf "$tmp/ref/gen/x64" "$tmp/ref/gen"/p_*_x64.cpp
cp -r "$tmp/out" "$tmp/x64/gen"; rm -rf "$tmp/x64/gen/x64"
python3 - "$tmp/x64/gen" "$g" <<'PY'
import re, glob, os, sys
d, g = sys.argv[1:]; os.chdir(d)
s = open('CMakeLists.txt').read()
s = re.sub(r'    p_\w+_\d{3}\.cpp\n', '', s)
add = ''.join(f'    {f}\n' for f in sorted(glob.glob('p_*_x64.cpp'))) + ''.join(f'    {g}/{f}\n' for f in ('x64_rt.cpp', 'code_cache.cpp', 'loader_posix.cpp'))
s = s.replace('add_library(recomp STATIC\n', 'add_library(recomp STATIC\n' + add)
s = s.replace('target_include_directories(recomp PUBLIC ${SATURN_RUNTIME}/include)', 'target_include_directories(recomp PUBLIC ${SATURN_RUNTIME}/include ' + g + ')')
open('CMakeLists.txt', 'w').write(s)
PY
for t in ref x64; do
    cmake -G Ninja -S "$tmp/$t/gen" -B "$tmp/$t/build" -DCMAKE_CXX_COMPILER=${CLANGXX:-clang++} -DSATURN_RUNTIME="$runtime" >/dev/null
    ninja -C "$tmp/$t/build" saturn >/dev/null
done
python3 "$here/tools/ps5/x64-statehash.py" "$tmp/ref/build/saturn" "$tmp/x64/build/saturn" "$tmp/out/x64" "$cue" "$tmp/run" "$@"
