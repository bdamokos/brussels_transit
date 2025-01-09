<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [GTFS Precache Tool](#gtfs-precache-tool)
  - [Prerequisites](#prerequisites)
    - [On Debian/Ubuntu/Raspberry Pi:](#on-debianubunturaspberry-pi)
    - [On macOS:](#on-macos)
    - [On Windows:](#on-windows)
  - [Building](#building)
    - [Unix-like systems (Linux, macOS)](#unix-like-systems-linux-macos)
    - [Windows](#windows)
  - [Usage](#usage)
  - [Development](#development)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# GTFS Precache Tool

This directory contains a C-based tool for efficient GTFS data preprocessing, specifically designed for memory-constrained environments like the Raspberry Pi.

## Prerequisites

The tool requires the MessagePack development library:

### On Debian/Ubuntu/Raspberry Pi:
```bash
sudo apt-get update
sudo apt-get install libmsgpack-dev build-essential cmake
```

If you get a linking error with `-lmsgpack`, try installing the C library specifically:
```bash
sudo apt-get install libmsgpackc-dev
```

### On macOS:
```bash
brew install msgpack cmake
```

### On Windows:
1. Install [Visual Studio](https://visualstudio.microsoft.com/downloads/) with C++ support
2. Install [CMake](https://cmake.org/download/)
3. Install [vcpkg](https://github.com/Microsoft/vcpkg)
4. Install msgpack:
```bash
vcpkg install msgpack:x64-windows
```

## Building

### Unix-like systems (Linux, macOS)
You can use either Make or CMake:

Using Make:
```bash
make
```

Using CMake:
```bash
mkdir build
cd build
cmake ..
cmake --build .
```

### Windows
Using CMake:
```bash
mkdir build
cd build
cmake -DCMAKE_TOOLCHAIN_FILE=[path to vcpkg]/scripts/buildsystems/vcpkg.cmake ..
cmake --build . --config Release
```

## Usage

The tool is automatically used by the Python GTFS loader when available. If not found, the loader will fall back to a pure Python implementation.

To run manually:
```bash
./gtfs_precache <input_file> <output_file>
```

Arguments:
- `input_file`: Path to stop_times.txt
- `output_file`: Path for output msgpack file

Additional features:
- `--version`: Display the tool version

## Development

- `gtfs_precache.c`: Main C implementation
- `CMakeLists.txt`: CMake build configuration
- `Makefile`: Unix Make build configuration (alternative to CMake)
- The tool reads GTFS stop_times.txt and outputs a msgpack file that's more memory-efficient to process
- Cross-platform support for Linux, macOS, and Windows 