#!/bin/sh
# One disc to an x64 game tree: probe, module audit, sf3-gen --x64, then a CMake tree whose function
# bodies are the code caches (p_*_x64.cpp stubs), with the SH-2 interpreter as the fallback for any
# code the profile missed (native/recomp/interp_fallback.cpp; the host calls
# sf3_interp_fallback_install()).
#   tools/ps5/x64-profile.sh CUE WORK FRAMEWORK RUNTIME_DIR
# FRAMEWORK is a saturn-recomp checkout with tools/runtime-diagnostics.patch applied; RUNTIME_DIR
# its runtime/. Writes WORK/stage, WORK/out (WORK/out/x64 = the caches, for SF3_X64_DIR) and
# WORK/tree (configure it with -DSATURN_RUNTIME=RUNTIME_DIR). Everything under WORK is
# game-derived: keep it outside the repo.
set -eu
cue=$1 work=$2 framework=$3 runtime=$4
here=$(cd "$(dirname "$0")/../.." && pwd)
g=$here/native/recomp/gen
mkdir -p "$work"
python3 -B "$here/tools/probe.py" --cue "$cue" --framework "$framework" --out "$work/stage" >"$work/probe.log"
prof=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['profile'])" "$work/stage/revision.json")
python3 -B "$here/tools/audit-modules.py" --work "$work/stage" --profile "$here/profiles/$prof" \
    --out "$work/stage/module-audit" >"$work/audit.log"
[ -x "$work/../sf3-gen" ] || ${CXX:-g++} -std=c++20 -O2 -Wall -Wno-unused-function -o "$work/../sf3-gen" \
    "$g/gen_main.cpp" "$g/profile_gen.cpp" "$g/discovery.cpp" "$g/emit_cpp.cpp" "$g/emit_x64.cpp" \
    "$g/code_cache.cpp" "$g/sh2_text.cpp"
rm -rf "$work/out" "$work/tree"
"$work/../sf3-gen" --work "$work/stage" --profile "$work/stage/module-audit/candidate-profile.json" \
    --out "$work/out" --runtime "$runtime" --x64 >"$work/gen.log"
cp -r "$work/out" "$work/tree"; rm -rf "$work/tree/x64"
python3 - "$work/tree" "$here/native/recomp" <<'PY'
import re, glob, os, sys
d, r = sys.argv[1:]; g = r + '/gen'; os.chdir(d)
s = open('CMakeLists.txt').read()
s = re.sub(r'    p_\w+_\d{3}\.cpp\n', '', s)
add = ''.join(f'    {f}\n' for f in sorted(glob.glob('p_*_x64.cpp')))
add += ''.join(f'    {g}/{f}\n' for f in ('x64_rt.cpp', 'code_cache.cpp', 'loader_posix.cpp'))
s = s.replace('add_library(recomp STATIC\n', 'add_library(recomp STATIC\n' + add)
s = s.replace('target_include_directories(recomp PUBLIC ${SATURN_RUNTIME}/include)',
              'target_include_directories(recomp PUBLIC ${SATURN_RUNTIME}/include ' + g + ' ' + r + ')')
# the interpreter fallback: objects, so an executable links them whole (the host's reference to
# sf3_interp_fallback_install is weak and would not pull them out of a static library)
s = s.replace('target_include_directories(recomp PUBLIC', 'add_library(sf3_interp OBJECT ' + r + '/sh2_interp.cpp ' + r +
              '/interp_fallback.cpp)\ntarget_include_directories(sf3_interp PRIVATE ${SATURN_RUNTIME}/include ' + r + ')\n'
              'target_include_directories(recomp PUBLIC', 1)
open('CMakeLists.txt', 'w').write(s)
PY
echo "$prof: $(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['modules']))" "$work/stage/module-audit/candidate-profile.json") modules -> $work/tree"
