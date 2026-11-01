# marble LineageOS 24.0 内核（DroidSpaces + SukiSU Ultra）

Redmi Note 12 Turbo / POCO F5（marble，SM8450）的 LineageOS 24.0 内核，带 DroidSpaces
容器支持、SukiSU Ultra root（SUSFS + KPM）。

内核源码整个在仓库根目录，CI 编的就是仓库里提交的东西。构建期只从外部拉 SukiSU 和
KernelPatch 两样，都不入库，按 commit 钉死。

## 内容

- 基底：LineageOS [`android_kernel_xiaomi_sm8450`](https://github.com/LineageOS/android_kernel_xiaomi_sm8450)
  `lineage-24.0` @ `eff4b404`，Linux 5.10.269
- DroidSpaces：namespace / SysV IPC / netfilter 配置，加 kABI padding
  （`include/linux/sched.h`、`sched/user.h`），开 `SYSVIPC` 不改结构体布局
- SUSFS 2.3.0：树内提交 `5332250`
- SukiSU Ultra `builtin`：构建期注入 `drivers/kernelsu`，UAPI 6
- KernelPatch：构建期把 kpimg 预补丁进 Image，KPM 才能用

和 [kernel_dash_droidspaces](https://github.com/lakitu12/android_kernel_xiaomi_dash) 的
区别是不做 KVM/EL2（marble 开不了），因此没有 gz、trusty-rescue、`kvm-arm.mode=nvhe`；
基底本身就是 ROM 出厂那棵树，KMI 天然对齐，不需要补 vendor hook。

## 仓库结构

| 路径 | 内容 |
|---|---|
| 仓库根 | 完整内核树，68,710 个文件 |
| `arch/arm64/configs/marble_gki.fragment` | 配置增量（DroidSpaces 的 namespace / SysV IPC / netfilter 集合，LTO FULL→THIN）。KSU/SUSFS 的符号由 CI 注入，它们要等 `setup.sh` 放好 `drivers/kernelsu` 才存在 |
| `include/linux/sched.h`、`sched/user.h` | DroidSpaces kABI padding |
| `.github/scripts/gen-config.sh` | 配置入口：vendor 配置链 + fragment，本地和 CI 同一份 |
| `.github/scripts/verify-tree.sh` | 源码门禁：树身份、kABI padding、`gki_defconfig` 未被改动、SUSFS 钩子在位 |
| `.github/scripts/kabi-layout-diff.py` | 比对两份 vmlinux 的同名类型尺寸，证明 kABI 未破 |
| `.github/scripts/patch-ksu-builtin.py` | 修 builtin 分支的三处构建期问题 |
| `docs/` | 基底来历、版本冻结、上游 README 原文 |

树里的 delta 只有三个提交：kABI padding（`4da795e`）、SUSFS 2.3.0（`5332250`）、
配置与 CI（`14ce48f`）。改动全在提交里，review 用 `git log`，回滚用 `git revert`。

## 构建

CI 在 push 到 `main` 或手动 `Run workflow` 时跑，矩阵两个变体：

- `ksu`：SukiSU builtin（UAPI 6）+ 10 个 SUSFS 功能 + KernelPatch 预补丁
- `bypass`：同一棵树，KSU 关掉

产物是 AnyKernel3 zip 和裸 `Image`。

本地构建与 CI 等价：

```bash
export PATH=<clang-r596125>/bin:$PATH    # clang r596125 (22.0.2)
bash .github/scripts/verify-tree.sh .

# 注入 SukiSU builtin，修三处，打开 KSU/SUSFS 配置
KSU_PIN=b16e899a555e9b96aa1225f049cd7274820ca5b8
curl -LSs "https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/$KSU_PIN/kernel/setup.sh" | bash -s "$KSU_PIN"
python3 .github/scripts/patch-ksu-builtin.py .
bash .github/scripts/gen-config.sh . out -droidspaces-lakitu
for c in KSU KPM KSU_SUSFS KSU_SUSFS_SUS_PATH KSU_SUSFS_SUS_MOUNT KSU_SUSFS_SUS_KSTAT \
        KSU_SUSFS_SPOOF_UNAME KSU_SUSFS_ENABLE_LOG KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS \
        KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG KSU_SUSFS_OPEN_REDIRECT KSU_SUSFS_SUS_MAP; do
  sed -i "/^# CONFIG_${c} is not set/d; /^CONFIG_${c}=/d" out/.config; echo "CONFIG_${c}=y" >> out/.config
done
make O=out ARCH=arm64 TARGET_PRODUCT=marble LLVM=1 LLVM_IAS=1 olddefconfig
make O=out ARCH=arm64 TARGET_PRODUCT=marble LLVM=1 LLVM_IAS=1 -j$(nproc) Image
```

`TARGET_PRODUCT=marble` 不能省，`drivers/input/Makefile` 按它加 `-DCONFIG_TARGET_PRODUCT_MARBLE`。

KPM 还需要一步 KernelPatch 预补丁（`kptools -p -i Image -k kpimg -S <superkey> -o Image`），
完整步骤见 `.github/workflows/build.yml`。

## 刷入

- AnyKernel3 zip：用 SukiSU 管理器或支持 AK3 的刷写器刷，保留原 ramdisk
- 裸 Image：用旧 boot 镜像的 ramdisk + 新 `Image` 用 `magiskboot` 重打，`fastboot flash`；
  A/B 设备两个槽都要刷
- 管理器用 v4.3.0（UAPI 6），与内核 pin 的 UAPI 线一致

## 注意事项

**clang 必须是 r596125 (22.0.2)**，与 ROM 出厂内核同一个 release。CFI/BTI 的代码生成
与校验只在这个范围内兼容，用别的版本编出来的内核会在第一次调用 vendor 模块时触发
`Bad mode ... BTI` 然后 panic 重启。

**必须跑 `patch-ksu-builtin.py`**。builtin 的 `mount_hide` 对 `/proc/{mounts,mountinfo,mountstats}`
的 open 返回 `-ENOENT`，而它默认是开的、门控覆盖所有普通 app，结果是任何读 `/proc/mounts`
的进程 abort（libincfs），SystemUI 和 launcher 进崩溃循环。脚本把它改成默认关、open 恒成功，
挂载隐藏交给 SUSFS 的 `sus_mount`。所以管理器里 `mount_hide` 显示 DISABLED 是预期状态。

LTO 用 `LTO_CLANG_THIN`（stock 是 FULL）：FULL 链接阶段要 16GB 以上，GitHub runner 只有 7GB。

`/data` 是 `nosuid,nodev`（Android 设计），容器 rootfs 放在 `/data` 里时 setuid 程序
（su、sudo、passwd）不可用；需要这类功能用 `--rootfs-img` 稀疏镜像。

## 来源

- 内核：<https://github.com/LineageOS/android_kernel_xiaomi_sm8450>（`lineage-24.0` @ `eff4b404`）
- DroidSpaces：<https://github.com/ravindu644/Droidspaces-OSS>（kABI 补丁在 `GKI/below-kernel-6.12/`）
- SukiSU Ultra：<https://github.com/SukiSU-Ultra/SukiSU-Ultra>（`builtin` 分支）
- SUSFS：<https://gitlab.com/simonpunk/susfs4ksu>（`gki-android12-5.10` @ `3c8f72e`）
- KernelPatch：<https://github.com/bmax121/KernelPatch>（`d4c88d6`）
- kpimg：<https://github.com/ShirkNeko/SukiSU_patch>（`eec45788`）
- AnyKernel3 模板：<https://github.com/Numbersf/AnyKernel3>
- 基底导入流程：[docs/upstream-base.md](docs/upstream-base.md)
- 版本冻结与理由：[docs/version-pins.md](docs/version-pins.md)
