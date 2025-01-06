CC=gcc
CFLAGS=-Wall -O3 -I/opt/homebrew/include
LDFLAGS=-L/opt/homebrew/lib -lmsgpackc

all: gtfs_precache

gtfs_precache: gtfs_precache.c
	$(CC) $(CFLAGS) -o gtfs_precache gtfs_precache.c $(LDFLAGS)

clean:
	rm -f gtfs_precache 