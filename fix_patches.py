#!/usr/bin/env python3
"""Repair the SUSFS 4.19 patch hunks that don't apply to the msm-4.19 CLO tree.

Run from the kernel root after `patch -p1 < 50_add_susfs_in_kernel-4.19.patch`
and after `patch -p1 < 10_enable_susfs_for_ksu.patch` inside KernelSU/.
Idempotent: every fix checks for its marker first.
"""
import io
import os
import re
import sys

SUSFS_KSU_PATCH = os.path.join("KernelSU", "10_enable_susfs_for_ksu.patch")


def read(path):
    with io.open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(text)


def log(msg):
    print("[fix] " + msg)


def fix_sched_h():
    """include/linux/sched.h: tree has no ANDROID_KABI_RESERVE, add plain fields."""
    path = "include/linux/sched.h"
    text = read(path)
    if "susfs_task_state" in text:
        log("sched.h already has susfs fields")
        return
    anchor = "\trandomized_struct_fields_end"
    if anchor not in text:
        log("!! sched.h: anchor not found")
        sys.exit(1)
    block = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "\tu64 susfs_task_state;\n"
        "\tu64 susfs_last_fake_mnt_id;\n"
        "#endif\n"
    )
    text = text.replace(anchor, block + anchor, 1)
    write(path, text)
    log("sched.h: inserted susfs_task_state / susfs_last_fake_mnt_id")


def fix_task_mmu_h():
    """fs/proc/task_mmu.c: missing #include <linux/susfs_def.h>."""
    path = "fs/proc/task_mmu.c"
    text = read(path)
    if "susfs_def.h" in text:
        log("task_mmu.c already includes susfs_def.h")
        return
    block = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
        "#include <linux/susfs_def.h>\n"
        "#endif\n"
    )
    # insert after the first linux header include
    m = re.search(r"^#include <linux/[^\n]*>\n", text, re.M)
    if not m:
        log("!! task_mmu.c: no include anchor")
        sys.exit(1)
    idx = m.end()
    text = text[:idx] + block + text[idx:]
    write(path, text)
    log("task_mmu.c: inserted susfs_def.h include")


def fix_readdir_h():
    """fs/readdir.c: compat_fillonedir guard hunk failed."""
    path = "fs/readdir.c"
    text = read(path)
    fn = "static int compat_fillonedir(struct dir_context *ctx, const char *name,"
    if fn not in text:
        log("!! readdir.c: compat_fillonedir not found")
        sys.exit(1)
    start = text.index(fn)
    guard = (
        "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
        "\tif (likely(current->susfs_task_state & TASK_STRUCT_NON_ROOT_USER_APP_PROC) && "
        "susfs_sus_ino_for_filldir64(ino)) {\n"
        "\t\treturn 0;\n"
        "\t}\n"
        "#endif\n"
    )
    # place right after the opening brace of the function body
    brace = text.index("{", start)
    body = text[brace:]
    if "susfs_sus_ino_for_filldir64(ino)" in body[:600]:
        log("readdir.c: compat_fillonedir already guarded")
        return
    nl = text.index("\n", brace)
    text = text[: nl + 1] + guard + text[nl + 1 :]
    write(path, text)
    log("readdir.c: inserted compat_fillonedir sus_path guard")


def fix_ksu_kconfig():
    """KernelSU/kernel/Kconfig: SUSFS menu hunk failed, append it verbatim."""
    path = os.path.join("KernelSU", "kernel", "Kconfig")
    text = read(path)
    if "KSU_SUSFS" in text:
        log("KernelSU Kconfig already has KSU_SUSFS")
        return
    if not os.path.exists(SUSFS_KSU_PATCH):
        log("!! SUSFS KernelSU patch missing")
        sys.exit(1)
    patch = read(SUSFS_KSU_PATCH)
    lines = patch.split("\n")
    # locate the kernel/Kconfig diff section
    start = None
    for i, line in enumerate(lines):
        if line.startswith("diff --git a/kernel/Kconfig"):
            start = i
            break
    if start is None:
        log("!! kernel/Kconfig section not found in patch")
        sys.exit(1)
    added = []
    for line in lines[start + 1 :]:
        if line.startswith("diff --git"):
            break
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    if not added:
        log("!! no added lines extracted")
        sys.exit(1)
    text = text.rstrip("\n") + "\n\n" + "\n".join(added).strip("\n") + "\n"
    write(path, text)
    log("KernelSU Kconfig: appended SUSFS menu (%d lines)" % len(added))


NS_PATH = "fs/namespace.c"
NS_ANCHOR = "static bool is_mnt_ns_file"

NS_FUNCS = """
static int can_umount(const struct path *path, int flags)
{
\tstruct mount *mnt = real_mount(path->mnt);
\tif (flags & ~(MNT_FORCE | MNT_DETACH | MNT_EXPIRE | UMOUNT_NOFOLLOW))
\t\treturn -EINVAL;
\tif (!may_mount())
\t\treturn -EPERM;
\tif (path->dentry != path->mnt->mnt_root)
\t\treturn -EINVAL;
\tif (!check_mnt(mnt))
\t\treturn -EINVAL;
\tif (mnt->mnt.mnt_flags & MNT_LOCKED)
\t\treturn -EINVAL;
\tif (flags & MNT_FORCE && !capable(CAP_SYS_ADMIN))
\t\treturn -EPERM;
\treturn 0;
}

int path_umount(struct path *path, int flags)
{
\tstruct mount *mnt = real_mount(path->mnt);
\tint ret;
\tret = can_umount(path, flags);
\tif (!ret)
\t\tret = do_umount(mnt, flags);
\tdput(path->dentry);
\tmntput_no_expire(mnt);
\treturn ret;
}
"""


def fix_namespace_c():
    """SUSFS injects can_umount/path_umount from KernelSU's Makefile at parse
    time, which is too late for fs/namespace.o in a single build pass.
    Pre-inject them here so the first build already has the symbols."""
    if not os.path.isfile(NS_PATH):
        log("!! %s missing" % NS_PATH)
        sys.exit(1)
    text = read(NS_PATH)
    if "int path_umount(struct path *path, int flags)" in text:
        log("namespace.c: path_umount already present")
        return
    idx = text.find(NS_ANCHOR)
    if idx < 0:
        log("!! namespace.c: anchor %r not found" % NS_ANCHOR)
        sys.exit(1)
    text = text[:idx] + NS_FUNCS.lstrip("\n") + "\n" + text[idx:]
    write(NS_PATH, text)
    log("namespace.c: injected can_umount + path_umount before %r" % NS_ANCHOR)

def fix_cred_h():
    """4.19 has no get_cred_rcu(); KernelSU/SUSFS call it. Inject the 5.4 backport."""
    path = "include/linux/cred.h"
    if not os.path.isfile(path):
        log("!! %s missing" % path)
        sys.exit(1)
    text = read(path)
    if "get_cred_rcu" in text:
        log("cred.h: get_cred_rcu already present")
        return
    anchor = "static inline void put_cred"
    idx = text.find(anchor)
    if idx < 0:
        log("!! cred.h: anchor %r not found" % anchor)
        sys.exit(1)
    fn = (
        "static inline const struct cred *get_cred_rcu(const struct cred *cred)\n"
        "{\n"
        "\tstruct cred *nonconst_cred = (struct cred *) cred;\n"
        "\tif (!cred)\n"
        "\t\treturn NULL;\n"
        "\tif (!atomic_inc_not_zero(&nonconst_cred->usage))\n"
        "\t\treturn NULL;\n"
        "\tvalidate_creds(cred);\n"
        "\treturn cred;\n"
        "}\n\n"
    )
    text = text[:idx] + fn + text[idx:]
    write(path, text)
    log("cred.h: injected get_cred_rcu before %r" % anchor)

SELINUX_SUSFS_BLOCK = r"""#ifdef CONFIG_KSU_SUSFS
static inline void susfs_set_sid(const char *secctx_name, u32 *out_sid)
{
	int err;

	if (!secctx_name || !out_sid) {
		pr_err("secctx_name || out_sid is NULL\n");
		return;
	}

	err = security_secctx_to_secid(secctx_name, strlen(secctx_name),
					   out_sid);
	if (err) {
		pr_err("failed setting sid for '%s', err: %d\n", secctx_name, err);
		return;
	}
	pr_info("sid '%u' is set for secctx_name '%s'\n", *out_sid, secctx_name);
}

bool susfs_is_sid_equal(void *sec, u32 sid2) {
	struct task_security_struct *tsec = (struct task_security_struct *)sec;
	if (!tsec) {
		return false;
	}
	return tsec->sid == sid2;
}

u32 susfs_get_sid_from_name(const char *secctx_name)
{
	u32 out_sid = 0;
	int err;

	if (!secctx_name) {
		pr_err("secctx_name is NULL\n");
		return 0;
	}
	err = security_secctx_to_secid(secctx_name, strlen(secctx_name),
					   &out_sid);
	if (err) {
		pr_err("failed getting sid from secctx_name: %s, err: %d\n", secctx_name, err);
		return 0;
	}
	return out_sid;
}

u32 susfs_get_current_sid(void) {
	return current_sid();
}

void susfs_set_zygote_sid(void)
{
	susfs_set_sid(KERNEL_ZYGOTE_DOMAIN, &susfs_zygote_sid);
}

bool susfs_is_current_zygote_domain(void) {
	return unlikely(current_sid() == susfs_zygote_sid);
}

void susfs_set_ksu_sid(void)
{
	susfs_set_sid(KERNEL_SU_DOMAIN, &susfs_ksu_sid);
}

bool susfs_is_current_ksu_domain(void) {
	return unlikely(current_sid() == susfs_ksu_sid);
}

void susfs_set_init_sid(void)
{
	susfs_set_sid(KERNEL_INIT_DOMAIN, &susfs_init_sid);
}

bool susfs_is_current_init_domain(void) {
	return unlikely(current_sid() == susfs_init_sid);
}
#endif

"""


def fix_ksu_selinux_c():
    p = "KernelSU/kernel/selinux/selinux.c"
    if not os.path.exists(p):
        log("!! %s missing" % p)
        return
    t = open(p).read()
    if "susfs_is_current_ksu_domain" in t:
        log("[ok] selinux.c already has susfs sid helpers")
        return
    anchor = "#define DEVPTS_DOMAIN"
    if anchor in t:
        t = t.replace(anchor, SELINUX_SUSFS_BLOCK + anchor, 1)
        log("[fix] inserted susfs sid helpers before DEVPTS_DOMAIN")
    else:
        t = t + "\n" + SELINUX_SUSFS_BLOCK
        log("[fix] appended susfs sid helpers to selinux.c")
    open(p, "w").write(t)

def main():
    if not os.path.isdir("KernelSU"):
        log("!! KernelSU dir missing")
        sys.exit(1)
    fix_cred_h()
    if "--no-susfs" in sys.argv:
        log("ksu-only mode: skipped SUSFS repairs")
        log("all repairs done")
        return
    fix_sched_h()
    fix_task_mmu_h()
    fix_readdir_h()
    fix_ksu_kconfig()
    fix_ksu_selinux_c()
    fix_namespace_c()
    log("all repairs done")


if __name__ == "__main__":
    main()
