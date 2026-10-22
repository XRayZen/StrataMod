cmake_minimum_required(VERSION 3.24)
project(strata_ext_host_fixture LANGUAGES CXX)

if(NOT WIN32 OR NOT MSVC)
  message(FATAL_ERROR "T06 host fixture is scoped to Windows MSVC")
endif()

get_filename_component(OWNED_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
get_filename_component(WORKTREE_ROOT "${OWNED_ROOT}/.." ABSOLUTE)
set(COMPILED_INPUTS
  Strata-extensions/native/include/strata_ext/provenance.hpp
  Strata-extensions/native/provenance.cpp
  Strata-extensions/tests/native/host_fixture.cpp)
set(IDENTITY_MATERIAL "")
foreach(INPUT IN LISTS COMPILED_INPUTS)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${WORKTREE_ROOT}/${INPUT}")
  file(SHA256 "${WORKTREE_ROOT}/${INPUT}" INPUT_HASH)
  string(APPEND IDENTITY_MATERIAL "${INPUT}|${INPUT_HASH}\n")
endforeach()
string(SHA256 OWNED_SOURCE_ID "${IDENTITY_MATERIAL}")

add_executable(strata-ext-host-fixture provenance.cpp ../tests/native/host_fixture.cpp)
target_include_directories(strata-ext-host-fixture PRIVATE include)
target_compile_features(strata-ext-host-fixture PRIVATE cxx_std_17)
target_compile_definitions(strata-ext-host-fixture PRIVATE
  STRATA_EXT_REFERENCE_BASE="477ac13cbe8e582c20484871ce459d20d82df09d"
  STRATA_EXT_SOURCE_ID="${OWNED_SOURCE_ID}" WIN32_LEAN_AND_MEAN NOMINMAX)
target_compile_options(strata-ext-host-fixture PRIVATE /W4 /WX /utf-8)
target_link_libraries(strata-ext-host-fixture PRIVATE bcrypt)
# This CRT choice is confined to this CPU test executable, not a future engine.
set_target_properties(strata-ext-host-fixture PROPERTIES
  MSVC_RUNTIME_LIBRARY MultiThreaded
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bundle")
