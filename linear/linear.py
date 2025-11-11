import json
import os

import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- 設定 ---
# Linear Personal API Keyを.envファイルから読み込み
LINEAR_API_KEY = os.getenv("LINEAR_API_KEY")
if not LINEAR_API_KEY:
    raise ValueError("LINEAR_API_KEY が .env ファイルに設定されていません")

# Linear GraphQLのエンドポイント
LINEAR_API_URL = "https://api.linear.app/graphql"

# teamIdとprojectIdを取得するためのGraphQLクエリ
# 'id'がUUID形式のteamId/projectIdです。
GRAPHQL_QUERY = """
query {
  teams {
    nodes {
      id
      name
      key
    }
  }
  projects {
    nodes {
      id
      name
      state
      teams {
        nodes {
          name
          key
        }
      }
    }
  }
}
"""
# --- 実行 ---

# HTTPリクエストのヘッダーを設定
# Note: Linear APIではAPI keyを使う場合、Bearerプレフィックスは不要
headers = {
    "Authorization": LINEAR_API_KEY,
    "Content-Type": "application/json"
}

# リクエストのペイロード（データ）
payload = {
    "query": GRAPHQL_QUERY
}

try:
    # APIにPOSTリクエストを送信
    response = requests.post(LINEAR_API_URL, headers=headers, json=payload)

    # HTTPステータスコードを確認
    response.raise_for_status()

    # JSONレスポンスを取得
    data = response.json()

    print("✅ チームIDとプロジェクトIDの取得に成功しました:\n")

    # チーム情報のパースと表示
    teams = data.get("data", {}).get("teams", {}).get("nodes", [])

    if teams:
        print("=" * 80)
        print("【チーム情報】")
        print("=" * 80)
        print(f"{'Team Name':<20} | {'Key':<5} | Team ID (UUID)")
        print("-" * 80)
        for team in teams:
            team_id = team.get('id', 'N/A')
            team_name = team.get('name', 'N/A')
            team_key = team.get('key', 'N/A')
            print(f"{team_name:<20} | {team_key:<5} | {team_id}")
        print("=" * 80)
        print()
    else:
        print("⚠️  チーム情報が見つかりませんでした。\n")

    # プロジェクト情報のパースと表示
    projects = data.get("data", {}).get("projects", {}).get("nodes", [])

    if projects:
        print("=" * 80)
        print("【プロジェクト情報】")
        print("=" * 80)
        print(f"{'Project Name':<30} | {'State':<12} | {'Team':<10} | Project ID (UUID)")
        print("-" * 80)
        for project in projects:
            project_id = project.get('id', 'N/A')
            project_name = project.get('name', 'N/A')
            project_state = project.get('state', 'N/A')

            # プロジェクトに紐づくチーム名を取得
            project_teams = project.get('teams', {}).get('nodes', [])
            team_names = ', '.join([t.get('key', 'N/A') for t in project_teams]) if project_teams else 'N/A'

            print(f"{project_name:<30} | {project_state:<12} | {team_names:<10} | {project_id}")
        print("=" * 80)
    else:
        print("⚠️  プロジェクト情報が見つかりませんでした。")

except requests.exceptions.HTTPError as errh:
    print(f"HTTPエラーが発生しました: {errh}")
    if response.status_code == 401:
        print("🔑 認証エラー: APIキーが間違っているか、有効期限が切れている可能性があります。")
    # デバッグ: レスポンス内容を表示
    try:
        error_data = response.json()
        print(f"エラー詳細: {json.dumps(error_data, indent=2, ensure_ascii=False)}")
    except:
        print(f"レスポンステキスト: {response.text}")
except requests.exceptions.ConnectionError as errc:
    print(f"接続エラーが発生しました: {errc}")
except requests.exceptions.Timeout as errt:
    print(f"タイムアウトエラーが発生しました: {errt}")
except requests.exceptions.RequestException as err:
    print(f"リクエスト送信中に予期せぬエラーが発生しました: {err}")
except json.JSONDecodeError:
    print("レスポンスの解析エラー: 無効なJSONが返されました。")
except Exception as e:
    print(f"予期せぬエラー: {e}")