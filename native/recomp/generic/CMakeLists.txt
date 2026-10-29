# The generic game build (MIT): the runtime, the x86-64 backend's loader and the SH-2 interpreter, and no
# code or data made from a disc. It runs the module set the generator wrote from the user's own disc
# (sf3-gen --x64-set, ../gen/x64_set.cpp), with the interpreter for anything the set misses.
#   cmake -S native/recomp/generic -B build -DSATURN_RUNTIME=<saturn-recomp>/runtime [-DSATURN_EXTRA=file.cmake]
cmake_minimum_required(VERSION 3.20)
project(sf3_generic CXX)
set(CMAKE_CXX_STANDARD 20)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
if(NOT SATURN_RUNTIME)
  message(FATAL_ERROR "SATURN_RUNTIME: saturn-recomp's runtime/ with tools/runtime-diagnostics.patch applied")
endif()
get_filename_component(SF3_RECOMP ${CMAKE_CURRENT_LIST_DIR}/.. ABSOLUTE)
set(SF3_GEN ${SF3_RECOMP}/gen)
# what the runtime links as "recomp": the empty generated tables and the cache loader
add_library(recomp STATIC ${SF3_RECOMP}/gen/modules_none.cpp ${SF3_GEN}/x64_rt.cpp ${SF3_GEN}/code_cache.cpp
    ${SF3_GEN}/loader_posix.cpp ${SF3_GEN}/module_set.cpp)
target_include_directories(recomp PUBLIC ${SATURN_RUNTIME}/include ${SF3_GEN} ${SF3_RECOMP})
# objects, so an executable links them whole (a host reaches them through weak references)
add_library(sf3_x64_set OBJECT ${SF3_GEN}/x64_set.cpp)
target_include_directories(sf3_x64_set PRIVATE ${SATURN_RUNTIME}/include ${SF3_GEN})
add_library(sf3_interp OBJECT ${SF3_RECOMP}/sh2_interp.cpp ${SF3_RECOMP}/interp_fallback.cpp)
target_include_directories(sf3_interp PRIVATE ${SATURN_RUNTIME}/include ${SF3_RECOMP})
include(${SATURN_RUNTIME}/runtime.cmake)
if(DEFINED SATURN_EXTRA)
  include(${SATURN_EXTRA})
endif()
