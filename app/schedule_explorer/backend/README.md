<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [GTFS Precache Tool](#gtfs-precache-tool)
  - [Compilation](#compilation)
    - [On Debian/Ubuntu/Raspberry Pi:](#on-debianubunturaspberry-pi)
    - [On macOS:](#on-macos)
  - [Usage](#usage)
  - [Development](#development)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# GTFS Precache Tool

This directory contains a C-based tool for efficient GTFS data preprocessing, specifically designed for memory-constrained environments like the Raspberry Pi.

## Compilation

The tool requires the MessagePack development library:

### On Debian/Ubuntu/Raspberry Pi:
```bash
sudo apt-get update
sudo apt-get install libmsgpack-dev build-essential
```

### On macOS:
```bash
brew install msgpack
```

Then compile the tool:
```bash
make
```

## Usage

The tool is automatically used by the Python GTFS loader when available. If not found, the loader will fall back to a pure Python implementation.

## Development

- `gtfs_precache.c`: Main C implementation
- `Makefile`: Build configuration
- The tool reads GTFS stop_times.txt and outputs a msgpack file that's more memory-efficient to process 