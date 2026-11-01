# kernel_marble_droidspaces

marble（Redmi Note 12 Turbo / POCO F5，SM8450）的 **LineageOS 24.0 内核**：
DroidSpaces（宿主容器）+ SukiSU Ultra（KPM）。仓库布局与方法论照
[kernel_dash_droidspaces](https://github.com/lakitu12/android_kernel_xiaomi_dash)：
**内核源码整个就在仓库根目录**，CI 编的就是 check in 的东西。

与 dash 的唯一区别是**不做 KVM/EL2**那一套（marble 开不了），所以没有 gz、没有
trusty-rescue、没有 `kvm-arm.mode=nvhe`；也没有 vendor hook 差额——基底本身就是
ROM 出厂用的那棵树，KMI 天然对齐。

## 仓库结构（`main`）

| 路径 | 内容 |
|---|---|
| 仓库根 | 完整内核树：LineageOS `android_kernel_xiaomi_sm8450` `lineage-24.0` @ `eff4b404`（Linux **5.10.269**，68,710 个文件） |
| `arch/arm64/configs/marble_gki.fragment` | 我们的**全部**配置增量（DroidSpaces 的 namespace/SysV IPC/netfilter 集合、KSU 符号、LTO FULL→THIN） |
| `include/linux/sched.h`、`sched/user.h` | DroidSpaces kABI padding（`sysv_sem`/`sysv_shm`/`mq_bytes` 挪进 Android ABI 预留位） |
| `.github/scripts/gen-config.sh` | 配置唯一入口：LineageOS vendor 链 + 我们的 fragment（本地与 CI 同一份） |
| `.github/scripts/verify-tree.sh` | 源码级门禁：树的身份 / kABI padding / gki_defconfig 是否被动过 |
| `.github/scripts/kabi-layout-diff.py` | 离线证明 kABI 没破：两份 vmlinux 的同名类型尺寸比对（见 docs/version-pins.md §7） |
| `docs/` | 基底来历、版本冻结、上游 README 原文 |

> 根 `README.md` 是本仓库说明，覆盖了上游 kernel 的那份；上游原文留在
> [`docs/upstream-kernel-README.md`](docs/upstream-kernel-README.md)。
> 根 `.gitignore` = 上游那份 + 末尾追加的 `__pycache__/`、`*.pyc`、`!.github/**`。

### 烘在树里的 delta 只有两条

| 提交 | 内容 |
|---|---|
| `4da795e` | **DroidSpaces kABI padding**：`sysv_sem → ANDROID_KABI_RESERVE(6)`、`sysv_shm → KABI_REPLACE(7;8)`、`mq_bytes → user_struct 的 KABI_USE(1)`。于是开 `CONFIG_SYSVIPC`/`POSIX_MQUEUE` 不改任何布局，ROM 里预编译的几百个 vendor_dlkm 模块照旧能加载 |
| `14ce48f` | 配置文件 + 构建/门禁脚本 + CI（`gki_defconfig` 保持上游原样，我们的配置一律进 fragment） |

不再有 `patches/` 目录，也不再在 CI 里给内核树打补丁（2026-10-31 起）。review 就是
`git log`，回滚就是 `git revert`。

## 构建

CI（GitHub Actions，push 到 `main` 或手动 `Run workflow`）：

- 矩阵 `ksu` / `bypass` 并行；产物是 AnyKernel3 zip + 裸 `Image`
- 构建期唯一注入内核树的外部组件是 **SukiSU Ultra + KPM**（不入库，按 commit 钉死）

本地（与 CI 等价，clang 必须和 ROM stock 内核同一个 release，见下）：

```bash
export PATH=~/clang/bin:$PATH            # clang r596125 (22.0.2)
bash .github/scripts/verify-tree.sh .
bash .github/scripts/gen-config.sh . out -droidspaces-lakitu
make O=out ARCH=arm64 TARGET_PRODUCT=marble LLVM=1 LLVM_IAS=1 -j$(nproc) Image
```

`TARGET_PRODUCT=marble` 不是装饰：`drivers/input/Makefile` 按它加
`-DCONFIG_TARGET_PRODUCT_MARBLE`。

### 已验证到什么程度（2026-11-01）

- 本地 `-j20` 全量构建 **5m11s** 出 `Image`（37MB），版本串
  `5.10.269-gki-droidspaces-lakitu`，ikconfig 里 `LTO_CLANG_THIN`/`CFI_CLANG`/DroidSpaces 全套都在；
- **干净克隆**（只有 git 跟踪的文件，= CI 的文件集）从零构建通过，ikconfig 与工作树构建逐行相同；
- **kABI 布局实测**：我们的配置 vs stock 配置，9908 个同名类型 **0 个尺寸变化**，
  `sysv_sem`/`sysv_shm`/`mq_bytes` 正好落在 `android_kabi_reserved6..8` / `reserved1` 上
  → ROM 里预编译的 vendor_dlkm 模块按原偏移访问是安全的。证据与复现命令见
  [docs/version-pins.md §7](docs/version-pins.md)。
- **实机（2026-11-01）**：`magiskboot` 用旧 boot 镜像的 ramdisk + 新 `Image` 重打 boot 后
  `fastboot flash` 到 `boot_b`+`boot_a`，~40s 开机；`uname -r` =
  `5.10.269-gki-droidspaces-lakitu`；管理器里授权一个 app 后 `/system/bin/su -c id` →
  `uid=0`（`u:r:ksu:s0`）；`/proc/config.gz` 与构建出的 ikconfig **7755 行零差异**；
  minidump 与 2026-10-16 快照 **md5 相同**（无新增崩溃 dump），pstore 空、dmesg 无 panic。
- **KSU 管理器（2026-11-01）**：pin 从 v4.2.1（UAPI 5）提到 v4.3.0（UAPI 6）后，设备上的
  v4.3.0 管理器红条「需要更新内核」消失，超级用户/模块（`ksud`）操作恢复；换 pin 时必须
  同时看管理器 UAPI，见 [docs/version-pins.md §3](docs/version-pins.md)。该 pin 的 CI
  `41269038858` 双变体绿，其 ksu 产物 ikconfig 与实机刷入的本地构建**逐行相同**（7755 行，
  0 diff）。

### 工具链铁律（实机踩过，2026-10-16）

内核必须用 **clang r596125 (22.0.2)** 编——与 ROM stock 内核 `5.10.269-gki-geff4b40407a1`
完全同一个 clang release。`CFI_CLANG`/BTI 的代码生成与校验 ABI 只在同一 release 内兼容：
用 r547379 (20.0.0) 编出来的内核在 `__cfi_check` 第一次调 vendor 模块（`qcom_tsens`）
时触发 `Bad mode ... code 0x36000002 -- BTI` → `Kernel panic - not syncing: bad mode`，
0.3 秒重启循环。取证在 `~/code/probes/marble-lineage24-cfi-20261016/`。

LTO 用 `LTO_CLANG_THIN`（stock 是 `LTO_CLANG_FULL`）：FULL 的链接阶段要 16GB+，7GB 的
GitHub runner 会 OOM；THIN 仍是真 LTO，`CONFIG_CFI_CLANG=y` 不受影响，已实机验证。

## 刷入与验收

- AnyKernel3 zip 用 SukiSU 管理器或支持 AK3 的刷写器刷（保留原 ramdisk）
- A/B 设备：手动刷 image 时两个槽都要刷（`boot_a` + `boot_b`）
- **管理器要和内核 UAPI 对上**：本仓库 KSU pin 在 v4.3.0 线（UAPI 6），管理器用
  v4.3.0（41100，UAPI 6）；装 v4.2.1 管理器（UAPI 5）会提示「需要更新管理器」，
  反之 v4.3.0 管理器配 UAPI 5 内核会红条「需要更新内核」且 ksud 写操作全失败
  （见 [docs/version-pins.md §6](docs/version-pins.md) 注）
- 验收：`sys.boot_completed=1`、`uname -r` 为 `5.10.269-gki-droidspaces-lakitu`、
  授权一个 app 后 `/system/bin/su -c id` → `uid=0`、`/proc/config.gz` 与 CI `Image` 的
  ikconfig diff 为空、minidump 无新增；`droidspaces check` 需要设备装有 DroidSpaces 工具

## 来源

- 内核：<https://github.com/LineageOS/android_kernel_xiaomi_sm8450>（`lineage-24.0` @ `eff4b404`）
- DroidSpaces：<https://github.com/ravindu644/Droidspaces-OSS>（kABI 补丁 `GKI/below-kernel-6.12`）
- SukiSU Ultra：<https://github.com/SukiSU-Ultra/SukiSU-Ultra>
- AnyKernel3 模板：<https://github.com/Numbersf/AnyKernel3>
- 基底来历与重新导入流程：[docs/upstream-base.md](docs/upstream-base.md)
- 版本冻结（clang / KSU / AK3）：[docs/version-pins.md](docs/version-pins.md)