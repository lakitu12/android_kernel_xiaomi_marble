# 版本冻结（clang / SukiSU / AnyKernel3 / DroidSpaces）

> 这份文档是「为什么钉这个」的唯一出处。改 pin 必须同时改这里、CI 里的 `env:` 和
> 本文末尾的验证记录。

## 1. 现状（2026-11-01）

| 组件 | 钉住的对象 | 位置 | 说明 |
|---|---|---|---|
| clang | `clang-r596125`（22.0.2，AOSP `main-kernel`） | CI `CLANG_URL` | **必须**与 ROM stock 内核同一个 release，见 §2 |
| SukiSU Ultra | `main` 线 `e67b14e6bbbb`（v4.3.0 tag，**UAPI 6**） | CI `KSU_PIN` | 构建期注入，不入库；**不带 SUSFS**；必须和管理器 APK 同一 UAPI 线，见 §3 |
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

## 3. 为什么 KSU 用 main 线、没有 SUSFS、且必须和管理器同 UAPI

`lineage-24.0` 这条线一开始就是按 **main 线 stable** 建的，原因是当时 SukiSU 的
`builtin` 分支（唯一带 `KSU_SUSFS*` Kconfig 的分支）处于半合并状态：2026-10-15 的
HEAD 里 `ksu_manager_cmd`、重复的 `KSU_IOCTL_KPM`、`TRACK_THRONE` 都编不过，而 main 线
一编就过。当时的选择是「先有能开机的 root」，SUSFS 留空。

最初钉的是 `dfae923`（v4.2.1-40994，**UAPI 5**），特征：main 线 `kernel/Kconfig` 里
`config KSU_SUSFS` **0 项**，所以工作流里没有任何 `CONFIG_KSU_SUSFS*`，
`CONFIG_KSU=y` + `CONFIG_KPM=y` 就是全部。

**2026-11-01 换成 `e67b14e6`（v4.3.0 tag，UAPI 6）**：设备上的管理器是 v4.3.0
(41100-**6**)，而 UAPI 5 的内核在管理器里会触发
`requiresNewKernel = managerUAPIVersion > kernelUAPIVersion`（`HomeViewModel.kt:102`）：
首页红条「需要更新内核」，并且 ksud 的 `ensure_uapi_version_matched` 会让所有写操作
直接失败——表现就是「管理器 GUI 什么都点不动」。v4.3.0 tag 与 v4.2.1 同为 main 线、
同样没有 `KSU_SUSFS`，UAPI 升到 6，管理器与内核对齐后 GUI 恢复正常（见 §6）。

**升级到 builtin + SUSFS 的路径**（想做的时候照这个来，别直接换）：

1. dash 上 `builtin@b16e899a` + `susfs4ksu` 同日提交这一对已经验证可开机
   （见 dash 仓库 `docs/version-pins.md`）；marble 是 5.10，SUSFS 对应分支是
   `gki-android12-5.10`，**不能直接复用 6.6 的 patch**；
2. 先按 dash 的配对门禁静态核对（`ksu_*()` / `susfs_*()` 双向引用），再编；
3. 只有编过 + 实机开机 + `su` 可用，才把 pin 换掉；
4. 换上之后这条文档、CI 注释、`/data/adb/ksu` 验收步骤要一起更新。

顺带一提：旧的 `main` 分支（AOSP 5.10.236 基底那套）**确实**跑过
builtin + `gki-android12-5.10` 的 SUSFS，所以 5.10 上的组合是存在过的，只是那套 CI 走的
是另一棵基底（现在存档为 `main-legacy`）。

## 4. CI 里的冻结断言

- `Fetch clang prebuilt`：`clang --version` 必须含 `clang version 22.0.2`；
- `Setup SukiSU Ultra`：`drivers/kernelsu` 的 `HEAD` 必须等于 `KSU_PIN`，并打印
  `KSU @ <sha> <date> <subject>` 与构建日志里的 `SukiSU-Ultra version:`；
- `Prepare AnyKernel3`：`AK3_PIN` 必须匹配，且 `tools/magiskboot` = 788840 B、
  `tools/magiskpolicy` = 356584 B（工具漂了一度把设备刷成 panic）；
- 版本门禁：Image 里必须有 `5.10.269` + `droidspaces-lakitu`，ikconfig 里必须有
  `LTO_CLANG_THIN` / `CFI_CLANG` / `SYSVIPC` / `POSIX_MQUEUE`，ksu 变体再加
  `CONFIG_KSU` / `CONFIG_KPM`，bypass 变体反过来断言两者都不在。

## 5. 已知可开机的组合

| 基底 | 工具链 | KSU | 结果 |
|---|---|---|---|
| LineageOS `eff4b404` (5.10.269) | r596125 (22.0.2) | `dfae923` (v4.2.1-40994, **UAPI 5**) | ✅ 2026-10-16 实测：CI `38835130001` 双变体绿；AK3 刷入 KSU-KPM 变体正常开机、KernelSU 激活、minidump 无新增崩溃。2026-11-01 完整树重构后 CI `41217178370` 双变体绿 + 实机 fastboot 刷入：40s 开机、`su`→uid=0、`/proc/config.gz` 与 CI ikconfig 零差异、minidump 无新增。⚠️ 这一条**只配 v4.2.1 管理器**；v4.3.0 管理器会红条且写操作被 UAPI 校验挡住 |
| 同上（完整树重构） | 同上 | `e67b14e6` (v4.3.0 tag, **UAPI 6**) | ✅ 2026-11-01 本地重编（5m14s）后实机 fastboot 刷 `boot_a`+`boot_b`：40s 开机、`su`→uid=0、`ksud 4.3.0 (uapi: 6)`、管理器 v4.3.0 红条消失、GUI 可操作、`/proc/config.gz` 与构建 ikconfig 零差异、minidump 无新增；CI 记录见 §8 |

## 6. 本次（完整树重构）的验证记录

| 项 | 值 |
|---|---|
| 本地构建 | 2026-10-31 22:10 首编 **5m11s**；2026-11-01 00:54 换 KSU v4.3.0 重编 **5m14s**（同机 -j20）；`Image` 37MB |
| 版本串 | `Linux version 5.10.269-gki-droidspaces-lakitu (lakitu@localhost) (Android (15682573 … clang version 22.0.2 …) #1 SMP PREEMPT` |
| ikconfig | `LTO_CLANG_THIN=y` + `# CONFIG_LTO_CLANG_FULL is not set` + `CFI_CLANG=y` + `SYSVIPC/POSIX_MQUEUE/IPC_NS/PID_NS/DEVTMPFS/USER_NS/KALLSYMS_ALL/KPROBES/MACVLAN/IP_SET=y` |
| 干净克隆复现 | 从 `file://` 新 clone（只有 tracked 文件，= CI 看到的文件集）→ verify-tree 过 → 编过 → ikconfig 与工作树构建**逐行相同**（证明仓库自足，不依赖 tarball 里的残留文件） |
| kABI 布局 | 见 §7：9908 个同名类型**一个都没变尺寸** |
| CI | run `41217178370`（`de0df778`，pin 仍是 `dfae923`/UAPI 5）：**双变体绿**，各 ~27 min；此前 `41209919015`/`41214550495` 红在 `techpack/stub`，见 §8。换 pin 后的 `41222918907` 红在下载截断（基础设施），见 §8 |
| 上机 | 2026-11-01 00:31 先刷 CI ksu 产物（pin `dfae923`，UAPI 5）验证基底，40s 开机；01:00 换 `e67b14e6`（v4.3.0，UAPI 6）重编后重刷 `boot_b`+`boot_a`。`magiskboot` 用旧 boot 镜像的 ramdisk + 新 `Image` 重打 192MB boot。验收：`sys.boot_completed=1`；`uname -r` = `5.10.269-gki-droidspaces-lakitu`（本地 build 2026-11-01 00:54:17）；管理器里授权 Termux 后 `/system/bin/su -c id` = `uid=0(root) ... context=u:r:ksu:s0`；`ksud 4.3.0 (uapi: 6)` 的 `feature list`/`module list` rc=0；管理器「需要更新内核」红条消失、内核完整版本 `v4.3.0-e67b14e6@HEAD`、拓展功能页可加载；`/proc/config.gz` 与构建 ikconfig **7755 行零差异**；minidump 与 2026-10-16 快照 **md5 相同**（无新增 dump）；pstore 空、mtdoops last-kmsg（#2036）无 panic。设备未装 DroidSpaces 工具，`droidspaces check` 未执行（配置层已由 ikconfig 证明） |

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
| `41222918907` | `b3cf5cec` | ❌ 基础设施，不是代码问题：`Fetch clang prebuilt` 阶段 android.googlesource.com 把 ~1.5GB 的 tar.gz 传到一半截断（curl 退出 0、`gzip: unexpected end of file` / `tar: Unexpected EOF in archive`），两个变体各耗 ~6 min 后挂。修法：下载后 `gzip -t` 验完整性 + 最多 4 次整份重下（`build.yml`），坏包只损失一次尝试而不是后面的编译 |
