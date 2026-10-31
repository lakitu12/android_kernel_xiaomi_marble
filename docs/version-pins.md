# 版本冻结（clang / SukiSU / AnyKernel3 / DroidSpaces）

> 这份文档是「为什么钉这个」的唯一出处。改 pin 必须同时改这里、CI 里的 `env:` 和
> 本文末尾的验证记录。

## 1. 现状（2026-10-31）

| 组件 | 钉住的对象 | 位置 | 说明 |
|---|---|---|---|
| clang | `clang-r596125`（22.0.2，AOSP `main-kernel`） | CI `CLANG_URL` | **必须**与 ROM stock 内核同一个 release，见 §2 |
| SukiSU Ultra | `main` 线 `dfae92378135`（v4.2.1-40994） | CI `KSU_PIN` | 构建期注入，不入库；**不带 SUSFS**，见 §3 |
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

## 3. 为什么 KSU 用 main 线且没有 SUSFS

`lineage-24.0` 这条线一开始就是按 **main 线 stable** 建的，原因是当时 SukiSU 的
`builtin` 分支（唯一带 `KSU_SUSFS*` Kconfig 的分支）处于半合并状态：2026-10-15 的
HEAD 里 `ksu_manager_cmd`、重复的 `KSU_IOCTL_KPM`、`TRACK_THRONE` 都编不过，而 main 线
一编就过。当时的选择是「先有能开机的 root」，SUSFS 留空。

`dfae923`（v4.2.1-40994）是当时的 stable tip，特征：main 线 `kernel/Kconfig` 里
`config KSU_SUSFS` **0 项**，所以工作流里没有任何 `CONFIG_KSU_SUSFS*`，
`CONFIG_KSU=y` + `CONFIG_KPM=y` 就是全部。

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
| LineageOS `eff4b404` (5.10.269) | r596125 (22.0.2) | `dfae923` (v4.2.1-40994) | ✅ 2026-10-16 实测：CI `38835130001` 双变体绿；AK3 刷入 KSU-KPM 变体正常开机、KernelSU 激活、minidump 无新增崩溃 |
| 同上（本条 + 完整树重构） | 同上 | 同上 | ⏳ 待本次 CI run 记录（见 §6） |

## 6. 本次（完整树重构）的验证记录

| 项 | 值 |
|---|---|
| 提交 | 补 |
| CI run | 补 |
| 本地构建 | 补 |
| 离线门禁 | 补 |
| 上机 | 补 |