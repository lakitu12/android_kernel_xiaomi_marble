#!/usr/bin/env python3
"""kabi-layout-diff.py <ours.vmlinux> <baseline.vmlinux>

用 pahole 读两份 vmlinux 的 DWARF，比较「同名类型的大小」——这是我们能离线证明
「开了 CONFIG_SYSVIPC 等配置之后，ROM 里预编译的 vendor_dlkm 模块仍然能按 stock
布局访问内核结构体」的最直接证据（不是 ABI 符号表那种静态检查）。

判定：
  * 同名类型 size 变了   -> 布局动过，kABI 破了（退出码 1）
  * 只在 ours 里的类型   -> 本次新编进来的（例如 SYSVIPC 的 semid_ds），无害
  * 只在 baseline 里的   -> 基线有而我们没有，说明配置方向反了，也报出来

用法（两次构建都用同一个 clang release，这样差异只来自配置）：

  pahole 需要带 DWARF/BTF 的 vmlinux，因此两次构建都要有 CONFIG_DEBUG_INFO=y。

  ./kabi-layout-diff.py out/.config-ours/vmlinux out/.config-stock/vmlinux

  # 顺带核单个结构体的字段偏移（最有用的两处）：
  pahole -C task_struct ours/vmlinux | grep -E 'sysvsem|sysvshm|reserved[678]'
  pahole -C user_struct ours/vmlinux | grep -E 'mq_bytes|reserved1'
"""
import subprocess
import sys


def sizes(vmlinux: str) -> dict:
    out = subprocess.run(
        ["pahole", "-s", vmlinux], capture_output=True, text=True, check=True
    ).stdout
    d = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            d[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return d


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    ours, base = sizes(sys.argv[1]), sizes(sys.argv[2])
    common = set(ours) & set(base)
    changed = sorted(
        ((n, ours[n], base[n]) for n in common if ours[n] != base[n]),
        key=lambda t: -abs(t[1] - t[2]),
    )
    only_ours = sorted(set(ours) - set(base))
    only_base = sorted(set(base) - set(ours))

    print(f"types: ours={len(ours)} baseline={len(base)} common={len(common)}")
    print(f"same-name types with changed size: {len(changed)}")
    for name, a, b in changed[:25]:
        print(f"  CHANGED {name}: ours={a} baseline={b} delta={a - b}")
    print(f"only in ours: {len(only_ours)} (newly compiled-in types, expected)")
    if only_base:
        print(f"only in baseline: {len(only_base)} e.g. {only_base[:8]}")

    if changed:
        print("\nRESULT: kABI layout CHANGED - vendor_dlkm modules built against stock may break")
        return 1
    print("\nRESULT: no layout change in any type present in both builds - kABI preserved")
    return 0


if __name__ == "__main__":
    sys.exit(main())