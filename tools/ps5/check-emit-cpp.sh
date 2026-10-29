#!/bin/sh
# Byte-identical check of the C++ emitter (native/recomp/gen/emit_cpp.*) against saturn-recomp's
# Python one (MIT).
#   tools/ps5/check-emit-cpp.sh DUMP PY_GEN_DIR [WORK_DIR]
# DUMP and PY_GEN_DIR come from one run of tools/ps5/gen-dump-discovery.py (both game-derived: keep
# them outside the repository). report.txt and scene-data-entries.tsv are not emitted by the port.
set -eu
dump=$1 ref=$2 work=${3:-${TMPDIR:-/tmp}/sf3-emit-cpp}
here=$(cd "$(dirname "$0")/../.." && pwd)
mkdir -p "$work"
${CXX:-g++} -std=c++20 -O2 -Wall -o "$work/sf3-emit-cpp" \
    "$here/native/recomp/gen/emit_cpp.cpp" "$here/native/recomp/gen/sh2_text.cpp" "$here/native/recomp/gen/emit_cpp_main.cpp"
rm -rf "$work/out"
"$work/sf3-emit-cpp" "$dump" "$work/out"
diff -r -x report.txt -x scene-data-entries.tsv "$ref" "$work/out"
echo "check-emit-cpp: identical"
