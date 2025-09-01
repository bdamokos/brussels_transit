# Detect OS
UNAME_S := $(shell uname -s)

# Get version from header
VERSION := $(shell grep 'GTFS_PRECACHE_VERSION_STRING' gtfs_precache_version.h | cut -d'"' -f2)

# Common flags
CFLAGS = -Wall -O3

# Try to get flags from pkg-config when available (preferred)
PKGCONFIG := $(shell command -v pkg-config 2>/dev/null)
ifneq ($(PKGCONFIG),)
    # Detect which pkg-config name is available: msgpack, msgpackc, or msgpack-c
    ifeq ($(shell pkg-config --exists msgpack && echo yes || echo no),yes)
        MSGPACK_PKG := msgpack
    else ifeq ($(shell pkg-config --exists msgpackc && echo yes || echo no),yes)
        MSGPACK_PKG := msgpackc
    else ifeq ($(shell pkg-config --exists msgpack-c && echo yes || echo no),yes)
        MSGPACK_PKG := msgpack-c
    endif

    ifneq ($(strip $(MSGPACK_PKG)),)
        MSGPACK_CFLAGS := $(shell pkg-config --cflags $(MSGPACK_PKG) 2>/dev/null)
        MSGPACK_LDFLAGS := $(shell pkg-config --libs $(MSGPACK_PKG) 2>/dev/null)
    endif
endif

# OS-specific flags
ifeq ($(UNAME_S),Darwin)
    # macOS (Homebrew paths) - fallback paths if pkg-config didn't find anything
    CFLAGS += -I/opt/homebrew/include $(MSGPACK_CFLAGS)
    ifeq ($(strip $(MSGPACK_LDFLAGS)),)
        LDFLAGS = -L/opt/homebrew/lib -lmsgpackc
    else
        LDFLAGS = $(MSGPACK_LDFLAGS)
    endif
else
    # Linux - prefer pkg-config, fallback to standard include/lib and -lmsgpackc
    CFLAGS += -I/usr/include $(MSGPACK_CFLAGS)
    ifeq ($(strip $(MSGPACK_LDFLAGS)),)
        # Final fallback when pkg-config not available or no pc file found
        # Try the common C library name
        LDFLAGS = -lmsgpackc
    else
        LDFLAGS = $(MSGPACK_LDFLAGS)
    endif
endif

all: gtfs_precache

gtfs_precache: gtfs_precache.c gtfs_precache_version.h
	@echo "Building GTFS Precache Tool v$(VERSION)"
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)
	@echo "Build complete: v$(VERSION)"

clean:
	rm -f gtfs_precache

version:
	@echo "GTFS Precache Tool v$(VERSION)"

.PHONY: all clean version 