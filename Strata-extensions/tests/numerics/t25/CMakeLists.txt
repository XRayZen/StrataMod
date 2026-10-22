cmake_minimum_required(VERSION 3.24)
project(t25_engram LANGUAGES CXX HIP)
find_package(hip CONFIG REQUIRED)
if(NOT T25_SNAPSHOT)
 message(FATAL_ERROR "Explicit immutable consumed source root required")
endif()
set(R "${T25_SNAPSHOT}")
set(E "${R}/Strata-extensions")
set_source_files_properties("${R}/src/core/device.cu" PROPERTIES LANGUAGE HIP)
add_executable(t25-engram fixture.hip
 ${E}/models/deepseek41/core.hip ${E}/models/deepseek41/ffn.hip ${E}/models/deepseek41/mhc.hip ${E}/models/deepseek41/kv.hip ${E}/models/deepseek41/attention.hip ${E}/models/deepseek41/engram_forward.hip
 ${E}/native/quant/quant.hip ${E}/native/cache/primary_supply.hip ${E}/native/cache/row_supply.hip ${E}/native/cache/lease_queue.cpp
 ${E}/models/deepseek41/engram.hip ${E}/models/deepseek41/engram.cpp ${E}/models/deepseek41/artifact.cpp ${E}/native/artifact/native_reader.cpp ${E}/native/io/span_provider.cpp ${E}/native/stats/measurement.cpp
 ${R}/src/core/device.cu ${R}/src/platform/direct_file.cpp)
target_include_directories(t25-engram PRIVATE ${E}/models/deepseek41 ${E}/native/artifact ${E}/native/io ${E}/native/stats ${E}/native/cache "${R}/include/strata/hip_compat" "${R}/include")
target_compile_features(t25-engram PRIVATE cxx_std_17)
target_compile_options(t25-engram PRIVATE -fno-fast-math -ffp-contract=off -fdenormal-fp-math=ieee)
target_compile_definitions(t25-engram PRIVATE STRATA_USE_HIP STRATA_HIP_ARCHS="gfx1100,gfx1201" NOMINMAX WIN32_LEAN_AND_MEAN T25_SOURCE_ID="${T25_SOURCE_ID}")
target_link_libraries(t25-engram PRIVATE hip::host psapi)
set_target_properties(t25-engram PROPERTIES HIP_STANDARD 17 HIP_STANDARD_REQUIRED YES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bundle")
