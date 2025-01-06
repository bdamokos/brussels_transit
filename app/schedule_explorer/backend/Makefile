# Detect OS
UNAME_S := $(shell uname -s)

# Common flags
CFLAGS = -Wall -O3

# OS-specific flags
ifeq ($(UNAME_S),Darwin)
    # macOS (Homebrew paths)
    CFLAGS += -I/opt/homebrew/include
    LDFLAGS = -L/opt/homebrew/lib -lmsgpack
else
    # Linux
    CFLAGS += -I/usr/include
    LDFLAGS = -lmsgpack
endif

all: gtfs_precache

gtfs_precache: gtfs_precache.c
	$(CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

clean:
	rm -f gtfs_precache

.PHONY: all clean 