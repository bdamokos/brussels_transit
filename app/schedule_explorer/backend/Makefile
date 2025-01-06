# Detect OS
UNAME_S := $(shell uname -s)

# Get version from header
VERSION := $(shell grep 'GTFS_PRECACHE_VERSION_STRING' gtfs_precache_version.h | cut -d'"' -f2)

# Common flags
CFLAGS = -Wall -O3

# OS-specific flags
ifeq ($(UNAME_S),Darwin)
    # macOS (Homebrew paths)
    CFLAGS += -I/opt/homebrew/include
    LDFLAGS = -L/opt/homebrew/lib -lmsgpackc
else
    # Linux
    CFLAGS += -I/usr/include
    LDFLAGS = -lmsgpackc
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