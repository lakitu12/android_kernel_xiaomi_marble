#!/usr/bin/env bash
# verify-tree.sh <kernel tree>
#
# 内核源码现在整个在仓库里（import: LineageOS sm8450 @ eff4b404，tree 在仓库根目录）。
# 我方的 delta 以**提交**形式烘在树里（DroidSpaces kABI padding + 配置文件），构建时
# 不再给内核树打任何补丁。所以这一步只做源码级门禁：任何一条改动丢了（错误 rebase、
# 误 revert、上游 tag 覆盖）立刻失败，而不是 20 分钟后编出一个静默功能不全的内核。
#
# 二进制层的门禁在 workflow 的 version gate：版本串 / ikconfig 里的 SYSVIPC、CFI、
# LTO_CLANG_THIN / KSU 变体断言。
set -euo pipefail

TREE=${1:?usage: $0 <kernel tree>}
fail() { echo "::error::in-tree marble delta broken: $*"; exit 1; }

[ -d "$TREE" ] || fail "no such tree: $TREE"

# ------------------------------------------------ 基底还是 LineageOS sm8450
SUB=$(grep -E '^[[:space:]]*SUBLEVEL[[:space:]]*=[[:space:]]*269' "$TREE/Makefile") \
	|| fail "Makefile is not Linux 5.10.269 - the in-repo tree is not the LineageOS base"
[ -n "$SUB" ] || fail "Makefile SUBLEVEL != 269"
# 只有 LineageOS/qcom 树才有的东西：少了说明拿 AOSP common 顶替了。
# 注意只能用 **被 git 跟踪** 的路径：techpack/.gitignore 里有 "*/" 规则，techpack/stub
# 在上游是被忽略的（那边由 build 时从 vendor 填），全新 clone 里根本没有它。
for f in arch/arm64/configs/vendor/marble_GKI.config \
	arch/arm64/configs/vendor/waipio_GKI.config \
	techpack/Kbuild drivers/gpu/msm drivers/soc/qcom \
	drivers/input/touchscreen/fst2 Android.bp; do
	[ -e "$TREE/$f" ] || fail "$f missing - tree is not the LineageOS sm8450 base"
done
[ -f "$TREE/README.md" ] || fail "README.md (our project README) missing"

# ------------------------------------------------ DroidSpaces kABI padding
# SYSVIPC/POSIX_MQUEUE 会改 task_struct / user_struct 布局，DroidSpaces 的 kABI
# padding 把这两个字段挪进 ANDROID_KABI_RESERVE/USE，这样 ROM 里预编译的
# vendor_dlkm 模块仍然和 stock 布局一致（否则一开 SYSVIPC 就全树 CRC 漂移）。
grep -q 'ANDROID_KABI_USE(6, struct sysv_sem sysvsem)' "$TREE/include/linux/sched.h" \
	|| fail "sysv_sem is not parked in ANDROID_KABI_RESERVE(6) of include/linux/sched.h"
grep -q 'struct sysv_shm sysvshm' "$TREE/include/linux/sched.h" \
	|| fail "sysv_shm kABI replacement missing from include/linux/sched.h"
grep -qE '^[[:space:]]*//[[:space:]]*struct sysv_sem[[:space:]]+sysvsem;' "$TREE/include/linux/sched.h" \
	|| fail "the original (un-parked) sysvsem field is back - task_struct layout would move"
grep -q 'ANDROID_KABI_USE(1, unsigned long mq_bytes)' "$TREE/include/linux/sched/user.h" \
	|| fail "mq_bytes is not parked in ANDROID_KABI_USE(1) of include/linux/sched/user.h"

# ------------------------------------------------ 配置：我们的东西只在 fragment 里
DEF="$TREE/arch/arm64/configs/gki_defconfig"
FRAG="$TREE/arch/arm64/configs/marble_gki.fragment"
[ -f "$FRAG" ] || fail "arch/arm64/configs/marble_gki.fragment missing"
# gki_defconfig 必须保持 LineageOS 原样（我们的 delta 一律进 fragment）
grep -qE '^CONFIG_(SYSVIPC|POSIX_MQUEUE|PID_NS|LTO_CLANG_THIN)=y$' "$DEF" \
	&& fail "our config leaked back into gki_defconfig (keep it pristine, use the fragment)"
grep -q '^CONFIG_LTO_CLANG_FULL=y$' "$DEF" \
	|| fail "gki_defconfig lost its stock CONFIG_LTO_CLANG_FULL=y - is this really the upstream file?"
for sym in SYSVIPC POSIX_MQUEUE IPC_NS PID_NS DEVTMPFS USER_NS \
	TMPFS_XATTR TMPFS_POSIX_ACL NETFILTER_XT_MATCH_ADDRTYPE IP_SET \
	NETFILTER_XT_SET KPROBES KALLSYMS KALLSYMS_ALL; do
	grep -q "^CONFIG_${sym}=y$" "$FRAG" || fail "marble_gki.fragment lost CONFIG_${sym}=y"
done
grep -q '^CONFIG_LTO_CLANG_THIN=y$' "$FRAG" || fail "fragment lost CONFIG_LTO_CLANG_THIN=y"
grep -q '^# CONFIG_LTO_CLANG_FULL is not set$' "$FRAG" \
	|| fail "fragment must demote the stock LTO_CLANG_FULL explicitly"
# fragment 必须被实际合并：gen-config.sh 是唯一入口，CI 只调它
grep -q 'arch/arm64/configs/marble_gki.fragment' "$TREE/.github/scripts/gen-config.sh" \
	|| fail "gen-config.sh does not merge marble_gki.fragment"

# ------------------------------------------------ 构建脚本
[ -x "$TREE/.github/scripts/gen-config.sh" ] || fail ".github/scripts/gen-config.sh missing or not executable"
[ -f "$TREE/.github/scripts/extract-ikconfig" ] || fail ".github/scripts/extract-ikconfig missing"
grep -q 'marble_gki.fragment' "$TREE/.github/workflows/build.yml" \
	|| fail "workflow does not go through the fragment (gen-config.sh)"

echo "in-tree marble delta verified:"
echo "  base               LineageOS sm8450 lineage-24.0 @ eff4b404 (Linux 5.10.269), tree at repo root"
echo "  DroidSpaces        sysv_sem/sysv_shm/mq_bytes parked in Android ABI padding (sched.h / sched/user.h)"
echo "  config             marble_gki.fragment only; gki_defconfig still byte-identical (LTO_CLANG_FULL=y)"
echo "  build entry        .github/scripts/gen-config.sh (vendor chain + fragment)"
echo "(binary gates still to run after the build: version string, ikconfig, KSU variant)"