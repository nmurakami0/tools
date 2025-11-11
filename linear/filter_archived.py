#!/usr/bin/env python3
"""
notion_export.csvからステータスに「アーカイブ」を含む行を除外するスクリプト
"""

import csv
import sys
import argparse
from pathlib import Path


def filter_archived_tasks(input_file: str, output_file: str) -> None:
    """
    CSVファイルからステータスに「アーカイブ」を含む行を除外する

    Args:
        input_file: 入力CSVファイルのパス
        output_file: 出力CSVファイルのパス
    """
    # 入力ファイルの存在チェック
    if not Path(input_file).exists():
        print(f"エラー: 入力ファイル '{input_file}' が見つかりません", file=sys.stderr)
        sys.exit(1)

    filtered_rows = []
    excluded_count = 0
    total_count = 0

    try:
        # CSVファイルを読み込み（UTF-8 BOM対応）
        with open(input_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            # ヘッダーを保存
            fieldnames = reader.fieldnames

            if 'ステータス' not in fieldnames:
                print("エラー: '「ステータス' 列が見つかりません", file=sys.stderr)
                sys.exit(1)

            # 各行を処理
            for row in reader:
                total_count += 1
                status = row.get('ステータス', '')

                # ステータスに「アーカイブ」が含まれているかチェック
                if 'アーカイブ' in status:
                    excluded_count += 1
                else:
                    filtered_rows.append(row)

        # フィルタリング結果を出力
        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(filtered_rows)

        # 結果を表示
        remaining_count = total_count - excluded_count
        print(f"処理完了:")
        print(f"  総行数: {total_count}")
        print(f"  除外された行数（アーカイブを含む）: {excluded_count}")
        print(f"  残った行数: {remaining_count}")
        print(f"  出力ファイル: {output_file}")

    except Exception as e:
        print(f"エラーが発生しました: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description='notion_export.csvからステータスに「アーカイブ」を含む行を除外する'
    )
    parser.add_argument(
        '-i', '--input',
        default='notion_export.csv',
        help='入力CSVファイル（デフォルト: notion_export.csv）'
    )
    parser.add_argument(
        '-o', '--output',
        default='notion_export_filtered.csv',
        help='出力CSVファイル（デフォルト: notion_export_filtered.csv）'
    )

    args = parser.parse_args()

    filter_archived_tasks(args.input, args.output)


if __name__ == '__main__':
    main()
