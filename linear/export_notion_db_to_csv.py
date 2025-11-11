import os
import csv
import time
from typing import Any, Dict, List
import requests
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")
OUTPUT_CSV = os.getenv("OUTPUT_CSV", "notion_export.csv")
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))  # 1~100
REQUEST_INTERVAL = float(os.getenv("REQUEST_INTERVAL", "0.35"))  # リクエスト間隔（秒）
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))  # 429エラー時の最大リトライ回数
INCLUDE_PAGE_CONTENT = os.getenv("INCLUDE_PAGE_CONTENT", "true").lower() == "true"  # ページ本文を取得するか
PRIORITY_PROPERTY = os.getenv("PRIORITY_PROPERTY", "Priority")  # 優先度プロパティ名
PRIORITY_VALUES = os.getenv("PRIORITY_VALUES", "高,中")  # フィルタする優先度の値（カンマ区切り）

BASE = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def rate_limited_request(method: str, url: str, **kwargs) -> requests.Response:
    """
    レート制限を考慮したリクエスト実行。
    429 Too Many Requests エラー時は自動リトライ。
    """
    for attempt in range(MAX_RETRIES):
        # リクエスト間隔を守る
        time.sleep(REQUEST_INTERVAL)

        try:
            if method.upper() == "GET":
                resp = requests.get(url, **kwargs)
            elif method.upper() == "POST":
                resp = requests.post(url, **kwargs)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            # 429エラーの場合
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 1))
                wait_time = retry_after if attempt == 0 else (2 ** attempt)
                print(f"Rate limit hit (429). Waiting {wait_time} seconds... (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(wait_time)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.HTTPError as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait_time = 2 ** attempt
            print(f"HTTP error occurred: {e}. Retrying in {wait_time} seconds...")
            time.sleep(wait_time)

    raise RuntimeError(f"Failed after {MAX_RETRIES} attempts")

def get_database_properties(db_id: str) -> Dict[str, Dict[str, Any]]:
    """データベースのスキーマ（プロパティ定定義）を取得。"""
    url = f"{BASE}/databases/{db_id}"
    resp = rate_limited_request("GET", url, headers=HEADERS, timeout=30)
    data = resp.json()
    # {"properties": {"Name": {"type": "title", ...}, "Description": {"type": "rich_text", ...}, ...}}
    return data.get("properties", {})

def rich_text_to_plain(rt_list: List[Dict[str, Any]]) -> str:
    """rich_text配列をplain_text結合に変換。"""
    parts = []
    for rt in rt_list or []:
        # 公式仕様: rich_textオブジェクトは plain_text を含む
        parts.append(rt.get("plain_text", ""))
    return "".join(parts)

def block_to_text(block: Dict[str, Any]) -> str:
    """ブロックオブジェクトをプレーンテキストに変換。"""
    btype = block.get("type")
    if not btype:
        return ""

    block_data = block.get(btype, {})

    # paragraph
    if btype == "paragraph":
        return rich_text_to_plain(block_data.get("rich_text", []))

    # heading_1, heading_2, heading_3
    if btype in ("heading_1", "heading_2", "heading_3"):
        level = int(btype.split("_")[1])
        text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"{'#' * level} {text}"

    # bulleted_list_item
    if btype == "bulleted_list_item":
        text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"• {text}"

    # numbered_list_item
    if btype == "numbered_list_item":
        text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"1. {text}"

    # to_do
    if btype == "to_do":
        checked = block_data.get("checked", False)
        text = rich_text_to_plain(block_data.get("rich_text", []))
        checkbox = "☑" if checked else "☐"
        return f"{checkbox} {text}"

    # quote
    if btype == "quote":
        text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"> {text}"

    # code
    if btype == "code":
        language = block_data.get("language", "")
        code_text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"```{language}\n{code_text}\n```"

    # callout
    if btype == "callout":
        icon = block_data.get("icon", {})
        emoji = icon.get("emoji", "📌") if icon.get("type") == "emoji" else "📌"
        text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"{emoji} {text}"

    # toggle
    if btype == "toggle":
        text = rich_text_to_plain(block_data.get("rich_text", []))
        return f"▸ {text}"

    # divider
    if btype == "divider":
        return "---"

    # その他のrich_textを持つブロック
    if "rich_text" in block_data:
        return rich_text_to_plain(block_data.get("rich_text", []))

    return ""

def blocks_to_text(blocks: List[Dict[str, Any]]) -> str:
    """ブロックリストをプレーンテキストに変換（10,000文字制限）。"""
    parts = []
    total_length = 0
    max_length = 10000

    for block in blocks:
        text = block_to_text(block)
        if text:
            if total_length + len(text) > max_length:
                parts.append(f"... (truncated at {max_length} chars)")
                break
            parts.append(text)
            total_length += len(text)

    return "\n\n".join(parts)

def files_to_text(files_list: List[Dict[str, Any]]) -> str:
    """files配列を name|url のセミコロン連結に変換。"""
    out = []
    for f in files_list or []:
        name = f.get("name", "")
        if f.get("type") == "external":
            url = f.get("external", {}).get("url", "")
        else:
            url = f.get("file", {}).get("url", "")
        if url:
            out.append(f"{name}|{url}")
        else:
            out.append(name)
    return ";".join(out)

def people_to_text(people_list: List[Dict[str, Any]]) -> str:
    """people配列を 名前(or メール) をセミコロン連結。"""
    out = []
    for p in people_list or []:
        name = p.get("name")
        email = p.get("person", {}).get("email")
        out.append(name or email or "")
    return ";".join([x for x in out if x])

def relation_to_text(rel_list: List[Dict[str, Any]]) -> str:
    """relation配列を関連ページIDのセミコロン連結に簡易変換。"""
    return ";".join([r.get("id", "") for r in (rel_list or []) if r.get("id")])

def rollup_to_text(rollup: Dict[str, Any]) -> str:
    """rollup値を簡易に文字列へ（代表的ケースのみ）。"""
    if not rollup:
        return ""
    rtype = rollup.get("type")
    if rtype == "array":
        # 中の型に応じてテキスト化
        items = []
        for item in rollup.get("array", []):
            itype = item.get("type")
            if itype == "rich_text":
                items.append(rich_text_to_plain(item.get("rich_text", [])))
            elif itype == "title":
                items.append(rich_text_to_plain(item.get("title", [])))
            elif itype == "number":
                items.append(str(item.get("number", "")))
            elif itype == "people":
                items.append(people_to_text(item.get("people", [])))
            elif itype == "date":
                d = item.get("date") or {}
                items.append(d.get("start") or "")
            elif itype == "relation":
                items.append(relation_to_text(item.get("relation", [])))
            else:
                items.append(str(item.get(itype, "")))
        return ";".join([x for x in items if x != ""])
    elif rtype == "number":
        return str(rollup.get("number", ""))
    elif rtype == "date":
        d = rollup.get("date") or {}
        return d.get("start") or ""
    else:
        return str(rollup.get(rtype, ""))

def property_value_to_text(prop: Dict[str, Any]) -> str:
    """ページの各Property ValueをCSV用の文字列に正規化。"""
    ptype = prop.get("type")
    if ptype == "title":
        return rich_text_to_plain(prop.get("title", []))
    if ptype == "rich_text":
        return rich_text_to_plain(prop.get("rich_text", []))
    if ptype == "number":
        v = prop.get("number")
        return "" if v is None else str(v)
    if ptype == "select":
        s = prop.get("select") or {}
        return s.get("name") or ""
    if ptype == "multi_select":
        return ";".join([x.get("name", "") for x in (prop.get("multi_select") or [])])
    if ptype == "date":
        d = prop.get("date") or {}
        return d.get("start") or ""
    if ptype == "people":
        return people_to_text(prop.get("people", []))
    if ptype == "files":
        return files_to_text(prop.get("files", []))
    if ptype == "checkbox":
        return "TRUE" if prop.get("checkbox") else "FALSE"
    if ptype == "url":
        return prop.get("url") or ""
    if ptype == "email":
        return prop.get("email") or ""
    if ptype == "phone_number":
        return prop.get("phone_number") or ""
    if ptype == "relation":
        return relation_to_text(prop.get("relation", []))
    if ptype == "rollup":
        return rollup_to_text(prop.get("rollup", {}))
    if ptype == "formula":
        f = prop.get("formula") or {}
        ftype = f.get("type")
        return "" if ftype is None else str(f.get(ftype, ""))
    if ptype in ("created_time", "last_edited_time"):
        return prop.get(ptype) or ""
    if ptype in ("created_by", "last_edited_by"):
        # peopleと同じ形
        person = prop.get(ptype) or {}
        return person.get("name") or ""
    # 未知型は素直に文字列化
    return str(prop.get(ptype, ""))

def get_page_blocks(page_id: str) -> List[Dict[str, Any]]:
    """ページのブロック（本文）をページネーションで取得。"""
    url = f"{BASE}/blocks/{page_id}/children"
    all_blocks = []
    next_cursor = None

    try:
        while True:
            params = {"page_size": 100}
            if next_cursor:
                params["start_cursor"] = next_cursor

            resp = rate_limited_request("GET", url, headers=HEADERS, params=params, timeout=30)
            data = resp.json()
            all_blocks.extend(data.get("results", []))

            if not data.get("has_more"):
                break
            next_cursor = data.get("next_cursor")

        return all_blocks

    except Exception as e:
        print(f"Warning: Failed to get blocks for page {page_id}: {e}")
        return []

def query_all_pages(db_id: str) -> List[Dict[str, Any]]:
    """データベース全ページをページネーションで取得（優先度フィルタ付き）。"""
    url = f"{BASE}/databases/{db_id}/query"
    all_results = []
    payload: Dict[str, Any] = {"page_size": PAGE_SIZE}

    # 優先度フィルタを構築
    if PRIORITY_VALUES:
        priority_list = [v.strip() for v in PRIORITY_VALUES.split(",") if v.strip()]
        if priority_list:
            # 複数の優先度をORで結合
            filter_conditions = [
                {
                    "property": PRIORITY_PROPERTY,
                    "select": {"equals": priority_val}
                }
                for priority_val in priority_list
            ]

            if len(filter_conditions) == 1:
                payload["filter"] = filter_conditions[0]
            else:
                payload["filter"] = {"or": filter_conditions}

    next_cursor = None

    while True:
        if next_cursor:
            payload["start_cursor"] = next_cursor
        resp = rate_limited_request("POST", url, headers=HEADERS, json=payload, timeout=60)
        data = resp.json()
        all_results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        next_cursor = data.get("next_cursor")
    return all_results

def main():
    if not NOTION_TOKEN or not DATABASE_ID:
        raise SystemExit("NOTION_TOKEN または DATABASE_ID が未設定です (.env を確認)")

    # 1) スキーマ取得（列名の順序を作る）
    print("Fetching database schema...")
    props = get_database_properties(DATABASE_ID)
    # プロパティ名（表示順は任意。必要なら並び替え規則を実装）
    property_names = list(props.keys())

    # 推奨: よく使う補助列を先頭に
    extra_cols = ["Page ID", "Page URL", "Created time (page)", "Last edited time (page)"]
    headers = extra_cols + property_names

    # ページ本文を含める場合は列を追加
    if INCLUDE_PAGE_CONTENT:
        headers.append("Page Content")

    # 2) 全ページ取得
    if PRIORITY_VALUES:
        print(f"Fetching pages with {PRIORITY_PROPERTY} = {PRIORITY_VALUES}...")
    else:
        print("Fetching all pages (no filter)...")
    pages = query_all_pages(DATABASE_ID)
    total = len(pages)
    print(f"Found {total} pages. Starting export...")

    # 3) CSVに書き出し
    error_count = 0
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for idx, pg in enumerate(pages, 1):
            page_id = pg.get("id", "")
            print(f"Processing page {idx}/{total} ({page_id})")

            row = {}
            row["Page ID"] = page_id
            row["Page URL"] = pg.get("url", "")
            row["Created time (page)"] = pg.get("created_time", "")
            row["Last edited time (page)"] = pg.get("last_edited_time", "")

            # プロパティ値を平坦化
            pvals: Dict[str, Any] = pg.get("properties", {})
            for name in property_names:
                row[name] = property_value_to_text(pvals.get(name, {}))

            # ページ本文を取得
            if INCLUDE_PAGE_CONTENT:
                try:
                    blocks = get_page_blocks(page_id)
                    row["Page Content"] = blocks_to_text(blocks)
                except Exception as e:
                    print(f"  Warning: Failed to get content for page {page_id}: {e}")
                    row["Page Content"] = ""
                    error_count += 1

            writer.writerow(row)

    print(f"\nDone! Wrote {total} rows to {OUTPUT_CSV}")
    if error_count > 0:
        print(f"Warning: {error_count} pages had errors retrieving content.")

if __name__ == "__main__":
    main()
