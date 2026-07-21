#!/bin/bash
# check_axios_vuln.sh
# axios の悪意あるバージョン (1.14.1, 0.30.4) がインストールされていないかチェックするスクリプト
# 参考: https://www.stepsecurity.io/blog/axios-compromised-on-npm-malicious-versions-drop-remote-access-trojan

MALICIOUS_AXIOS_VERSIONS=("1.14.1" "0.30.4")
MALICIOUS_DEP="plain-crypto-js"
found=0

echo "=== axios 脆弱性チェッカー ==="
echo "対象: axios@1.14.1, axios@0.30.4 (悪意あるRAT入りバージョン)"
echo "関連パッケージ: plain-crypto-js@4.2.1"
echo "-------------------------------------------"

# 1. カレントディレクトリの node_modules をチェック
check_project() {
    local dir="$1"
    local pkg="$dir/node_modules/axios/package.json"

    if [ -f "$pkg" ]; then
        version=$(grep -o '"version": *"[^"]*"' "$pkg" | head -1 | grep -o '[0-9][^"]*')
        for mal_ver in "${MALICIOUS_AXIOS_VERSIONS[@]}"; do
            if [ "$version" = "$mal_ver" ]; then
                echo "[!] 危険: $dir に悪意あるバージョン axios@$version が見つかりました"
                found=1
            fi
        done
        if [ "$found" -eq 0 ] 2>/dev/null; then
            echo "[OK] $dir: axios@$version (安全)"
        fi
    fi

    # plain-crypto-js の存在チェック
    if [ -d "$dir/node_modules/$MALICIOUS_DEP" ]; then
        echo "[!] 危険: $dir に悪意ある依存関係 '$MALICIOUS_DEP' が見つかりました"
        found=1
    fi
}

# 2. npm グローバルインストールをチェック
check_npm_global() {
    echo ""
    echo "--- npm グローバルパッケージのチェック ---"
    if command -v npm &>/dev/null; then
        global_dir=$(npm root -g 2>/dev/null)
        if [ -d "$global_dir/axios" ]; then
            version=$(grep -o '"version": *"[^"]*"' "$global_dir/axios/package.json" | head -1 | grep -o '[0-9][^"]*')
            for mal_ver in "${MALICIOUS_AXIOS_VERSIONS[@]}"; do
                if [ "$version" = "$mal_ver" ]; then
                    echo "[!] 危険: グローバルに悪意あるバージョン axios@$version がインストールされています"
                    found=1
                fi
            done
            if [ "$found" -eq 0 ] 2>/dev/null; then
                echo "[OK] グローバル: axios@$version (安全)"
            fi
        else
            echo "[OK] グローバルに axios はインストールされていません"
        fi

        if [ -d "$global_dir/$MALICIOUS_DEP" ]; then
            echo "[!] 危険: グローバルに悪意ある依存関係 '$MALICIOUS_DEP' が見つかりました"
            found=1
        fi
    else
        echo "[SKIP] npm が見つかりません"
    fi
}

# 3. npm cache をチェック
check_npm_cache() {
    echo ""
    echo "--- npm キャッシュのチェック ---"
    if command -v npm &>/dev/null; then
        cache_dir=$(npm config get cache 2>/dev/null)
        if [ -n "$cache_dir" ] && [ -d "$cache_dir" ]; then
            for mal_ver in "${MALICIOUS_AXIOS_VERSIONS[@]}"; do
                if find "$cache_dir" -path "*/axios/-/axios-${mal_ver}.tgz" 2>/dev/null | grep -q .; then
                    echo "[!] 警告: npm キャッシュに axios@$mal_ver が残っています"
                    echo "    削除するには: npm cache clean --force"
                    found=1
                fi
            done
            if find "$cache_dir" -path "*/$MALICIOUS_DEP/*" 2>/dev/null | grep -q .; then
                echo "[!] 警告: npm キャッシュに '$MALICIOUS_DEP' が残っています"
                found=1
            fi
        fi
    fi
}

# 4. lock ファイルのチェック
check_lockfiles() {
    local dir="$1"
    echo ""
    echo "--- ロックファイルのチェック ($dir) ---"

    for lockfile in "package-lock.json" "yarn.lock" "pnpm-lock.yaml"; do
        local path="$dir/$lockfile"
        if [ -f "$path" ]; then
            for mal_ver in "${MALICIOUS_AXIOS_VERSIONS[@]}"; do
                if grep -q "axios.*${mal_ver}" "$path" 2>/dev/null; then
                    echo "[!] 危険: $lockfile に axios@$mal_ver への参照が見つかりました"
                    found=1
                fi
            done
            if grep -q "$MALICIOUS_DEP" "$path" 2>/dev/null; then
                echo "[!] 危険: $lockfile に '$MALICIOUS_DEP' への参照が見つかりました"
                found=1
            fi
        fi
    done
}

# 5. システム全体をスキャン（オプション）
scan_system() {
    echo ""
    echo "--- システム全体のスキャン (ホームディレクトリ配下) ---"
    echo "    ※ 時間がかかる場合があります..."

    while IFS= read -r pkg_json; do
        dir=$(dirname "$(dirname "$pkg_json")")
        version=$(grep -o '"version": *"[^"]*"' "$pkg_json" | head -1 | grep -o '[0-9][^"]*')
        for mal_ver in "${MALICIOUS_AXIOS_VERSIONS[@]}"; do
            if [ "$version" = "$mal_ver" ]; then
                echo "[!] 危険: $dir に axios@$version が見つかりました"
                found=1
            fi
        done
    done < <(find "$HOME" -path "*/node_modules/axios/package.json" -maxdepth 10 2>/dev/null)

    while IFS= read -r dep_dir; do
        echo "[!] 危険: '$MALICIOUS_DEP' が見つかりました: $dep_dir"
        found=1
    done < <(find "$HOME" -path "*/node_modules/$MALICIOUS_DEP" -type d -maxdepth 10 2>/dev/null)
}

# メイン処理
main() {
    local scan_all=false
    local target_dir="."

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --scan-all) scan_all=true; shift ;;
            --dir) target_dir="$2"; shift 2 ;;
            -h|--help)
                echo "使い方: $0 [オプション]"
                echo "  --dir <path>  チェック対象ディレクトリを指定 (デフォルト: カレントディレクトリ)"
                echo "  --scan-all    ホームディレクトリ配下を全スキャン"
                echo "  -h, --help    ヘルプを表示"
                exit 0
                ;;
            *) echo "不明なオプション: $1"; exit 1 ;;
        esac
    done

    echo ""
    echo "--- プロジェクトのチェック ($target_dir) ---"
    check_project "$target_dir"
    check_lockfiles "$target_dir"
    check_npm_global
    check_npm_cache

    if [ "$scan_all" = true ]; then
        scan_system
    fi

    echo ""
    echo "==========================================="
    if [ "$found" -eq 1 ]; then
        echo "[!] 悪意あるバージョンが検出されました！"
        echo ""
        echo "対処手順:"
        echo "  1. 該当プロジェクトで安全なバージョンに更新:"
        echo "     npm install axios@1.14.0  (1.x系の場合)"
        echo "     npm install axios@0.30.3  (0.x系の場合)"
        echo "  2. node_modules を削除して再インストール:"
        echo "     rm -rf node_modules && npm install"
        echo "  3. npm キャッシュをクリア:"
        echo "     npm cache clean --force"
        echo "  4. システムがRATに感染していないか確認"
        echo "     - 不審なプロセスの確認: ps aux | grep -i crypto"
        echo "     - 不審なネットワーク接続の確認: lsof -i -nP"
        exit 1
    else
        echo "[OK] 悪意ある axios バージョンは検出されませんでした"
        exit 0
    fi
}

main "$@"
