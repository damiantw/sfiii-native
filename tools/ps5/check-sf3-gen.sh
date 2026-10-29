#!/bin/sh
# End-to-end check of the standalone C++ generator (sf3-gen: native/recomp/gen/{gen_main,profile_gen,
# discovery,...}) against saturn-recomp's Python generate (MIT), plus the discovery-only checker.
#   tools/ps5/check-sf3-gen.sh WORK PROFILE DUMP PY_GEN_DIR RUNTIME_DIR [SCRATCH]
# WORK is the extraction work dir; DUMP and PY_GEN_DIR come from one run of
# tools/ps5/gen-dump-discovery.py with the same WORK/PROFILE (game-derived: keep them outside the repo).
# Only report.txt is allowed to differ.
set -eu
work=$1 profile=$2 dump=$3 ref=$4 runtime=$5 tmp=${6:-${TMPDIR:-/tmp}/sf3-gen-check}
here=$(cd "$(dirname "$0")/../.." && pwd)
g=$here/native/recomp/gen
mkdir -p "$tmp"
${CXX:-g++} -std=c++20 -O2 -Wall -o "$tmp/sf3-discovery-check" \
    "$g/discovery_check_main.cpp" "$g/discovery.cpp" "$g/emit_cpp.cpp" "$g/sh2_text.cpp"
${CXX:-g++} -std=c++20 -O2 -Wall -o "$tmp/sf3-gen" \
    "$g/gen_main.cpp" "$g/profile_gen.cpp" "$g/discovery.cpp" "$g/emit_cpp.cpp" "$g/emit_x64.cpp" \
    "$g/code_cache.cpp" "$g/sh2_text.cpp"
"$tmp/sf3-discovery-check" "$dump"
rm -rf "$tmp/out"
"$tmp/sf3-gen" --work "$work" --profile "$profile" --out "$tmp/out" --runtime "$runtime" --specs "$tmp/q.txt" >/dev/null
grep '^Q' "$dump" | diff - "$tmp/q.txt"
diff -r -x report.txt "$ref" "$tmp/out"
echo "check-sf3-gen: identical"
