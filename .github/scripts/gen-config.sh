#!/usr/bin/env bash
# gen-config.sh <tree> <outdir> [localversion-suffix]
#
# 生成 marble 的 .config。仓库里的树是 LineageOS 5.10.269，构建配置由两部分组成：
#
#   1) LineageOS 自己的链（CI 以前内联做的，现在搬到这里，本地/CI 同一份）：
#        gki_defconfig -> vendor/waipio_GKI.config -> xiaomi_GKI.config
#                      -> marble_GKI.config -> debugfs.config
#   2) 我们自己的 arch/arm64/configs/marble_gki.fragment（DroidSpaces / KSU / LTO）
#
# gki_defconfig 一个字节都不改，所以上游更新时永远不冲突（verify-tree.sh 断言）。
#
# 第三个参数会写进树里的 .scmversion（被 .gitignore 的 ".*" 规则忽略，属构建产物），
# 它短路 scripts/setlocalversion 的 git 逻辑，让版本串稳定成
#   5.10.269-gki<第一个参数>           例：5.10.269-gki-droidspaces-lakitu
# （-gki 来自 vendor/waipio_GKI.config 的 CONFIG_LOCALVERSION）
#
# 需要 clang 在 PATH 里：HAS_LTO_CLANG 只有在 LLVM=1 + LLVM_IAS=1 且 ND/AR 是 llvm
# 的时候才是 y，否则 LTO_CLANG_THIN 这个 choice 成员根本不可选（会静默退回 LTO_NONE）。
set -euo pipefail

TREE=${1:?usage: $0 <kernel tree> <out dir> [localversion-suffix]}
OUT=${2:?usage: $0 <kernel tree> <out dir> [localversion-suffix]}
SUFFIX=${3-}

[ -d "$TREE" ] || { echo "::error::no such tree: $TREE"; exit 1; }
mkdir -p "$OUT"

MK=(make -C "$TREE" O="$OUT" ARCH=arm64 TARGET_PRODUCT=marble LLVM=1 LLVM_IAS=1)

if [ -n "$SUFFIX" ]; then
	# 不能带空格：setlocalversion 是 cat 出来直接拼的
	case "$SUFFIX" in
	-*) : ;;
	*) SUFFIX="-$SUFFIX" ;;
	esac
	printf '%s' "$SUFFIX" >"$TREE/.scmversion"
	echo "localversion: $(cat "$TREE/.scmversion")"
fi

cp "$TREE/arch/arm64/configs/gki_defconfig" "$OUT/.config"
"${MK[@]}" olddefconfig >/dev/null

for frag in waipio_GKI xiaomi_GKI marble_GKI debugfs; do
	f="$TREE/arch/arm64/configs/vendor/$frag.config"
	[ -f "$f" ] || { echo "::error::vendor fragment missing: $f"; exit 1; }
	echo "=== merge vendor/$frag.config ==="
	"$TREE/scripts/kconfig/merge_config.sh" -m -O "$OUT" "$OUT/.config" "$f" >/dev/null
	"${MK[@]}" olddefconfig >/dev/null
done

OURS="$TREE/arch/arm64/configs/marble_gki.fragment"
[ -f "$OURS" ] || { echo "::error::marble_gki.fragment missing"; exit 1; }
echo "=== merge arch/arm64/configs/marble_gki.fragment ==="
"$TREE/scripts/kconfig/merge_config.sh" -m -O "$OUT" "$OUT/.config" "$OURS" >/dev/null
"${MK[@]}" olddefconfig >/dev/null

# 合并完立刻自检：跌回 LTO_NONE 或者丢一条 DroidSpaces 配置都是静默失败，
# 编 20 分钟才发现没有意义。
fail() { echo "::error::$*"; exit 1; }
grep -q '^CONFIG_LTO_CLANG_THIN=y$' "$OUT/.config" || fail "LTO_CLANG_THIN did not land (clang/LLVM=1 present? HAS_LTO_CLANG=y?)"
grep -q '^CONFIG_CFI_CLANG=y$' "$OUT/.config" || fail "CFI_CLANG lost - vendor modules would BTI-panic"
grep -q '^CONFIG_SYSVIPC=y$' "$OUT/.config" || fail "SYSVIPC did not land"
grep -q '^CONFIG_POSIX_MQUEUE=y$' "$OUT/.config" || fail "POSIX_MQUEUE did not land"
grep -q '^CONFIG_PID_NS=y$' "$OUT/.config" || fail "PID_NS did not land"
grep -q '^CONFIG_KALLSYMS_ALL=y$' "$OUT/.config" || fail "KALLSYMS_ALL did not land"
echo "config OK: $(grep -E '^CONFIG_(LTO_CLANG_THIN|CFI_CLANG|SYSVIPC|POSIX_MQUEUE)=' "$OUT/.config" | tr '\n' ' ')"