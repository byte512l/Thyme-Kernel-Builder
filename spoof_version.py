#!/usr/bin/env python3
"""Make the built kernel report the stock MIUI kernel identity.

Replaces init/version.c's linux_banner with the exact string the stock
MIUI 14 (V14.0.6.0.TGACNXM) kernel prints, so /proc/version and uname agree.
"""
import os
import re
import sys

TEXT = (
    "Linux version 4.19.157-perf-g9d90dd04aa7c "
    "(builder@pangu-build-component-vendor-144082-xmbbk-vqbzf-3sb9s) "
    "(clang version 10.0.7 for Android NDK, GNU ld (binutils-2.27-bd24d23f) 2.27.0.20170315) "
    "#1 SMP PREEMPT Mon Sep 4 10:51:57 UTC 2023"
)
# C escape for the trailing newline: backslash + 'n' as literal source text.
C_LITERAL = TEXT + chr(92) + "n"

REPL = 'const char linux_banner[] = "%s";\n' % C_LITERAL


def main():
    p = "init/version.c"
    if not os.path.exists(p):
        print("!! init/version.c missing")
        sys.exit(1)
    if "\n" in C_LITERAL:
        print("!! internal error: C literal contains a real newline")
        sys.exit(1)
    s = open(p).read()
    # NOTE: re.sub treats backslashes in the replacement as escapes, so use a
    # callable to keep the C "\n" escape intact.
    s2, n = re.subn(r"const char linux_banner\[\]\s*=.*?;\n", lambda m: REPL, s, flags=re.S)
    if n == 0:
        print("!! linux_banner definition not found")
        sys.exit(1)
    open(p, "w").write(s2)
    print("[fix] linux_banner replaced (%d site)" % n)
    for line in open(p).read().splitlines():
        if "linux_banner" in line:
            print("    " + line[:200])


if __name__ == "__main__":
    main()
