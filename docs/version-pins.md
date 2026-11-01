# 版本冻结（clang / SukiSU / AnyKernel3 / DroidSpaces）

> 这份文档是「为什么钉这个」的唯一出处。改 pin 必须同时改这里、CI 里的 `env:` 和
> 本文末尾的验证记录。

## 1. 现状（2026-11-01）

| 组件 | 钉住的对象 | 位置 | 说明 |
|---|---|---|---|
| clang | `clang-r596125`（22.0.2，AOSP `main-kernel`） | CI `CLANG_URL` | **必须**与 ROM stock 内核同一个 release，见 §2 |
| SukiSU Ultra | **`builtin` 线** `b16e899a555e`（UAPI 6，2026-10-30） | CI `KSU_PIN` | 构建期注入，不入库。**只有这条线有 `CONFIG_KSU_SUSFS*` 和 `ksu_susfs_*` 超调用**；必须和管理器 APK 同一 UAPI 线（v4.3.0 = UAPI 6），见 §3 |
| SUSFS | `susfs4ksu` 分支 `gki-android12-5.10` @ `3c8f72ec47ee`（SUSFS 2.3.0） | **树内提交** `5332250` | 整份 patch 已烘进树（27 改 + 3 新），构建时不再打补丁；5.10 专用，6.6 的 patch 不适用，见 §3.2 |
| KernelPatch | `bmax121/KernelPatch` @ `d4c88d667268`（2026-10-29） | CI `KP_PIN` | KPM 的后端：kptools 把 kpimg 预补丁进 Image，否则 `ksud kpm list` 是 `os error 95`，见 §3.3 |
| kpimg | `ShirkNeko/SukiSU_patch` @ `eec45788c9a1`，sha256 `14fc6564…f5ca`（294384 B） | CI `KPIMG_PIN` / `KPIMG_SHA256` | kptools 嵌进 Image 的预置代码；每次构建随机生成 32 字符 superkey（只给 KP 自己的 kpatch 入口用） |
| AnyKernel3 | `Numbersf/AnyKernel3` `0fc75698` | CI `AK3_PIN` | SukiSU 管理器能认的大写变量版式；另加 magiskboot/magiskpolicy 体积门禁 |
| DroidSpaces kABI 补丁 | `001.GKI-below-6.12-fix_sysvipc_kabi_6_7_8` + `002.5.10_or_lower_…posix_mqueue` | **树内提交** `4da795e` | 已经烘进树，不再按 pin 拉取；来源 ravindu644/Droidspaces-OSS `GKI/below-kernel-6.12/` |
| 内核基底 | LineageOS sm8450 `eff4b404`（5.10.269） | 树本身 | 见 [upstream-base.md](upstream-base.md) |

## 2. clang 为什么必须钉 r596125（这条是实机用命换的）

CFI/BTI 的代码生成与校验 ABI **只在同一个 clang release 内兼容**。2026-10-16 的
事故：LTO+CFI 内核用 r547379 (20.0.0) 编，刷入后 0.3 秒在
`__cfi_check` 第一次调用 vendor 模块 `qcom_tsens` 时炸：

```
Bad mode in Synchronous Abort handler detected ... code 0x36000002 -- BTI
Kernel panic - not syncing: bad mode
```

取证：`~/code/probes/marble-lineage24-cfi-20261016/`（minidump 全量 + 三次崩溃全文）。
换回与 stock 逐字一致的 r596125 (22.0.2) 后 CI `38835130001` 全绿、实机 AK3 刷入正常。
所以 CI 第一步就要 `clang --version | grep 'clang version 22.0.2'`，不匹配立刻死。

ROM 哪天换内核工具链，这里必须跟着换：对照 `uname -v`/`strings Image | grep 'Linux version'`
里的 `-g<hash>` 找到 stock 内核对应 revision，再取同一个 `clang-rXXXXXX`。

## 3. KSU 为什么现在走 builtin、SUSFS 为什么烘进树、KPM 为什么必须预补丁 KernelPatch

### 3.1 从 main 线换到 `builtin`（2026-11-01 晚）

`lineage-24.0` 这条线最初按 **main 线 stable** 建，原因是 2026-10-15 的 `builtin`
HEAD 处于半合并状态（`ksu_manager_cmd`、重复的 `KSU_IOCTL_KPM`、`TRACK_THRONE` 都编
不过），而 main 线一编就过。当时的选择是「先有能开机的 root」，SUSFS 留空。表现就是
main 线的 `kernel/Kconfig` 里 `config KSU_SUSFS` **0 项**——SUSFS 在这条线上根本不存在。

UAPI 这条线依旧要盯死：设备上的管理器是 v4.3.0 (41100-**6**)，UAPI 5 的内核会触发
`requiresNewKernel = managerUAPIVersion > kernelUAPIVersion`（`HomeViewModel.kt:102`），
首页红条「需要更新内核」，ksud 的 `ensure_uapi_version_matched` 让所有写操作直接失败
（「管理器 GUI 什么都点不动」）。现在的 pin 是 `builtin@b16e899a`（UAPI 6），与 v4.3.0
管理器的 UAPI 线一致。

换线的两个前提都在 2026-11-01 当晚实测过：`b16e899a`（2026-10-30
"fix 0b666cad breaks clang GKI builds"）在 clang 22 下能编过；`susfs4ksu`
`gki-android12-5.10` 的 `50_*.patch` 能在 LineageOS 树上**零 fuzz** 应用。但 builtin
还带着三个问题，全部由 `.github/scripts/patch-ksu-builtin.py` 在构建期修掉（见 §3.4）。

### 3.2 SUSFS 为什么是「树内提交」而不是构建期打补丁

SUSFS 是 5.10 专用的内核补丁，dash 那套 6.6 的 patch 不能复用；它改的是 `fs/`、`mm/`、
`kernel/`、`security/selinux/` 这 27 个文件，属于「树本身的形状」，所以按 DroidSpaces
kABI 补丁的规格处理：**烘进树、记 pin、由 verify-tree.sh 断言**。这样仍然满足仓库的
前提「CI 只编 check in 的东西」——构建期只剩两件不属于本仓库的注入（KSU 与
KernelPatch），而不是三件。

来历写在提交 `5332250` 里，复现方式：

```bash
git clone -b gki-android12-5.10 https://gitlab.com/simonpunk/susfs4ksu.git
cd <tree>
cp ../susfs4ksu/kernel_patches/fs/* fs/
cp ../susfs4ksu/kernel_patches/include/linux/* include/linux/
patch -p1 < ../susfs4ksu/kernel_patches/50_add_susfs_in_gki-android12-5.10.patch  # 27 files, 0 fuzz
```

`kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch` **不打**：builtin 的 KSU 自己
就带这半边（10 个 `CONFIG_KSU_SUSFS*` 开关 + `ksu_susfs_*` 超调用）。树里还有两处本地
适配（`-Wunused-function` 在 `CONFIG_WERROR=y` 下会变错），原因写在提交正文里。

配置矩阵：**10 个 SUSFS 功能全开** + `KSU` + `KPM`。2026-11-01 排障时曾怀疑
`SUS_PATH`（当时关掉它就不崩），最后确认那是误判——真正的根因是 KSU 的 `mount_hide`
（§3.4），把 `SUS_PATH` 打开后一样稳。

### 3.3 KPM 不是「开个 CONFIG 就有」：必须预补丁 KernelPatch

`CONFIG_KPM=y` 只编 `sukisu_kpm_bridge`，真正的 KPM 超调用落在 KernelPatch（KP）上。
Image 没有预补丁时，`ksud kpm list` 返回 `os error 95 / Operation not supported`，
管理器拓展页把 KPM 标成不支持（2026-10-31 的实机状态）。

所以 ksu 变体在版本门禁之后、打 AnyKernel3 之前多一步：

1. 按 `KP_PIN` 取 `bmax121/KernelPatch`，把 `kernel/include/preset.h` 拷进 `tools/`
   （upstream 的 CMake 不自己干这事），编出 `kptools`；
2. 从 `ShirkNeko/SukiSU_patch` 取 `kpimg`（sha256 钉死，294384 B）；
3. `kptools -p -i Image -k kpimg -S <随机 32 字符 superkey> -o Image`；
4. 断言 `kptools -l` 输出 `patched=true` / `version=0xe00`，且 Image 里出现
   `KernelPatch Version:`。

superkey 每次构建随机生成、不入库：KPM 走的是 SukiSU 的 supercall，管理器和 ksud 都
不需要它；它只保护 KP 自己的 `kpatch` 用户态入口。代价是同一提交两次构建的 Image 不会
逐字节相同（差的就是这 32 字节和构建时间戳）。

### 3.4 mount_hide：一次把手机烤热的崩溃循环，和它的根因

2026-11-01，SUSFS + KP 一起上机后 SystemUI/launcher 进崩溃循环：一个 90 秒的
logcat 缓冲里有 **99 个崩溃进程**（systemui 50 + launcher3 49），其中 57 条是
incfs 的 abort message；手机发烫（电池 37°C+）、屏幕闪烁。排障过程（每一步都是
实机 A/B）：

**决定性的对照是「同一份源码只改一个默认值」**（都是解锁后 12 秒计数）：

| 变体 | fatal / incfs abort | 说明 |
|---|---|---|
| builtin KSU、**无 SUSFS**、`mount_hide` 默认 `true` | **69 / 77** | 崩溃与 SUSFS 无关 |
| 同上，只把默认值改成 `false`，别的字节不动 | **0 / 0** | 根因坐实 |
| SUSFS 全开 + KP、`mount_hide` 默认 `true` | 49 / 57 | 同一机制，另一组配置 |
| SUSFS 全开 + KP、`mount_hide` 关 / open 恒成功 | 0 / 0 | 修法验证 |
| main 线 KSU + KP，`mount_hide` ENABLED | 0 / 0 | 那份实现是过滤内容，不拒绝 open |

**为什么一开始看起来像 SUSFS 的问题**：最早复现是在 SUSFS + KP 的镜像上，随后「把
`SUS_MOUNT` / `SUS_PATH` 某个子项关掉」的几个变体都测出 0，于是误判成「某个 SUSFS 子项
把 app 塞进了 umount 名单」。这个解释站不住——builtin 单独跑（SUSFS 一个字节都没有）
照样 69/77 崩。真实原因是**触发时机**：`mount_hide` 的门控是
`is_appuid(uid) && ksu_uid_should_umount(uid)`，而 `default_non_root_profile.umount_modules`
在 `policy/allowlist.c` 里初始化就是 `true`，所以**任何未授权 su 的 app 都命中**；是否
当场炸，取决于那个窗口里有没有 app 去打开 `/proc/mounts`（libincfs 加载未压缩 APK 条目
时就会）。那些 0 结果只是时间窗内的假阴性，不能当成因果。

崩溃日志里的真信号不是「层」而是这一行：

```
Abort message: 'Failed to open the /proc/mounts file: No such file or directory'
Fatal signal 6 (SIGABRT) ... com.android.launcher3 / com.android.systemui
```

libincfs 的 `MountRegistry` 构造时 `std::ifstream("/proc/mounts")`，失败即
`PLOG(FATAL)`；而 builtin 的 `feature/mount_hide.c` 对「该 umount 的 app 进程」把
`/proc/{mounts,mountinfo,mountstats}` 的 open 直接返回 `-ENOENT`——于是**任何映射了未
压缩 APK 条目的进程**都会 abort。main 线没有这个问题：它的同名功能是 653 行、过滤文件
内容，而 builtin 这版（整文件 165 行）的核心钩子只有几行，就是直接 `return -ENOENT`。

修法（`.github/scripts/patch-ksu-builtin.py`，三处都是严格匹配 + 断言）：

1. `feature/mount_hide.c`：默认值 `true → false`，并把 open 钩子改成恒成功（`return 0`），
   保留 `ksu_should_hide_mount_for_current()` / `ksu_path_is_proc_mount_file()` 的调用，
   免得 `-Wunused-function` 又变错。真正的挂载隐藏交给 SUSFS 的 `sus_mount`——它本来
   就覆盖同样的 app，而且不会让任何进程的 `/proc/mounts` 打不开。
2. `manager/pkg_observer.c`：`susfs_parse_priority_app_strings()` 是无条件调用的，但
   声明只在 `CONFIG_KSU_SUSFS` 下，关掉 SUSFS 就编不过，加守卫。
3. `policy/allowlist.c`：`/* fall through */` 是 C23 之前的老写法，clang 22 +
   `CONFIG_WERROR=y` 会拒（`-Wimplicit-fallthrough`），改成 `fallthrough;`。

修完的实测（2026-11-01 17:56 构建、17:58 刷入）：解锁后 **0 次 SIGABRT**、launcher 拿回
焦点、`ksud kpm list` rc=0（不再是 os error 95）、内核日志同时有
`KP KernelPatch Version: e00` 与 `susfs is initialized! version: v2.3.0`、管理器首页
无红条且 SUSFS/KPM 两张卡都在。

## 4. CI 里的冻结断言

- `Verify the in-tree marble delta`：`verify-tree.sh` 除了基底/kABI/配置，还要断言
  SUSFS 的 5 个点（`fs/susfs.c`、`fs/Makefile` 的 `susfs.o` 规则、
  `SUSFS_VERSION "v2.3.0"`、`fs/namei.c` 与 `security/selinux/hooks.c` 里的钩子）——
  缺了不会编不过，只会静默少功能，所以必须硬断言；
- `Setup SukiSU Ultra (builtin)`：`drivers/kernelsu` 的 `HEAD` 必须等于 `KSU_PIN`、
  `Kconfig` 里必须有 **10** 个 `config KSU_SUSFS*`（builtin 的指纹），然后
  `patch-ksu-builtin.py` 必须让三处修补全部落地（否则立刻失败）；
- 配置门禁：ksu 变体在 `olddefconfig` 之后必须有 **10** 个 `CONFIG_KSU_SUSFS*=y`；
- `KernelPatch prepatch`：`KP_PIN` 必须匹配、`kpimg` sha256 必须等于 `KPIMG_SHA256`、
  `kptools -l` 必须输出 `patched=true` + `version=0xe00`、Image 里必须有
  `KernelPatch Version:`；
- `Prepare AnyKernel3`：`AK3_PIN` 必须匹配，`tools/magiskboot` = 788840 B、
  `tools/magiskpolicy` = 356584 B（工具漂了一度把设备刷成 panic）；ksu 产物的 zip 里
  必须同时能看到 `susfs is initialized! version: v2.3.0` 与 `KernelPatch Version:`；
- 版本门禁：Image 里必须有 `5.10.269` + `droidspaces-lakitu`，ikconfig 里必须有
  `LTO_CLANG_THIN` / `CFI_CLANG` / `SYSVIPC` / `POSIX_MQUEUE`，ksu 变体再加
  `CONFIG_KSU` / `CONFIG_KPM` / 10 个 SUSFS，bypass 变体反过来断言三者都不在。

## 5. 已知可开机的组合

| 基底 | 工具链 | KSU | 结果 |
|---|---|---|---|
| LineageOS `eff4b404` (5.10.269) | r596125 (22.0.2) | `dfae923` (v4.2.1-40994, **UAPI 5**) | ✅ 2026-10-16 实测：CI `38835130001` 双变体绿；AK3 刷入 KSU-KPM 变体正常开机、KernelSU 激活、minidump 无新增崩溃。2026-11-01 完整树重构后 CI `41217178370` 双变体绿 + 实机 fastboot 刷入：40s 开机、`su`→uid=0、`/proc/config.gz` 与 CI ikconfig 零差异、minidump 无新增。⚠️ 这一条**只配 v4.2.1 管理器**；v4.3.0 管理器会红条且写操作被 UAPI 校验挡住 |
| 同上（完整树重构） | 同上 | `builtin@b16e899a` (**UAPI 6**, + SUSFS 2.3.0 + KernelPatch `d4c88d6`) | ✅ 2026-11-01 17:58 实测：本地编 `out-full`（10 个 SUSFS 全开）→ kptools 预补丁 → magiskboot 重打刷 `boot_a`。解锁后 **0 次 SIGABRT**、launcher 有焦点；`su`→`uid=0 ... u:r:ksu:s0`；`ksud 4.3.0 (uapi: 6)`；`ksud kpm list` **rc=0**（旧 pin 是 `os error 95`）；内核日志有 `KP KernelPatch Version: e00` 与 `susfs is initialized! version: v2.3.0`；管理器首页无红条、内核版本 `v4.3.0-b16e899a@HEAD`、SUSFS `v2.3.0 (SUSFS Inline Hook)` 与 KPM 卡都在。⚠️ 必须带 `patch-ksu-builtin.py` 的三处修补，否则 mount_hide 会把 SystemUI 打进崩溃循环（§3.4） |
| 同上（完整树重构） | 同上 | `e67b14e6` (v4.3.0 tag, **UAPI 6**) | ✅ 2026-11-01 本地重编（5m14s）后实机 fastboot 刷 `boot_a`+`boot_b`：40s 开机、`su`→uid=0、`ksud 4.3.0 (uapi: 6)`、管理器 v4.3.0 红条消失、GUI 可操作、`/proc/config.gz` 与构建 ikconfig 零差异、minidump 无新增；CI `41269038858` 双变体绿。**同日 11:57 直接刷 CI 产物本身**（不重编）：40s 开机、build 时间戳 = CI 构建时刻、config 7755 行 0 diff、minidump md5 不变；`droidspaces v7.1.0 check` 全绿 + Alpine 3.22.1 容器实跑成功（见 §6） |

## 6. 验证记录

| 项 | 值 |
|---|---|
| 本地构建 | 2026-10-31 22:10 首编 **5m11s**；2026-11-01 00:54 换 KSU v4.3.0 重编 **5m14s**（同机 -j20）；`Image` 37MB |
| 版本串 | `Linux version 5.10.269-gki-droidspaces-lakitu (lakitu@localhost) (Android (15682573 … clang version 22.0.2 …) #1 SMP PREEMPT` |
| ikconfig | `LTO_CLANG_THIN=y` + `# CONFIG_LTO_CLANG_FULL is not set` + `CFI_CLANG=y` + `SYSVIPC/POSIX_MQUEUE/IPC_NS/PID_NS/DEVTMPFS/USER_NS/KALLSYMS_ALL/KPROBES/MACVLAN/IP_SET=y` |
| 干净克隆复现 | 从 `file://` 新 clone（只有 tracked 文件，= CI 看到的文件集）→ verify-tree 过 → 编过 → ikconfig 与工作树构建**逐行相同**（证明仓库自足，不依赖 tarball 里的残留文件） |
| kABI 布局 | 见 §7：9908 个同名类型**一个都没变尺寸** |
| CI | run `41217178370`（`de0df778`，pin 仍是 `dfae923`/UAPI 5）：**双变体绿**，各 ~27 min；此前 `41209919015`/`41214550495` 红在 `techpack/stub`，见 §8。换 pin 后的 `41222918907` 红在下载截断（基础设施）；下载步骤加完整性校验后 `41269038858` 双变体绿，见 §8 |
| 上机（本地构建） | 2026-11-01 00:31 先刷 CI ksu 产物（pin `dfae923`，UAPI 5）验证基底，40s 开机；01:00 换 `e67b14e6`（v4.3.0，UAPI 6）重编后重刷 `boot_b`+`boot_a`。`magiskboot` 用旧 boot 镜像的 ramdisk + 新 `Image` 重打 192MB boot。验收：`sys.boot_completed=1`；`uname -r` = `5.10.269-gki-droidspaces-lakitu`（本地 build 2026-11-01 00:54:17）；管理器里授权 Termux 后 `/system/bin/su -c id` = `uid=0(root) ... context=u:r:ksu:s0`；`ksud 4.3.0 (uapi: 6)` 的 `feature list`/`module list` rc=0；管理器「需要更新内核」红条消失、内核完整版本 `v4.3.0-e67b14e6@HEAD`、拓展功能页可加载；`/proc/config.gz` 与构建 ikconfig **7755 行零差异**；minidump 与 2026-10-16 快照 **md5 相同**（无新增 dump）；pstore 空、mtdoops last-kmsg（#2036）无 panic |
| 上机（**CI 产物**，2026-11-01 11:57） | CI `41269038858` 的 `Image-…-KSU-KPM` 用 magiskboot 重打后刷 `boot_a`+`boot_b`，**两槽都换成同一个 CI 镜像**（先 `--set-active=a` 验，再 `--set-active=b` 回滚位），每次 ~40s 进系统。**`uname -a` 的 build 时间是 `Sun Nov 1 03:33:03 UTC 2026` = CI run 的构建时刻**（不是本地 00:54 那次）→ 确认跑的就是 CI 产物。`su`→`uid=0 … u:r:ksu:s0`；`ksud 4.3.0 (uapi: 6)`；`feature list`/`module list` rc=0，**`feature set sulog 1/0` 写操作 rc=0**（UAPI 校验通过）；管理器 v4.3.0 (41100-6) 首页无红条、内核完整版本 `v4.3.0-e67b14e6@HEAD`；`/proc/config.gz` 与 CI `Image` 的 ikconfig **7755 行 0 diff**；minidump md5 `ff5dc1f4…` 与 2026-10-16 基线**逐字节相同**；pstore 空、dmesg 无 panic/Oops |
| DroidSpaces `check`（**首次**，v7.1.0） | 全部 `[MUST HAVE]`（root/Linux version/PID・Mount・UTS・IPC ns/pivot_root/proc/sys/seccomp）与 `[RECOMMENDED]`（epoll/signalfd/PTY/devpts/loop/ext4/cgroup v2/cgroup ns/devtmpfs）**全绿**；仅两个 `[OPTIONAL]` 为 ✗：CPU limit（`CONFIG_CFS_BANDWIDTH`）、Process limit（`CONFIG_CGROUP_PIDS`）——两者在 stock GKI `gki_defconfig` 里本来就没开，官方 GKI 清单也明确写「**DO NOT** enable anything other than the recommended GKI configuration」，故不动；缺它们只影响 `--cpus`/`--pids-limit`，工具自己标注「skipped if absent」 |
| 上机（**SUSFS + KPM**，2026-11-01 17:58） | `out-full` 的 Image（build 戳 `Sun Nov 1 17:56:59 CST 2026`）经 `kptools -p` 预补丁、magiskboot 重打成 192MB boot 刷 `boot_a`。验收：解锁（`input keyevent 82`）后 `adb logcat` 里 `Fatal signal 6 .*(launcher3|systemui)` **0 次**、`Failed to open the /proc/mounts` **0 次**、`mCurrentFocus` = launcher3；Termux 里 `/system/bin/su -c sh /sdcard/vf.sh` 得到 `uid=0(root) gid=0(root) context=u:r:ksu:s0`；`ksud 4.3.0 (uapi: 6)`；`feature list` 里 `mount_hide` = DISABLED（预期，见 §3.4）、`ksud kpm list` rc=0 且无报错、管理器拓展页 `[AVAILABLE] kpm (ID=0)`；`dmesg` 有 `KP KernelPatch Version: e00`、`KP sukisu_kpm_supercall_install done: 0`、`susfs is initialized! version: v2.3.0`；管理器截图：内核 `v4.3.0-b16e899a@HEAD`、`SuSFS 版本 v2.3.0 (SUSFS Inline Hook)`、`KPM (0 KPM)`、无红条 |
| 上机（**CI 产物**，2026-11-01 19:00，`41297579532`） | 下载 CI 的 `Image-…-KSU-KPM-SUSFS`（41,152,112 B）用 magiskboot 重打后刷 `boot_a`，45s 开机。**`uname -v` = `#1 SMP PREEMPT Sun Nov 1 10:38:26 UTC 2026` = 该 CI 构建时刻**；`/proc/config.gz` 与产物 ikconfig **7768 行 0 diff**（10 个 `CONFIG_KSU_SUSFS*=y`、`KSU=y`、`KPM=y`）；`kptools -l` 对产物 `patched=true` / `version=0xe00`；解锁后 `Fatal signal 6 .*(launcher3|systemui)` **0 次**、`Failed to open the /proc/mounts` **0 次**、焦点 launcher3；Termux 里 `su -c` → `uid=0(root) ... context=u:r:ksu:s0`（su 由 `su_compat` 提供，app 进程里 `/system/bin/su` 才可见，adbd-root 上下文里不存在）；`ksud 4.3.0 (uapi: 6)`、`kpm list` rc=0、`susfs status`=true、`susfs version`=v2.3.0、`feature list` 里 `mount_hide`=DISABLED；`dmesg`：`KP KernelPatch Version: e00`、`KP sukisu_kpm_supercall_install done: 0`、`susfs is initialized! version: v2.3.0`；minidump md5 `ff5dc1f4…` 与 10-16 基线一致；管理器截图 `probes/marble-ci-41269038858/ci41297579532_manager.png`（`v4.3.0-b16e899a@HEAD`、`SuSFS v2.3.0 (SUSFS Inline Hook)`、`KPM 0`、超级用户 4）。**SUSFS 没有破坏容器**：`droidspaces check` 仍然「All required features found!」（只有和 stock GKI 一样的两个 OPTIONAL 缺项），同一个 Alpine 3.22.1 rootfs `start` + `run cat /etc/alpine-release`（3.22.1）/`run uname -r`（`5.10.269-gki-droidspaces-lakitu`）都正常，随后 `stop` 优雅退出 |
| 容器实跑（**首次**，2026-11-01 12:13） | Alpine 3.22.1 minirootfs（3.8MB）解到 `/data/local/tmp/rootfs`，`droidspaces -n smoke --net=none start` → **RUNNING（PID 8590，Alpine Linux v3.22，hostname smoke，SELinux Enforcing）**；容器内 `cat /etc/alpine-release` = `3.22.1`、`id` = `uid=0`、`uname -r` = `5.10.269-gki-droidspaces-lakitu`、`nproc` = 8、`/proc/1` 在；`stop` 优雅退出、`show` 清空。⚠️ 启动时警告 `Failed to remount /data with suid support`——`/data` 是 `nosuid,nodev` 的 f2fs（Android 设计如此，非内核缺陷），所以 setuid 类程序（su/sudo/passwd）在 /data 上的 rootfs 里失效；要做这类事用 `--rootfs-img` 稀疏镜像（App 也推荐这个） |

> **KSU UAPI 注（2026-11-01 已解决）**：原 pin `dfae923`（v4.2.1，UAPI 5）与设备管理器
> v4.3.0 (41100-**6**) 不匹配——管理器首页红条「需要更新内核」（源码
> `HomeViewModel.kt:102`：`requiresNewKernel = managerUAPIVersion > kernelUAPIVersion`），
> 且 ksud 的 `ensure_uapi_version_matched` 让所有写操作失败，表现就是 GUI 基本点不动。
> 把 pin 提到 `e67b14e6`（v4.3.0 tag，UAPI 6）重编刷入后：红条消失、`ksud feature list`/
> `module list` rc=0、`su` 正常。**以后换 KSU pin 必须同时看管理器的 UAPI**（v4.2.1 = 5，
> v4.3.0 = 6）。

§6 里那次本地构建的命令就是 README 里那四条，没有别的魔法。

## 7. kABI 证据（pahole 实测，2026-10-31）

开 `CONFIG_SYSVIPC`/`POSIX_MQUEUE` 会不会让 ROM 里预编译的 vendor_dlkm 模块错位？这是
DroidSpaces 那对 kABI 补丁的**唯一**理由，所以不能只靠「打了补丁应该没事」，直接量。

方法：同一棵树编两次，只差配置——

```bash
# A) 我们的配置（gen-config.sh 产出的 out/.config）
# B) stock 配置：gki_defconfig + vendor/waipio_GKI → xiaomi_GKI → marble_GKI → debugfs
#    唯一的改动是把 LTO 换成 THIN，否则 15GB 的机器在 FULL LTO 链接阶段被 OOM 杀掉
#    （LTO 只影响代码生成，不影响结构体布局）
pahole -s A/vmlinux > sizes-a.txt; pahole -s B/vmlinux > sizes-b.txt
./.github/scripts/kabi-layout-diff.py A/vmlinux B/vmlinux
```

结果：

| 检查 | 结果 |
|---|---|
| 同名类型 size 变化 | **0 / 9908** |
| 只在我们的镜像里的类型 | 106 个，全是 SYSVIPC/POSIX_MQUEUE 带进来的（`compat_ipc_perm`、`mq_attr`、`semid64_ds` …） |
| `task_struct` | `sysvsem @3592 (8B)`、`sysvshm @3600 (16B)`，正好盖住 stock 的 `android_kabi_reserved6/7/8`；其后的字段偏移逐个一致 |
| `user_struct` | `mq_bytes @120 (8B)` 盖住 stock 的 `android_kabi_reserved1` |

结论：不止 `task_struct`，**全内核同名类型的尺寸都没变**，所以 stock 编的模块按原偏移
访问内核结构体是安全的。这个脚本留在 `.github/scripts/kabi-layout-diff.py`，换基底或
加配置时重跑；它比「ABI 符号表看起来没报错」硬得多。

## 8. CI 记录

| run | 提交 | 结果 |
|---|---|---|
| `41209919015` | `a81d0e75` | ❌ 两变体都挂在 `verify-tree.sh`：`techpack/stub missing` —— 那是上游 `.gitignore`（`techpack/.gitignore` 的 `*/`）吃掉的 7 个 tracked 文件之一，见 [upstream-base.md](upstream-base.md) 的 import 自检 |
| `41214550495` | `440e4a84` | ❌ 门禁修好了，但树里仍缺 `techpack/stub` → `make` 报 `scripts/Makefile.build:45: .../techpack/stub/Makefile: No such file` |
| `41217178370` | `de0df778` | ✅ 双变体绿。build 步骤 18–19 min（与 2026-10-16 的 18m43s 相当），总 27 min。产物已下载核对：`Image-5.10.269-gki-droidspaces-lakitu-{KSU-KPM,BYPASS-noKSU}` 版本串为 `5.10.269-gki-droidspaces-lakitu`，ksu 变体 ikconfig 有 `KSU/KPM=y`、bypass 没有；AK3 zip 里 `BLOCK=boot`/`IS_SLOT_DEVICE=auto`/`NO_MAGISK_CHECK=1`，magiskboot 788840 B、magiskpolicy 356584 B，zip 内 `Image` 版本串正确 |
| `41222918907` | `b3cf5cec` | ❌ 基础设施，不是代码问题：`Fetch clang prebuilt` 阶段 android.googlesource.com 把 ~1.1GB 的 tar.gz 传到一半截断（curl 退出 0、`gzip: unexpected end of file` / `tar: Unexpected EOF in archive`），两个变体各耗 ~6 min 后挂。修法：下载后 `gzip -t` 验完整性 + 最多 4 次整份重下（`build.yml`），坏包只损失一次尝试而不是后面的编译 |
| `41269038858` | `f591e74c` | ✅ 双变体绿（ksu 23m06s、bypass 18m39s），用的就是修好的下载步骤。产物下载核对：两个 `Image` 版本串都是 `5.10.269-gki-droidspaces-lakitu`；ksu 变体 `CONFIG_KSU=y`/`KSU_MANUAL_SU=y`/`KPM=y`、bypass 三者全无；ikconfig 分别 7755/7744 行；AK3 zip `BLOCK=boot`/`IS_SLOT_DEVICE=auto`/`NO_MAGISK_CHECK=1`、`magiskboot` 788840 B、`magiskpolicy` 356584 B。**ksu `Image` 的 ikconfig 与 2026-11-01 实机刷入验证过的本地 v4.3.0 构建逐行相同（0 diff）** |
| `41297579532` | `272ab099` | ✅ 双变体绿（ksu **30m04s**、bypass 23m03s；ksu 多出来的 ~7 min 是 KernelPatch 步骤：clone KP → 编 kptools → 下 kpimg → 预补丁）。这一步同时验证了所有新门禁：`verify-tree.sh` 的 SUSFS 断言、`config KSU_SUSFS*`=10、`patch-ksu-builtin.py` 三处修补、`CONFIG_KSU_SUSFS*=y`=10、产物里 `susfs is initialized! version: v2.3.0` + `KernelPatch Version:`、`kptools -l` = `patched=true`/`version=0xe00`。产物核对：ksu Image 41,152,112 B、bypass 38,428,876 B；ksu ikconfig **7768 行**、与本地干净克隆构建**逐行相同**；AK3 zip 里 `BLOCK=boot`/`IS_SLOT_DEVICE=auto`、`magiskboot` 788840 B、`magiskpolicy` 356584 B。**该产物已直接刷机验收**（见 §6）|
