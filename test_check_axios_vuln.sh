#!/bin/bash
# test_check_axios_vuln.sh
# check_axios_vuln.sh の検出能力を検証するテストスクリプト

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECK_SCRIPT="$SCRIPT_DIR/check_axios_vuln.sh"
TEST_DIR=$(mktemp -d)
PASS=0
FAIL=0

cleanup() {
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

run_test() {
    local name="$1"
    local dir="$2"
    local expect_danger="$3"  # "detect" or "safe"

    output=$("$CHECK_SCRIPT" --dir "$dir" 2>&1)
    has_danger=$(echo "$output" | grep -c "危険")

    if [ "$expect_danger" = "detect" ] && [ "$has_danger" -gt 0 ]; then
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    elif [ "$expect_danger" = "safe" ] && [ "$has_danger" -eq 0 ]; then
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $name"
        echo "        期待: $expect_danger / 検出行数: $has_danger"
        echo "        出力:"
        echo "$output" | sed 's/^/        /'
        FAIL=$((FAIL + 1))
    fi
}

# ダミーの node_modules 構造を作成するヘルパー
make_axios() {
    local base="$1"
    local version="$2"
    mkdir -p "$base/node_modules/axios"
    cat > "$base/node_modules/axios/package.json" <<EOFPKG
{
  "name": "axios",
  "version": "$version"
}
EOFPKG
}

make_plain_crypto() {
    local base="$1"
    mkdir -p "$base/node_modules/plain-crypto-js"
    cat > "$base/node_modules/plain-crypto-js/package.json" <<EOFPKG
{
  "name": "plain-crypto-js",
  "version": "4.2.1"
}
EOFPKG
}

make_lockfile() {
    local base="$1"
    local filename="$2"
    local content="$3"
    echo "$content" > "$base/$filename"
}

echo "=== check_axios_vuln.sh 検証テスト ==="
echo ""

# --- テスト1: 悪意ある axios@1.14.1 ---
echo "[テスト1] axios@1.14.1 の検出"
t1="$TEST_DIR/t1"
mkdir -p "$t1"
make_axios "$t1" "1.14.1"
run_test "axios@1.14.1 を検出できる" "$t1" "detect"

# --- テスト2: 悪意ある axios@0.30.4 ---
echo "[テスト2] axios@0.30.4 の検出"
t2="$TEST_DIR/t2"
mkdir -p "$t2"
make_axios "$t2" "0.30.4"
run_test "axios@0.30.4 を検出できる" "$t2" "detect"

# --- テスト3: 安全な axios@1.14.0 ---
echo "[テスト3] axios@1.14.0 は安全"
t3="$TEST_DIR/t3"
mkdir -p "$t3"
make_axios "$t3" "1.14.0"
run_test "axios@1.14.0 を安全と判定" "$t3" "safe"

# --- テスト4: 安全な axios@1.7.9 ---
echo "[テスト4] axios@1.7.9 は安全"
t4="$TEST_DIR/t4"
mkdir -p "$t4"
make_axios "$t4" "1.7.9"
run_test "axios@1.7.9 を安全と判定" "$t4" "safe"

# --- テスト5: plain-crypto-js の検出 ---
echo "[テスト5] plain-crypto-js の検出"
t5="$TEST_DIR/t5"
mkdir -p "$t5"
make_axios "$t5" "1.14.0"
make_plain_crypto "$t5"
run_test "plain-crypto-js を検出できる" "$t5" "detect"

# --- テスト6: ロックファイルに悪意あるバージョンの参照 ---
echo "[テスト6] package-lock.json 内の参照検出"
t6="$TEST_DIR/t6"
mkdir -p "$t6"
make_lockfile "$t6" "package-lock.json" '{
  "packages": {
    "node_modules/axios": {
      "version": "1.14.1",
      "resolved": "https://registry.npmjs.org/axios/-/axios-1.14.1.tgz"
    }
  }
}'
run_test "ロックファイル内の axios@1.14.1 参照を検出" "$t6" "detect"

# --- テスト7: ロックファイルに plain-crypto-js ---
echo "[テスト7] yarn.lock 内の plain-crypto-js 検出"
t7="$TEST_DIR/t7"
mkdir -p "$t7"
make_lockfile "$t7" "yarn.lock" 'plain-crypto-js@^4.2.1:
  version "4.2.1"
  resolved "https://registry.npmjs.org/plain-crypto-js/-/plain-crypto-js-4.2.1.tgz"'
run_test "yarn.lock 内の plain-crypto-js を検出" "$t7" "detect"

# --- テスト8: axios がインストールされていない ---
echo "[テスト8] axios 未インストール"
t8="$TEST_DIR/t8"
mkdir -p "$t8"
run_test "axios なしで安全と判定" "$t8" "safe"

# --- 結果 ---
echo ""
echo "==========================================="
echo "結果: $PASS 件成功 / $FAIL 件失敗 (全 $((PASS + FAIL)) 件)"
if [ "$FAIL" -eq 0 ]; then
    echo "全テスト合格!"
else
    echo "失敗したテストがあります"
fi
echo "==========================================="

exit "$FAIL"
