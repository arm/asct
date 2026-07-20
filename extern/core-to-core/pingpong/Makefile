# Makefile for building the pysweep workload generator
override CFLAGS +=-O2 -Wall
override LDFLAGS += -pthread


#
# Build the workload generator as a C-callable library
#
LIBSRC = block.c cacheline.c chain.c clockns.c cpufreq.c crc32.c gettid.c idfill.c vatopa.c workset.c shuffle.c hwpf.c hwmt.c
LIBBUILD=./libbuild/src
LIBOBJ=$(patsubst %.c,$(LIBBUILD)/%.o,$(LIBSRC))
EXE=pingpong

.PHONY: all clean Makefile

all: $(EXE)

$(LIBOBJ): libbuild/%.o: %.c
	mkdir -p $(LIBBUILD)
	$(CC) $(CFLAGS) -c $< -o $@ -Isrc

$(EXE): tests/pingpong.c $(LIBOBJ)
	$(CC) $(CFLAGS) -o $@ $^ -Isrc $(LDFLAGS)


clean:
	rm -rf $(LIBBUILD) $(LIB) $(EXE) $(LIBOBJ)
