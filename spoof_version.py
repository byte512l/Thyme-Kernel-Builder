#!/usr/bin/env python3
"""Make the built kernel report the stock MIUI kernel identity.

Rewrites init/version.c so that every kernel-side version surface
(/proc/version, uname(2) via init_uts_ns, /proc/sys/kernel/version,
linux_banner) prints exactly what the stock MIUI 14 kernel prints.
"""
import os
import re
import sys

RELEASE = "4.19.157-perf-g9d90dd04aa7c"
VERSION = "#1 SMP PREEMPT Mon Sep 4 10:51:57 UTC 2023"
BANNER = (
    "Linux version " + RELEASE + " "
    "(builder@pangu-build-component-vendor-144082-xmbbk-vqbzf-3sb9s) "
    "(clang version 10.0.7 for Android NDK, GNU ld (binutils-2.27-bd24d23f) 2.27.0.20170315) "
    + VERSION
)
NL = chr(92) + "n"          # literal backslash + n for the C source
BANNER_C = BANNER + NL


def cstr(s):
    """Escape a plain string for use inside a C string literal."""
    return s.replace(chr(92), chr(92) * 2).replace('"', chr(92) + '"')


def sub_once(src, pattern, repl, label):
    out, n = re.subn(pattern, lambda m: repl, src, flags=re.S)
    print("    %-22s %s" % (label + ":", "ok" if n else "NOT FOUND"))
    return out, n


def main():
    p = "init/version.c"
    if not os.path.exists(p):
        print("!! init/version.c missing")
        sys.exit(1)
    s = open(p).read()
    total = 0

    s, n = sub_once(
        s,
        r"const char linux_banner\[\]\s*=.*?;\n",
        'const char linux_banner[] = "%s";\n' % BANNER_C,
        "linux_banner",
    )
    total += n

    s, n = sub_once(
        s,
        r"const char linux_proc_banner\[\]\s*=.*?;\n",
        'const char linux_proc_banner[] = "%s";\n' % BANNER_C,
        "linux_proc_banner",
    )
    total += n

    s, n = sub_once(
        s,
        r"\.release\s*=\s*UTS_RELEASE,",
        '.release\t= "%s",' % RELEASE,
        "uts.release",
    )
    total += n

    s, n = sub_once(
        s,
        r"\.version\s*=\s*UTS_VERSION,",
        '.version\t= "%s",' % VERSION,
        "uts.version",
    )
    total += n

    if total < 4:
        print("!! only %d/4 sites patched" % total)
        sys.exit(1)

    open(p, "w").write(s)
    print("[fix] init/version.c rewritten (%d sites)" % total)


if __name__ == "__main__":
    main()
