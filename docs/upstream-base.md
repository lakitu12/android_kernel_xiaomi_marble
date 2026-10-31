# 基底：LineageOS android_kernel_xiaomi_sm8450

本文记录仓库根目录那棵内核树是怎么来的、为什么只 import 成一个提交、下次
LineageOS 更新时怎么重做、以及哪些东西必须在 rebase 之后重新检查。

## 1. 身份

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/LineageOS/android_kernel_xiaomi_sm8450` |
| 分支 | `lineage-24.0` |
| 提交 | `eff4b40407a1b6f1b1ab84554cbb540bcb495175`（`Merge branch 'lineage-20' of …/android_kernel_qcom_sm8450 into HEAD`） |
| 版本 | `Makefile`: `VERSION=5 PATCHLEVEL=10 SUBLEVEL=269` → Linux **5.10.269** |
| 规模 | 68,710 个文件；`.git` 打包后 ~450MB |
| 为什么是它 | 这就是 marble 的 LineageOS 24.0 ROM 出厂内核，ROM 里 `vendor_dlkm`/`vendor_boot` 的几百个 `.ko` 就是对着这棵树编的 → vermagic/KMI/CFI 天然对齐，不需要像 dash 那样补 vendor hook |

导入方式（一次性，可复现）：

```bash
git clone --depth=1 -b lineage-24.0 https://github.com/LineageOS/android_kernel_xiaomi_sm8450
cd android_kernel_xiaomi_sm8450 && git fetch --depth=1 origin eff4b40407a1b6f1b1ab84554cbb540bcb495175
git checkout FETCH_HEAD
rsync -a --exclude=.git ./ <本仓库>/ && cd <本仓库> && git add -A
```

## 2. 为什么只 import 成一个提交（不是 dash 那种真实历史）

dash 之所以要真历史，是因为它要做 **Xiaomi dash-w-oss + ACK 6.6.89 + ACK 6.6.118**
三方合并，合并基底本身就是一个真实的 commit，历史是合并的副产品。

marble 这里只有一个上游修订，没有要合的东西：真历史不但帮不上忙，浅拉取进来的
Linux 1.2M commit 还会把仓库撑到几个 GB（dash 的 README 里记了同一个取舍）。
所以这里 import 成一个提交，provenance 全写在提交信息 + 本文里。需要真历史时按需挂：

```bash
git remote add lineage https://github.com/LineageOS/android_kernel_xiaomi_sm8450
git fetch lineage lineage-24.0     # 之后 git log/blame 就能越过 import 点
```

## 3. 上游更新时怎么重做

```bash
# 1) 拿新的 lineage-24.0（或某个 tag），先看它相对我们基底改了什么
git remote add lineage https://github.com/LineageOS/android_kernel_xiaomi_sm8450
git fetch lineage lineage-24.0
git log --oneline eff4b40407a1..lineage/lineage-24.0 | head -50
git diff --stat eff4b40407a1..lineage/lineage-24.0 | tail -5

# 2) 判断我们的两条 delta 还在不在（在就别动，不在才重新打）
git show lineage/lineage-24.0:include/linux/sched.h      | grep -n ANDROID_KABI_RESERVE
git show lineage/lineage-24.0:include/linux/sched/user.h | grep -n ANDROID_KABI

# 3) 换基底（保持"delta 是 delta"的形状：基底提交换掉，两条 delta 提交重放）
git checkout -b bump lineage/lineage-24.0
git cherry-pick 4da795e            # kABI padding（可能因为上下文变了要手工调）
git checkout main -- .github .gitignore arch/arm64/configs/marble_gki.fragment README.md docs
git add -A && git commit
```

几个必然要重新确认的点：

- **kABI padding 的上下文**：`ANDROID_KABI_RESERVE(3..5)` / `KABI_USE(1)` 那几行的位置
  可能会变，`git cherry-pick` 冲突时按「字段进预留位」的语义解，别把结构体顺序改了。
- **`CONFIG_LTO_CLANG_FULL=y` 还在不在 `gki_defconfig`**：`verify-tree.sh` 拿它当
  "这确实是上游文件"的指纹；如果上游哪天自己换成 THIN，这条断言要跟着改。
- **vendor 配置链有没有变**：`gen-config.sh` 硬编码了
  `waipio_GKI → xiaomi_GKI → marble_GKI → debugfs`，上游增删 fragment 要同步。
- **工具链**：ROM stock 内核换 clang 版本时，`CLANG_URL` 必须跟着换（CFI/BTI 只兼容
  同一 release），见 [version-pins.md](version-pins.md)。

## 4. 我们改了什么（相对 import 提交）

```bash
git log --oneline 08a23c3..HEAD
git diff --stat 08a23c3..HEAD -- . ':!.github'   # 内核源码层面的改动只有 2 个文件
```

- `include/linux/sched.h`、`include/linux/sched/user.h`：DroidSpaces kABI padding
  （来自 Droidspaces-OSS `GKI/below-kernel-6.12/001…_6_7_8.patch` + `002…5.10…patch`，
  原样应用，fuzz 0）
- `arch/arm64/configs/marble_gki.fragment` + `.github/` + `docs/` + `README.md`
- **`gki_defconfig` 一个字节都没改**（`verify-tree.sh` 断言），这是我们和上游之间
  唯一需要保持的契约：以后 rebase 永远不在这儿冲突。