# check_axios_vuln.ps1
# axios の悪意あるバージョン (1.14.1, 0.30.4) がインストールされていないかチェックするスクリプト
# 参考: https://www.stepsecurity.io/blog/axios-compromised-on-npm-malicious-versions-drop-remote-access-trojan

param(
    [string]$Dir = ".",
    [switch]$ScanAll,
    [switch]$Help
)

$MaliciousVersions = @("1.14.1", "0.30.4")
$MaliciousDep = "plain-crypto-js"
$script:Found = $false

function Write-Danger { param([string]$Msg) Write-Host "[!] 危険: $Msg" -ForegroundColor Red }
function Write-Warning2 { param([string]$Msg) Write-Host "[!] 警告: $Msg" -ForegroundColor Yellow }
function Write-Safe { param([string]$Msg) Write-Host "[OK] $Msg" -ForegroundColor Green }

if ($Help) {
    Write-Host "使い方: .\check_axios_vuln.ps1 [オプション]"
    Write-Host "  -Dir <path>   チェック対象ディレクトリを指定 (デフォルト: カレントディレクトリ)"
    Write-Host "  -ScanAll      ユーザープロファイル配下を全スキャン"
    Write-Host "  -Help         ヘルプを表示"
    exit 0
}

Write-Host "=== axios 脆弱性チェッカー ==="
Write-Host "対象: axios@1.14.1, axios@0.30.4 (悪意あるRAT入りバージョン)"
Write-Host "関連パッケージ: plain-crypto-js@4.2.1"
Write-Host "-------------------------------------------"

# 1. プロジェクトの node_modules をチェック
function Test-Project {
    param([string]$TargetDir)

    Write-Host ""
    Write-Host "--- プロジェクトのチェック ($TargetDir) ---"

    $pkgJson = Join-Path $TargetDir "node_modules\axios\package.json"
    if (Test-Path $pkgJson) {
        $pkg = Get-Content $pkgJson -Raw | ConvertFrom-Json
        $version = $pkg.version
        if ($MaliciousVersions -contains $version) {
            Write-Danger "$TargetDir に悪意あるバージョン axios@$version が見つかりました"
            $script:Found = $true
        } else {
            Write-Safe "$TargetDir`: axios@$version (安全)"
        }
    }

    $depDir = Join-Path $TargetDir "node_modules\$MaliciousDep"
    if (Test-Path $depDir) {
        Write-Danger "$TargetDir に悪意ある依存関係 '$MaliciousDep' が見つかりました"
        $script:Found = $true
    }
}

# 2. npm グローバルインストールをチェック
function Test-NpmGlobal {
    Write-Host ""
    Write-Host "--- npm グローバルパッケージのチェック ---"

    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npmCmd) {
        Write-Host "[SKIP] npm が見つかりません"
        return
    }

    $globalDir = (npm root -g 2>$null).Trim()
    if (-not $globalDir -or -not (Test-Path $globalDir)) {
        Write-Host "[SKIP] npm グローバルディレクトリが見つかりません"
        return
    }

    $axisPkg = Join-Path $globalDir "axios\package.json"
    if (Test-Path $axisPkg) {
        $pkg = Get-Content $axisPkg -Raw | ConvertFrom-Json
        $version = $pkg.version
        if ($MaliciousVersions -contains $version) {
            Write-Danger "グローバルに悪意あるバージョン axios@$version がインストールされています"
            $script:Found = $true
        } else {
            Write-Safe "グローバル: axios@$version (安全)"
        }
    } else {
        Write-Safe "グローバルに axios はインストールされていません"
    }

    $globalDep = Join-Path $globalDir $MaliciousDep
    if (Test-Path $globalDep) {
        Write-Danger "グローバルに悪意ある依存関係 '$MaliciousDep' が見つかりました"
        $script:Found = $true
    }
}

# 3. npm キャッシュをチェック
function Test-NpmCache {
    Write-Host ""
    Write-Host "--- npm キャッシュのチェック ---"

    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npmCmd) { return }

    $cacheDir = (npm config get cache 2>$null).Trim()
    if (-not $cacheDir -or -not (Test-Path $cacheDir)) { return }

    foreach ($ver in $MaliciousVersions) {
        $matches = Get-ChildItem -Path $cacheDir -Recurse -Filter "axios-$ver.tgz" -ErrorAction SilentlyContinue
        if ($matches) {
            Write-Warning2 "npm キャッシュに axios@$ver が残っています"
            Write-Host "    削除するには: npm cache clean --force"
            $script:Found = $true
        }
    }

    $depMatches = Get-ChildItem -Path $cacheDir -Recurse -Directory -Filter $MaliciousDep -ErrorAction SilentlyContinue
    if ($depMatches) {
        Write-Warning2 "npm キャッシュに '$MaliciousDep' が残っています"
        $script:Found = $true
    }
}

# 4. ロックファイルのチェック
function Test-Lockfiles {
    param([string]$TargetDir)

    Write-Host ""
    Write-Host "--- ロックファイルのチェック ($TargetDir) ---"

    $lockfiles = @("package-lock.json", "yarn.lock", "pnpm-lock.yaml")

    foreach ($lockfile in $lockfiles) {
        $path = Join-Path $TargetDir $lockfile
        if (Test-Path $path) {
            $content = Get-Content $path -Raw
            foreach ($ver in $MaliciousVersions) {
                if ($content -match "axios.*$ver") {
                    Write-Danger "$lockfile に axios@$ver への参照が見つかりました"
                    $script:Found = $true
                }
            }
            if ($content -match $MaliciousDep) {
                Write-Danger "$lockfile に '$MaliciousDep' への参照が見つかりました"
                $script:Found = $true
            }
        }
    }
}

# 5. システム全体をスキャン（オプション）
function Search-System {
    Write-Host ""
    Write-Host "--- システム全体のスキャン (ユーザープロファイル配下) ---"
    Write-Host "    ※ 時間がかかる場合があります..."

    $userProfile = $env:USERPROFILE
    $axiosPkgs = Get-ChildItem -Path $userProfile -Recurse -Depth 10 -Filter "package.json" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "node_modules[\\/]axios[\\/]package\.json$" }

    foreach ($pkgFile in $axiosPkgs) {
        $pkg = Get-Content $pkgFile.FullName -Raw | ConvertFrom-Json
        $version = $pkg.version
        $projectDir = Split-Path (Split-Path (Split-Path $pkgFile.FullName))
        if ($MaliciousVersions -contains $version) {
            Write-Danger "$projectDir に axios@$version が見つかりました"
            $script:Found = $true
        }
    }

    $depDirs = Get-ChildItem -Path $userProfile -Recurse -Depth 10 -Directory -Filter $MaliciousDep -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "node_modules" }

    foreach ($d in $depDirs) {
        Write-Danger "'$MaliciousDep' が見つかりました: $($d.FullName)"
        $script:Found = $true
    }
}

# メイン処理
Test-Project -TargetDir $Dir
Test-Lockfiles -TargetDir $Dir
Test-NpmGlobal
Test-NpmCache

if ($ScanAll) {
    Search-System
}

Write-Host ""
Write-Host "==========================================="
if ($script:Found) {
    Write-Host "[!] 悪意あるバージョンが検出されました！" -ForegroundColor Red
    Write-Host ""
    Write-Host "対処手順:"
    Write-Host "  1. 該当プロジェクトで安全なバージョンに更新:"
    Write-Host "     npm install axios@1.14.0  (1.x系の場合)"
    Write-Host "     npm install axios@0.30.3  (0.x系の場合)"
    Write-Host "  2. node_modules を削除して再インストール:"
    Write-Host "     Remove-Item -Recurse -Force node_modules; npm install"
    Write-Host "  3. npm キャッシュをクリア:"
    Write-Host "     npm cache clean --force"
    Write-Host "  4. システムがRATに感染していないか確認:"
    Write-Host "     - タスクマネージャーで不審なプロセスを確認"
    Write-Host "     - netstat -ano で不審なネットワーク接続を確認"
    exit 1
} else {
    Write-Safe "悪意ある axios バージョンは検出されませんでした"
    exit 0
}
