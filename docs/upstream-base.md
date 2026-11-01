# 基底：LineageOS android_kernel_xiaomi_sm8450

仓库根目录那棵内核树的来历、导入方式、上游更新时怎么重做。

## 身份

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/LineageOS/android_kernel_xiaomi_sm8450` |
| 分支 | `lineage-24.0` |
| 提交 | `eff4b40407a1b6f1b1ab84554cbb540bcb495175` |
| 版本 | Linux 5.10.269（`Makefile` 里 `VERSION=5 PATCHLEVEL=10 SUBLEVEL=269`） |
| 规模 | 68,756 个被跟踪文件，加我们自己的 8 个；`.git` 打包后约 450MB |

选它的理由：这就是 marble 的 LineageOS 24.0 ROM 出厂内核，ROM 里 `vendor_dlkm`、
`vendor_boot` 的几百个 `.ko` 都是对着这棵树编的，vermagic、KMI、CFI 天然对齐，不需要
像 dash 那样补 vendor hook。

## 导入

```bash
git clone --depth=1 -b lineage-24.0 https://github.com/LineageOS/android_kernel_xiaomi_sm8450
cd android_kernel_xiaomi_sm8450 && git fetch --depth=1 origin eff4b40407a1b6f1b1ab84554cbb540bcb495175
git checkout FETCH_HEAD
rsync -a --exclude=.git ./ <本仓库>/ && cd <本仓库> && git add -A
```

### 导入后必须核对文件集

`git add -A` 会被内核树自己的 `.gitignore` 静默吃掉文件，包括上游其实有跟踪的。
第一次导入就丢了 7 个，其中一个让 `make Image` 直接失败：

```
techpack/stub/{Makefile,stub.c,include/uapi/stub/Kbuild}   # techpack/.gitignore 里有 "*/" 规则
arch/arm/boot/dts/vendor, arch/arm64/boot/dts/vendor       # 上游跟踪的符号链接
tools/testing/selftests/bpf/test_progs.c
tools/testing/selftests/tc-testing/plugins/__init__.py
```

症状是本地编得过（工作树里有 tarball 带进来的那份），CI 报
`scripts/Makefile.build:45: .../techpack/stub/Makefile: No such file or directory`。

导入或换基底之后跑这两条：

```bash
# 1) 文件集：上游跟踪的有没有丢
git -C <上游 clone> ls-files | sort > /tmp/up.txt
git ls-files | sort > /tmp/ours.txt
comm -23 /tmp/up.txt /tmp/ours.txt          # 输出必须为空，该补的用 git add -f

# 2) 内容：逐字节比对
rsync -rcnl --exclude=.git --exclude=.github --exclude=docs \
      --exclude=README.md --exclude=marble_gki.fragment --exclude=.scmversion \
      <上游 clone>/ ./
# 输出必须为空
```

补回来的文件要写进提交信息，说明为什么被 ignore、为什么仍然要跟踪，不要只 `add -f`
了事，否则下次换基底还会丢。

## 为什么只有一个提交

dash 需要真实历史，是因为它要做 dash-w-oss + ACK 6.6.89 + ACK 6.6.118 三方合并，
合并基底本身就是一个 commit。marble 只有一个上游修订，没有要合的东西；真历史帮不上忙，
浅拉取进来的 Linux 1.2M commit 还会把仓库撑到几个 GB。所以这里导入成一个提交，
provenance 写在提交信息和本文里。需要真历史时按需挂：

```bash
git remote add lineage https://github.com/LineageOS/android_kernel_xiaomi_sm8450
git fetch lineage lineage-24.0     # 之后 git log/blame 就能越过导入点
```

## 上游更新时怎么重做

```bash
# 1) 拿新的 lineage-24.0，先看相对我们基底改了什么
git remote add lineage https://github.com/LineageOS/android_kernel_xiaomi_sm8450
git fetch lineage lineage-24.0
git log --oneline eff4b40407a1..lineage/lineage-24.0 | head -50
git diff --stat eff4b40407a1..lineage/lineage-24.0 | tail -5

# 2) 判断两条 delta 还在不在（在就别动）
git show lineage/lineage-24.0:include/linux/sched.h      | grep -n ANDROID_KABI_RESERVE
git show lineage/lineage-24.0:include/linux/sched/user.h | grep -n ANDROID_KABI

# 3) 换基底，重放 delta
git checkout -b bump lineage/lineage-24.0
git cherry-pick 4da795e
git checkout main -- .github .gitignore arch/arm64/configs/marble_gki.fragment README.md docs
git add -A && git commit
```

几个要重新确认的点：

- kABI padding 的上下文：`ANDROID_KABI_RESERVE(3..5)`、`KABI_USE(1)` 那几行位置可能变，
  `git cherry-pick` 冲突时按「字段进预留位」的语义解，不要改结构体顺序
- `CONFIG_LTO_CLANG_FULL=y` 是否还在 `gki_defconfig`：`verify-tree.sh` 拿它当「这确实是
  上游文件」的指纹，上游若自己换成 THIN，断言要跟着改
- vendor 配置链：`gen-config.sh` 里写死了 `waipio_GKI → xiaomi_GKI → marble_GKI → debugfs`，
  上游增删 fragment 要同步
- 工具链：stock 内核换 clang 版本时 `CLANG_URL` 跟着换，见
  [version-pins.md](version-pins.md)

## 我们改了什么

相对导入提交 `08a23c3`：

```bash
git diff --stat 08a23c3..HEAD -- . ':!.github'
```

内核源码层面只有两个文件：

- `include/linux/sched.h`、`include/linux/sched/user.h`：DroidSpaces kABI padding，
  来自 Droidspaces-OSS `GKI/below-kernel-6.12/` 的 `001`、`002`，原样应用
- `arch/arm64/configs/marble_gki.fragment`、`.github/`、`docs/`、`README.md`

`gki_defconfig` 没有改动（`verify-tree.sh` 断言），这是和上游之间唯一需要保持的契约。
