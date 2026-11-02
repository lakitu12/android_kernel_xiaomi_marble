# 版本冻结

外部组件的版本都钉死，改 pin 时同步改这里和 `.github/workflows/build.yml` 的 `env:`。

## 固定版本

| 组件 | 版本 / 提交 | 位置 |
|---|---|---|
| 内核基底 | LineageOS sm8450 `eff4b404`（5.10.269） | 仓库根的树 |
| clang | `clang-r596125`（22.0.2） | CI `CLANG_URL` |
| SukiSU Ultra | `builtin` 分支 `1cfa573405909`（UAPI 6） | CI `KSU_PIN` |
| SUSFS | `susfs4ksu` `gki-android12-5.10` @ `3c8f72ec47ee`（2.3.0） | 树内提交 `5332250` |
| KernelPatch | `bmax121/KernelPatch` @ `d4c88d667268` | CI `KP_PIN` |
| kpimg | `ShirkNeko/SukiSU_patch` @ `eec45788c9a1`，sha256 `14fc6564…f5ca`（294384 B） | CI `KPIMG_PIN` / `KPIMG_SHA256` |
| AnyKernel3 | `Numbersf/AnyKernel3` @ `0fc75698` | CI `AK3_PIN` |
| DroidSpaces kABI | `GKI/below-kernel-6.12` 的 `001` / `002` | 树内提交 `4da795e` |

## clang 必须与 ROM 内核同一个 release

CFI/BTI 的代码生成与校验只在同一个 clang release 内兼容。用 r547379 (20.0.0) 编的
LTO+CFI 内核，刷入后第一次调用 vendor 模块（`qcom_tsens`）就 panic：

```
Bad mode in Synchronous Abort handler detected ... code 0x36000002 -- BTI
Kernel panic - not syncing: bad mode
```

ROM 换工具链时同步换 `CLANG_URL`：对照 stock 内核 `uname -v` 或
`strings Image | grep 'Linux version'` 里的 `-g<hash>`，取同一个 `clang-rXXXXXX`。

CI 第一步校验 `clang version 22.0.2`，不匹配直接失败。

## SukiSU：用 builtin 分支

只有 `builtin` 分支带 `CONFIG_KSU_SUSFS*`（10 项）和 `ksu_susfs_*` 超调用，main 线一项
都没有，所以要用 SUSFS 只能走这条线。

UAPI 必须和管理器一致：管理器 v4.3.0 是 UAPI 6。UAPI 5 的内核会让管理器首页报「需要
更新内核」（`requiresNewKernel = managerUAPIVersion > kernelUAPIVersion`），且 ksud 的
`ensure_uapi_version_matched` 让所有写操作失败。

`1cfa5734` 是 2026-11-01 报的 mount_hide 崩溃（SukiSU#1035）的上游修法，也是当前
`builtin` 的 head。它把拒绝 open 的实现换成按记录过滤，崩溃因此消失；但它的符号解析
在这棵树上装不上过滤器，所以仍有一处构建期补丁
（`.github/scripts/patch-ksu-mount-hide.py`，见下面「mount_hide」）。

## SUSFS：烘进树

SUSFS 是 5.10 专用补丁，6.6 的补丁不能复用；它改 `fs/`、`mm/`、`kernel/`、
`security/selinux/` 共 27 个文件，属于树本身的形状，所以整份烘进树，提交 `5332250`。

重放方式：

```bash
git clone -b gki-android12-5.10 https://gitlab.com/simonpunk/susfs4ksu.git
cp ../susfs4ksu/kernel_patches/fs/* fs/
cp ../susfs4ksu/kernel_patches/include/linux/* include/linux/
patch -p1 < ../susfs4ksu/kernel_patches/50_add_susfs_in_gki-android12-5.10.patch
```

`kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch` 不打，builtin 的 KSU 自带这半边。

树里有两处本地适配：`-Wunused-function` 在 `CONFIG_WERROR=y` 下会变错误。原因写在
提交正文里。

配置是 10 个 SUSFS 功能全开，加 `KSU` 和 `KPM`。

## KernelPatch：KPM 必须预补丁

`CONFIG_KPM=y` 只编 `sukisu_kpm_bridge`，真正的 KPM 超调用在 KernelPatch 里。Image
没有预补丁时，`ksud kpm list` 返回 `os error 95`，管理器把 KPM 标成不支持。

ksu 变体在版本门禁之后、打包 AnyKernel3 之前多一步：

1. 按 `KP_PIN` 取 KernelPatch，把 `kernel/include/preset.h` 拷进 `tools/`（上游的 CMake
   不自己做这件事），编出 `kptools`；
2. 从 `ShirkNeko/SukiSU_patch` 取 `kpimg`，校验 sha256；
3. `kptools -p -i Image -k kpimg -S <superkey> -o Image`；
4. 断言 `kptools -l` 输出 `patched=true` / `version=0xe00`，且 Image 里有
   `KernelPatch Version:`。

superkey 每次构建随机生成、不入库。KPM 走 SukiSU 的 supercall，管理器和 ksud 都不需要
它，它只保护 KernelPatch 自己的 `kpatch` 入口。代价是同一提交两次构建的 Image 不会
逐字节相同。

## mount_hide

`b16e899a` 那版对命中进程的 `/proc/{mounts,mountinfo,mountstats}` open 直接返回
`-ENOENT`，而 `ksu_mount_hide_enabled` 默认 `true`、门控覆盖所有未授权 su 的 app。
libincfs 的 `MountRegistry` 构造时 `std::ifstream("/proc/mounts")` 失败即
`PLOG(FATAL)`，于是 SystemUI 和 launcher 进崩溃循环。2026-11-01 报给上游：
<https://github.com/SukiSU-Ultra/SukiSU-Ultra/issues/1035>。

`1cfa5734` 换成 main 线的做法：从 `security_file_permission()` 拿到每个文件的
`proc_mounts`，把 `show` 指针换成自己的过滤器，按记录删掉模块挂载。open 始终成功，
`/proc/mounts` 对 app 来说只是「没有那几行」。符号名走 kallsyms，前提是
`CONFIG_KALLSYMS=y`（GKI 本来就有；`KALLSYMS_ALL` 只决定要不要带数据符号，函数符号
无论如何都在）。功能默认关，管理器里可以开；开关打开时解析失败只会 `pr_err`，不会崩。

上游用 `ksu_lookup_kernel_symbols()` 取 `show_vfsmnt()` 等三个函数的地址，拿它与
`proc_mounts.show` 比对。这在本树（5.10 + `CONFIG_CFI_CLANG`）不成立：函数地址被取用时
存进结构体的是 CFI 跳表项 `.cfi_jt`，不是函数本体。

```
p->show   ffffffdbf482f5e8   show_vfsmnt.<hash>.cfi_jt
expected  ffffffdbf445f54c   show_vfsmnt
```

于是 `p->show != expected`，过滤器永远装不上：open 正常（崩溃确实修了），但一个挂载都
不隐藏，dmesg 只有一行 `mount_hide: proc_mounts show mismatch, not filtering`。
`ksu_resolve_symbol_for_functable_hook()` 本来就是为这种情况写的（pre-KCFI 优先
`.cfi_jt`，6.1+ 取本体），`patch-ksu-mount-hide.py` 把解析换成它，实测装了过滤器之后
app / isolated 进程读到 151 行、root 152 行，测试挂载对前者不可见。

和 SUSFS 的 `sus_mount` 不能同时生效：开着 `hide-sus-mnts-for-non-su-procs` 时，
`mounts_open()` 装的 `show` 是 `susfs_show_vfsmnt()`，这里同样对不上，也只打一行
mismatch，KSU 的过滤器不装。实测两种状态：SUSFS 隐藏关掉时 app 读 151 行、测试挂载
不可见；打开后 app 读 152 行、那一行又出现了。要用哪个由管理员决定，别指望两个都开。

CI 钉住三件事：解析走 functable hook、`ksu_mount_hide_file_permission` 还在、不能再出现
`return -ENOENT;`。

## CI 断言

- `verify-tree.sh`：基底身份、kABI padding、`gki_defconfig` 未被改动，以及 SUSFS 的
  5 个点（`fs/susfs.c`、`fs/Makefile` 的 `susfs.o` 规则、`SUSFS_VERSION "v2.3.0"`、
  `fs/namei.c` 与 `security/selinux/hooks.c` 的钩子）。这些缺了不会编不过，只会静默
  少功能，所以必须硬断言
- `Setup SukiSU Ultra`：`drivers/kernelsu` 的 HEAD 等于 `KSU_PIN`，`Kconfig` 里有 10 个
  `config KSU_SUSFS*`（builtin 的指纹），`patch-ksu-mount-hide.py` 的断言全过（functable
  解析、`file_permission` 过滤器在位、没有 `return -ENOENT;`）
- 配置门禁：ksu 变体 `olddefconfig` 后有 10 个 `CONFIG_KSU_SUSFS*=y`
- `KernelPatch prepatch`：`KP_PIN` 匹配、kpimg sha256 匹配、`kptools -l` 输出
  `patched=true` + `version=0xe00`、Image 里有 `KernelPatch Version:`
- `Prepare AnyKernel3`：`AK3_PIN` 匹配，`tools/magiskboot` 788840 B、
  `tools/magiskpolicy` 356584 B（这两个工具版本漂移过，会让设备 panic）
- 版本门禁：Image 里有 `5.10.269` 和 `droidspaces-lakitu`，ikconfig 里有
  `LTO_CLANG_THIN` / `CFI_CLANG` / `SYSVIPC` / `POSIX_MQUEUE`；ksu 变体再加
  `KSU` / `KPM` / 10 个 SUSFS，bypass 变体反过来断言这些都不在

## kABI 证据

开 `SYSVIPC` / `POSIX_MQUEUE` 不能让 ROM 里预编译的 vendor_dlkm 模块错位，这是
DroidSpaces 那对 kABI 补丁的唯一目的。实测方法：同一棵树编两次，只差配置。

```bash
# A) gen-config.sh 产出的 out/.config
# B) stock 配置：gki_defconfig + vendor/waipio_GKI → xiaomi_GKI → marble_GKI → debugfs
#    （唯一改动是把 LTO 换成 THIN，否则 15GB 的机器在 FULL LTO 链接阶段被 OOM；
#     LTO 只影响代码生成，不影响结构体布局）
./.github/scripts/kabi-layout-diff.py A/vmlinux B/vmlinux
```

结果：

| 检查 | 结果 |
|---|---|
| 同名类型 size 变化 | 0 / 9908 |
| 只在我们的镜像里出现的类型 | 106 个，全部由 SYSVIPC / POSIX_MQUEUE 带入（`compat_ipc_perm`、`mq_attr`、`semid64_ds` 等） |
| `task_struct` | `sysvsem @3592 (8B)`、`sysvshm @3600 (16B)`，盖住 stock 的 `android_kabi_reserved6/7/8`，其后字段偏移一致 |
| `user_struct` | `mq_bytes @120 (8B)`，盖住 `android_kabi_reserved1` |

全内核同名类型尺寸都没有变化，stock 编的模块按原偏移访问是安全的。换基底或加配置时
重跑这个脚本。

## 验证记录

| 日期 | 内容 | 结果 |
|---|---|---|
| 2026-10-16 | r596125 + `dfae923`（UAPI 5），AK3 刷入 | 正常开机，KernelSU 激活 |
| 2026-11-01 | 完整树重构 + `e67b14e6`（v4.3.0，UAPI 6），fastboot 刷 `boot_a` + `boot_b` | 40s 开机，`su` → `uid=0`，管理器红条消失 |
| 2026-11-01 | 直接刷 CI `41269038858` 的 ksu 产物 | `uname -v` 与 CI 构建时刻一致，`/proc/config.gz` 与产物 ikconfig 0 diff |
| 2026-11-01 | SUSFS + KernelPatch 全套上机 | 解锁后 0 次 SIGABRT，`ksud kpm list` rc=0，dmesg 有 `KP KernelPatch Version: e00` 和 `susfs is initialized! version: v2.3.0` |
| 2026-11-01 | CI `41297579532` 产物刷 `boot_a` | 45s 开机，ikconfig 7768 行 0 diff，`kptools -l` 为 `patched=true` |
| 2026-11-01 | DroidSpaces v7.1.0 `check` + Alpine 3.22.1 容器 | `[MUST HAVE]` / `[RECOMMENDED]` 全绿，容器 start/run/stop 正常 |
