cmake_minimum_required(VERSION 3.10)
project(gtfs_precache C)

# Set C standard
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Read version from header file
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/gtfs_precache_version.h" version_h)
string(REGEX MATCH "GTFS_PRECACHE_VERSION_STRING \"([0-9]+\\.[0-9]+\\.[0-9]+)\"" _ ${version_h})
set(GTFS_PRECACHE_VERSION ${CMAKE_MATCH_1})

# Configure version information
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/gtfs_precache_version.h.in"
    "${CMAKE_CURRENT_BINARY_DIR}/gtfs_precache_version.h"
    @ONLY
)

# Find msgpack
if(WIN32)
    # On Windows, expect msgpack to be installed via vcpkg
    find_package(msgpack CONFIG REQUIRED)
    set(MSGPACK_LIBRARIES msgpackc-cxx)
else()
    # On Unix-like systems, try pkg-config first
    find_package(PkgConfig)
    if(PKG_CONFIG_FOUND)
        pkg_check_modules(MSGPACK REQUIRED msgpackc)
        if(NOT MSGPACK_FOUND)
            pkg_check_modules(MSGPACK REQUIRED msgpack)
        endif()
    else()
        # Fallback to find_library
        find_library(MSGPACK_LIBRARIES NAMES msgpackc msgpack)
        if(NOT MSGPACK_LIBRARIES)
            message(FATAL_ERROR "msgpack library not found")
        endif()
    endif()
endif()

# Add executable
add_executable(gtfs_precache gtfs_precache.c)

# Add include directories
target_include_directories(gtfs_precache PRIVATE 
    ${CMAKE_CURRENT_BINARY_DIR}
    ${MSGPACK_INCLUDE_DIRS}
)

# Link libraries
target_link_libraries(gtfs_precache PRIVATE ${MSGPACK_LIBRARIES})

# Platform-specific settings
if(WIN32)
    target_link_libraries(gtfs_precache PRIVATE psapi)
    # Set runtime library to MD/MDd
    set_property(TARGET gtfs_precache PROPERTY
        MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>DLL")
endif()

# Installation
install(TARGETS gtfs_precache
        RUNTIME DESTINATION bin) 