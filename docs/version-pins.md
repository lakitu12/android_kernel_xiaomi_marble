# 版本冻结

外部组件的版本都钉死，改 pin 时同步改这里和 `.github/workflows/build.yml` 的 `env:`。

## 固定版本

| 组件 | 版本 / 提交 | 位置 |
|---|---|---|
| 内核基底 | LineageOS sm8450 `eff4b404`（5.10.269） | 仓库根的树 |
| clang | `clang-r596125`（22.0.2） | CI `CLANG_URL` |
| SukiSU Ultra | `builtin` 分支 `b16e899a555e`（UAPI 6） | CI `KSU_PIN` |
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

builtin 有三处构建期问题，由 `.github/scripts/patch-ksu-builtin.py` 修，全部严格匹配
原文，匹配不上就报错：

1. `feature/mount_hide.c`：默认值 `true → false`，open 钩子改成恒 `return 0`。原实现
   对 `/proc/{mounts,mountinfo,mountstats}` 的 open 返回 `-ENOENT`，见下面「mount_hide」。
2. `manager/pkg_observer.c`：`susfs_parse_priority_app_strings()` 无条件调用，但声明在
   `CONFIG_KSU_SUSFS` 下，关掉 SUSFS 就编不过，加守卫。
3. `policy/allowlist.c`：`/* fall through */` 在 clang 22 + `CONFIG_WERROR=y` 下报
   `-Wimplicit-fallthrough`，改成 `fallthrough;`。

## SUSFS：烘进树

SUSFS 是 5.10 专用补丁（dash 那套 6.6 的不能复用），改 `fs/`、`mm/`、`kernel/`、
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

builtin 的 `feature/mount_hide.c` 对命中进程的 `/proc/{mounts,mountinfo,mountstats}`
open 直接返回 `-ENOENT`，而 `ksu_mount_hide_enabled` 默认 `true`、门控覆盖所有未授权
su 的 app。libincfs 的 `MountRegistry` 构造时 `std::ifstream("/proc/mounts")` 失败即
`PLOG(FATAL)`，于是 SystemUI 和 launcher 进崩溃循环。

main 线的同名功能是过滤 seq_file 内容，open 始终成功，没有这个问题。

已报上游：<https://github.com/SukiSU-Ultra/SukiSU-Ultra/issues/1035>。截至 2026-11-01，
最新 builtin head `464f9201` 仍是 `-ENOENT` + 默认开。上游修好后可以去掉
`patch-ksu-builtin.py` 的第 1 条，挂载隐藏改回 KSU 的实现；在那之前由 SUSFS 的
`sus_mount` 负责，它做 umount，不会让任何进程打不开 `/proc/mounts`。

## CI 断言

- `verify-tree.sh`：基底身份、kABI padding、`gki_defconfig` 未被改动，以及 SUSFS 的
  5 个点（`fs/susfs.c`、`fs/Makefile` 的 `susfs.o` 规则、`SUSFS_VERSION "v2.3.0"`、
  `fs/namei.c` 与 `security/selinux/hooks.c` 的钩子）。这些缺了不会编不过，只会静默
  少功能，所以必须硬断言
- `Setup SukiSU Ultra`：`drivers/kernelsu` 的 HEAD 等于 `KSU_PIN`，`Kconfig` 里有 10 个
  `config KSU_SUSFS*`（builtin 的指纹），`patch-ksu-builtin.py` 三处修补全部落地
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
