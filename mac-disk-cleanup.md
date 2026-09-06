# Mac disk cleanup

`mac-disk-cleanup.sh` は隣の `mac_disk_cleanup.py` を起動します。Python 3.9+ の標準ライブラリのみ使用します。macOS 標準 Bash 3.2 対応。実行時は通常ユーザーで、対象を使う開発サーバー・IDE・ビルド・エージェントを終了してください。`sudo` は拒否します。

## 使い方

```bash
# ホームの直下を容量順に確認。削除はしない。
./mac-disk-cleanup.sh

# 大きかった場所を掘り下げる。任意のディレクトリは測定だけで、削除対象にはならない。
./mac-disk-cleanup.sh --overview-root ~/.cache --overview-root ~/Library

# Docker・worktree・古い依存関係・診断ログ・Terraformの候補を確認
./mac-disk-cleanup.sh --no-overview --worktrees --worktree-deps \
  --docker-volumes --agent-logs --terraform

# 上のレポートのIDを選択。同じオプションに --run --select を追加する。
# IDは例。実際に表示された値を使う。複数なら --select を繰り返す。
./mac-disk-cleanup.sh --no-overview --worktrees --worktree-deps \
  --docker-volumes --agent-logs --terraform --run --select volume-xxxxxxxxxxxx

# スキャン範囲を限定（複数指定可）。リポジトリから登録済みworktreeも検出する。
./mac-disk-cleanup.sh --no-overview --worktrees --repo-root ~/projects/src/my-repo
./mac-disk-cleanup.sh --no-overview --terraform --terraform-dir ~/projects/src/my-infra
```

旧版と異なり **`--run` 単独では削除しません**。候補のIDは種類・パスまたはリソースID・識別情報から生成します。選択IDが存在しない場合は、他の選択も含め削除を開始しません。対象が置き換わる、HEADが変わるなどするとIDも変わり、再確認が必要です。実行時のチェックで使用中・確認不能になった候補は残し、終了コード1で報告します。他の選択済み候補は続行します。削除開始後の失敗・timeoutは部分的に削除済みの可能性を明記し、全削除成功や完全保持とは報告しません。

## 判定方針

| 対象 | 候補と削除の条件 |
| --- | --- |
| ホーム、Downloads、Library、`.cache`、AI関連ディレクトリ等 | 容量を測定。大きいという理由だけでは削除しない |
| npm / Gradle / pip / Yarn / Go等の既知キャッシュ | 原則30日以上更新のない子要素。内部の全ファイルも確認し、実行前に`lsof`で利用を検査。再取得・再ビルドが必要になる場合がある |
| uv | 実際の `uv cache dir` に対して公式の `uv cache prune` のみを個別選択。到達不能なキャッシュをuv自身が判定するため日数フィルターは適用しない。uv/uvx実行中・開いているファイルがあれば保護。`--ci`・`--force`・全消去・直接`rm`は使わない |
| Docker image | 全コンテナから未参照、かつ作成から30日以上。通常はdanglingのみ、`--docker-all`でtag付きも候補にする。ID指定、強制削除なし |
| Docker build cache | 明示選択時のみ、30日間使われていないdangling cacheを対象とし、`--keep-build-cache 10GB`を指定。`--all`は使わない。別のbuildx builderを一括巡回しない |
| Docker volume | `--docker-volumes`でのみ候補化。停止中を含む全コンテナから未参照、作成から30日以上、名前ごとに明示選択。実行直前に作成日時・ラベル・参照状態を再検査し、強制削除なし。**未使用でもDB等のデータを含み得る。内容が不要と確認できたvolumeだけ選ぶ** |
| Git worktree | `--worktrees`。main・locked・prunable・現在の作業ディレクトリ・変更あり・未追跡/ignoredファイルあり・submoduleあり・Git操作中を保護。GitHubのmerged PRのhead SHAとローカルHEADの完全一致、マージから30日以上を要求。squash mergeやdetached HEADもSHAで判定する |
| worktreeのnode_modules | `--worktree-deps`。上記のPR照合とGit保護条件を満たすworktreeで、Gitに無視され、追跡ファイルを含まない古い`node_modules`のみ。`.env`など他のignoredファイルは残す。内部symlinkは辿らずリンクを削除。親worktreeや候補自体のsymlinkは拒否 |
| マージ済みworktreeのCompose container | Composeラベルのworking_dirが検証済みworktreeに入ること、そのprojectの**全コンテナ**が停止済みで同じworktreeを指すことを確認。作成から30日以上。container IDごとに選択。書込みレイヤーは失われる。起動中のcontainerを停止しない |
| Claude / Codex | `--agent-logs`で古い`.claude/debug`・`.codex/log`の`.txt`/`.log`ファイルのみ。エージェント起動中は削除しない。会話・sessions・file-history・設定・認証・DB・memories・plugins・runtimes・モデル・ブラウザプロファイルは削除しない |
| Terraform | `--terraform`は有効なlockを読み、pinされていない古いproviderのみ。lock不明/解析不能は保護。実行前に再読込。`--terraform-all`は古いproviders/modulesを対象とし、`terraform init`が必要。`.terraform/terraform.tfstate`・environmentは保護 |
| Trash / Xcode | `--trash` / `--xcode`で古い子要素を候補化。Trash本体を残す。Simulatorの一括削除は行わない |

PR照合は `gh` の認証とネットワークが必要です。現在は `origin` がgithub.comを指すSSH/HTTPS形式に対応し、GitHub Enterpriseや照合不能なPRは保護します。fetch・ブランチ削除・worktree prune・強制removeは行いません。登録が残った消失済みworktreeも保護し、メタデータだけ消して容量が増えたとは報告しません。

DockerはローカルUnix socketのcontextだけを受け付け、`DOCKER_HOST`指定やremote contextは拒否します。contextをコマンドに固定し、daemon IDを削除直前にも確認します。volumeはlocal driverかつ独自mount optionsなしのものに限定し、NFS等は保護します。Dockerが停止中/確認不能、または`--no-docker`の場合、コンテナの参照を確認できないのでworktree・依存関係の削除は行いません。

Composeのproject名やvolume名の接頭辞だけからworktreeを推測しません。複数のworking_dirが同じprojectを共有する場合はcontainer削除候補にしません。containerを先に選択削除した後、再スキャンすると未参照volumeを選べます。containerが既にないvolumeは所属PRを確認できないため、その事実を表示し、必ずvolume単位で選択します。`compose down -v`・`system prune`・`volume prune`は使いません。

## 測定と安全性の限界

- `du`の割当済みサイズを使用。上位20件表示、最大4並列、コマンド/探索ごとの既定タイムアウト30秒。大きなディレクトリは`--timeout 120`や狭い`--overview-root`で再測定できます。権限不足・timeoutは **unknown** であり0ではありません。
- `--no-overview`で再実行時の広範囲測定を省略できます。`--min-age-days 7`などで保持期間を変えられます（1日以上）。候補表示時点では使用中チェック待ちのため、表示された候補すべてが削除可能とは限りません。
- APFS clone・hardlink・snapshot、Dockerの共有レイヤー・sparse VM diskにより、見かけの容量合計と回復容量は一致しません。削除候補の単純合計を回復見込みとして表示せず、実行前後のホスト空き容量差を表示します。並行作業の影響を含みます。Dockerの論理容量減少が即座にMacの空き容量へ反映されない場合もあります。
- ageはmtime基準です。読み取り頻度や将来の必要性は表しません。閉じたアプリが後で必要とするキャッシュは再取得が必要です。実行前チェックはアプリの再起動や競合書込みを原子的には防げません。対象を使う作業を止めて実行してください。`lsof`の警告・失敗・timeoutも削除拒否にします。
- ファイルと親ディレクトリのsymlink、特殊ファイル、別filesystemへの横断を拒否します。Pythonのsymlink耐性のある`rmtree`を使用。任意のパスを削除指定するオプションや`--force`による安全策の迂回はありません。
- 旧版のHomebrew一括cleanup、pnpm store prune、Gradle/browser cacheの無条件全削除を廃止しました。管理ツールの独自参照構造や利用中の環境を、単なる古さ/大きさだけで削除しないためです。

## 検証

```bash
shellcheck mac-disk-cleanup.sh
python3 -m unittest -v test_mac_disk_cleanup
```

テストの削除対象は一時ディレクトリのみ。実Gitのworktree（空白・改行を含むパス、detached、ignoredファイル、locked、隠された変更）と、モックDockerの使用中volume・共有Compose project・remote endpoint・削除失敗などを確認します。

仕様参照: [Git worktree](https://git-scm.com/docs/git-worktree)、[GitHub commitに関連するPR](https://docs.github.com/en/rest/commits/commits#list-pull-requests-associated-with-a-commit)、[Docker builder prune](https://docs.docker.com/reference/cli/docker/builder/prune/)、[Docker volume pruneの意味](https://docs.docker.com/reference/cli/docker/volume/prune/)、[uv cacheの安全性とprune](https://docs.astral.sh/uv/concepts/cache/)。
