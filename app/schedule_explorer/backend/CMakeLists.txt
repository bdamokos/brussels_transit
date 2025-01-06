cmake_minimum_required(VERSION 3.10)
project(gtfs_precache C)

# Set C standard
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Find msgpack
if(WIN32)
    # On Windows, expect msgpack to be installed in a standard location
    # or specified via CMAKE_PREFIX_PATH
    find_package(msgpack CONFIG REQUIRED)
    set(MSGPACK_LIBRARIES msgpackc)
else()
    # On Unix-like systems, try pkg-config first
    find_package(PkgConfig)
    if(PKG_CONFIG_FOUND)
        pkg_check_modules(MSGPACK REQUIRED msgpack)
    else()
        # Fallback to find_library
        find_library(MSGPACK_LIBRARIES NAMES msgpack msgpackc)
        if(NOT MSGPACK_LIBRARIES)
            message(FATAL_ERROR "msgpack library not found")
        endif()
    endif()
endif()

# Add executable
add_executable(gtfs_precache gtfs_precache.c)

# Link libraries
target_link_libraries(gtfs_precache PRIVATE ${MSGPACK_LIBRARIES})

# Platform-specific settings
if(WIN32)
    target_link_libraries(gtfs_precache PRIVATE psapi)
endif()

# Installation
install(TARGETS gtfs_precache
        RUNTIME DESTINATION bin) 