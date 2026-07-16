# Below makes use of /proc/cpuinfo to detect CPU features
CPU_FLAGS := $(shell \
  awk 'tolower($$0) ~ /^features[ \t]*:/ { \
         $$1=""; sub(/^[ \t:]+/, "", $$0); print $$0; exit \
       }' /proc/cpuinfo \
)

# Check for SVE support, set to true if exists and false if not
HAS_SVE := $(if $(findstring sve,$(CPU_FLAGS)),true,false)

# Add -DHAS_SVE if SVE is supported
ifeq ($(HAS_SVE),true)
  override CFLAGS += -DHAS_SVE -march=armv8.2-a+sve
endif