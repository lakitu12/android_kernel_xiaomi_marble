#!/usr/bin/env python3
"""Make SukiSU `builtin`'s mount_hide resolve the CFI jump-table entry on 5.10.

`drivers/kernelsu` is injected at build time (pin lives in CI's `KSU_PIN`), so a
fix has to be applied here. One strict, idempotent text edit; if upstream moves
the code, this script fails loudly instead of shipping a silently dead filter.

What is wrong as of upstream 1cfa5734 (the mount_hide crash fix, SukiSU#1035):

    ret = ksu_lookup_kernel_symbols(names, addrs, ARRAY_SIZE(names));

`ksu_lookup_kernel_symbols()` matches kallsyms entries by name, so it returns
the function itself (`show_vfsmnt`). With CONFIG_CFI_CLANG on 5.10 a function
whose address is taken has a `.cfi_jt` jump-table alias, and the pointer stored
in `struct proc_mounts.show` is the alias, not the function:

    p->show          = ffffffdbf482f5e8   show_vfsmnt.<hash>.cfi_jt
    expected         = ffffffdbf445f54c   show_vfsmnt

so `p->show != expected` and the filter is never installed. The open succeeds
(that part of the fix works, no more libincfs aborts), but nothing is hidden and
the only trace is `mount_hide: proc_mounts show mismatch, not filtering`.

`ksu_resolve_symbol_for_functable_hook()` exists for exactly this case: it
prefers the `.cfi_jt` variant on pre-KCFI kernels and the plain symbol on 6.1+
(where KCFI has no jump table). Resolve each name with that instead.
"""

import pathlib
import sys

OLD = """    unsigned long addrs[ARRAY_SIZE(names)] = {};
    int ret;

    ret = ksu_lookup_kernel_symbols(names, addrs, ARRAY_SIZE(names));
    if (ret < 0) {
        pr_err("mount_hide: symbol lookup failed: %d\\n", ret);
        return ret;
    }
"""

NEW = """    unsigned long addrs[ARRAY_SIZE(names)] = {};
    unsigned int i;

    /*
     * marble: CONFIG_CFI_CLANG (5.10) stores the .cfi_jt jump-table entry in
     * proc_mounts.show, not the function itself, so a plain kallsyms match
     * against show_vfsmnt() never succeeds and the filter stays off. This
     * helper prefers .cfi_jt on pre-KCFI kernels and the plain symbol on 6.1+.
     */
    for (i = 0; i < ARRAY_SIZE(names); i++)
        addrs[i] = (unsigned long)ksu_resolve_symbol_for_functable_hook(names[i]);
"""

MARK = "ksu_resolve_symbol_for_functable_hook(names[i])"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch-ksu-mount-hide.py <kernel-tree>")
        return 2
    tree = pathlib.Path(sys.argv[1])
    path = tree / "drivers" / "kernelsu" / "feature" / "mount_hide.c"
    if not path.is_file():
        print(f"::error::{path} missing - run the KSU setup step first")
        return 1

    src = path.read_text()
    if MARK in src:
        print(f"{path}: already resolves .cfi_jt variants")
    else:
        if src.count(OLD) != 1:
            print(f"::error::{path}: expected exactly 1 occurrence of the batch lookup, found {src.count(OLD)}")
            print("::error::upstream moved ksu_mount_hide_resolve() - re-check the CFI question before patching")
            return 1
        if "void *ksu_resolve_symbol_for_functable_hook" not in (
            tree / "drivers" / "kernelsu" / "infra" / "symbol_resolver.c"
        ).read_text():
            print("::error::ksu_resolve_symbol_for_functable_hook() is gone from symbol_resolver.c")
            return 1
        path.write_text(src.replace(OLD, NEW))
        print(f"{path}: mount_hide resolves show fns via the functable hook (CFI .cfi_jt)")

    # The filter must still be installed from file_permission and must never
    # fail the open: that is the SukiSU#1035 fix we are pinning to.
    mh = path.read_text()
    for needle in ("ksu_mount_hide_file_permission", "ksu_should_hide_mount_for_current"):
        if needle not in mh:
            print(f"::error::mount_hide.c lost {needle}")
            return 1
    if "return -ENOENT;" in mh:
        print("::error::mount_hide is back to failing the open (libincfs abort, SukiSU#1035)")
        return 1
    print("ok: mount_hide patches applied and asserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())