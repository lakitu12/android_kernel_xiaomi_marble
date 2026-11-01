#!/usr/bin/env python3
"""Apply the three build/runtime fixes SukiSU `builtin` @ b16e899a still needs.

`drivers/kernelsu` is injected by `kernel/setup.sh` at build time (the pin lives
in CI's `KSU_PIN`), so it cannot carry these fixes in the repo. Each one is a
strict, idempotent text edit: if upstream moves the code, this script fails
loudly instead of producing a subtly broken kernel.

1. policy/allowlist.c - `/* fall through */` is the pre-C23 spelling; clang 22
   under CONFIG_WERROR=y rejects the -Wimplicit-fallthrough warning it emits.
   Rewrite to `fallthrough;`.

2. manager/pkg_observer.c - `susfs_parse_priority_app_strings()` is called
   unconditionally but only declared under CONFIG_KSU_SUSFS, so a build with
   SUSFS disabled fails with an implicit declaration error. Guard the call.

3. feature/mount_hide.c - the crash loop of 2026-11-01. `builtin`'s mount_hide
   makes opens of /proc/{mounts,mountinfo,mountstats} fail with -ENOENT for
   every app-uid process that has something to umount:

       int ksu_mount_hide_file_open(struct file *file)
       {
           ...
           return -ENOENT;      /* <-- this */
       }

   libincfs' MountRegistry does `std::ifstream("/proc/mounts")` and
   PLOG(FATAL)-aborts when that fails, so every process that maps *uncompressed*
   APK entries (launcher3, systemui, wellbeing, ...) died with

       Abort message: 'Failed to open the /proc/mounts file: No such file or directory'

   Measured on marble 2026-11-01: 99 crashed processes in one logcat buffer
   (systemui 50 + launcher3 49), 57 of them with the incfs abort message, phone hot,
   SystemUI in a restart loop. Main line (v4.3.0) does not have this problem: its mount_hide
   filters the *contents* of those files instead of failing the open. That
   implementation is 653 lines and needs hooks this fork does not ship
   (ksu_patch_text/patch_memory), so we keep the feature plumbing but (a) default
   it off and (b) let the open succeed. SUSFS' own sus_mount already hides the
   module mounts for the apps that matter, and the manager then reports
   mount_hide as disabled instead of crashing the UI when someone toggles it.

Everything here is asserted after the edit; the script exits non-zero if a fix
did not land.
"""

import pathlib
import sys

MARK = "marble: never fail this open (libincfs aborts); SUSFS sus_mount does the hiding"


def _replace_once(path: pathlib.Path, old: str, new: str) -> bool:
    """Replace `old` with `new`; return True if the file changed."""
    src = path.read_text()
    if new in src:
        return False  # already patched
    if src.count(old) != 1:
        print(f"::error::{path}: expected exactly 1 occurrence of:\n{old!r}\nfound {src.count(old)}")
        raise SystemExit(1)
    path.write_text(src.replace(old, new))
    return True


def fix_fallthrough(tree: pathlib.Path) -> None:
    path = tree / "drivers" / "kernelsu" / "policy" / "allowlist.c"
    src = path.read_text()
    if "/* fall through */" not in src:
        print(f"{path}: no legacy fall-through comments left")
        return
    count = src.count("/* fall through */")
    path.write_text(src.replace("/* fall through */", "fallthrough;"))
    print(f"{path}: rewrote {count} legacy fall-through comment(s)")


def fix_pkg_observer(tree: pathlib.Path) -> None:
    path = tree / "drivers" / "kernelsu" / "manager" / "pkg_observer.c"
    old = (
        "    // Renew the getpriority uid bitmap filter\n"
        "    susfs_parse_priority_app_strings();\n"
    )
    new = (
        "    // Renew the getpriority uid bitmap filter\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "    susfs_parse_priority_app_strings();\n"
        "#endif\n"
    )
    if _replace_once(path, old, new):
        print(f"{path}: guarded susfs_parse_priority_app_strings() with CONFIG_KSU_SUSFS")


def fix_mount_hide(tree: pathlib.Path) -> None:
    path = tree / "drivers" / "kernelsu" / "feature" / "mount_hide.c"
    src = path.read_text()

    if "static bool ksu_mount_hide_enabled __read_mostly = true;" in src:
        src = src.replace(
            "static bool ksu_mount_hide_enabled __read_mostly = true;",
            "static bool ksu_mount_hide_enabled __read_mostly = false;",
        )
        path.write_text(src)
        print(f"{path}: mount_hide now defaults to off")
    elif "static bool ksu_mount_hide_enabled __read_mostly = false;" not in src:
        print(f"::error::{path}: mount_hide default flag not found - upstream changed")
        raise SystemExit(1)

    # Keep both helpers referenced (otherwise -Wunused-function under -Werror)
    # and make the hook a no-op: the checks still run, the open always succeeds.
    old = (
        "    if (!ksu_path_is_proc_mount_file(file))\n"
        "        return 0;\n"
        "\n"
        "    return -ENOENT;\n"
        "}\n"
    )
    new = (
        "    if (!ksu_path_is_proc_mount_file(file))\n"
        "        return 0;\n"
        "\n"
        f"    /* {MARK} */\n"
        "    return 0;\n"
        "}\n"
    )
    if _replace_once(path, old, new):
        print(f"{path}: ksu_mount_hide_file_open() can no longer fail the open")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch-ksu-builtin.py <kernel-tree>")
        return 2
    tree = pathlib.Path(sys.argv[1])
    if not (tree / "drivers" / "kernelsu" / "Kconfig").is_file():
        print(f"::error::{tree}: drivers/kernelsu missing - run the KSU setup step first")
        return 1

    fix_fallthrough(tree)
    fix_pkg_observer(tree)
    fix_mount_hide(tree)

    # ---------------------------------------------------------------- assertions
    mh = (tree / "drivers" / "kernelsu" / "feature" / "mount_hide.c").read_text()
    if "return -ENOENT;" in mh:
        print("::error::mount_hide still returns -ENOENT (would crash libincfs)")
        return 1
    if "static bool ksu_mount_hide_enabled __read_mostly = false;" not in mh:
        print("::error::mount_hide default is not off")
        return 1
    po = (tree / "drivers" / "kernelsu" / "manager" / "pkg_observer.c").read_text()
    if "#ifdef CONFIG_KSU_SUSFS" not in po:
        print("::error::pkg_observer still calls susfs_parse_priority_app_strings() unguarded")
        return 1
    al = (tree / "drivers" / "kernelsu" / "policy" / "allowlist.c").read_text()
    if "/* fall through */" in al:
        print("::error::legacy fall-through comment still present")
        return 1
    print("ok: builtin KSU fixes applied and asserted")
    return 0


if __name__ == "__main__":
    sys.exit(main())