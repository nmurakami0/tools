#!/usr/bin/env python3
"""
Convert Notion CSV export to Linear CSV import format.

This script transforms a Notion task export CSV into the format required
by Linear's CSV import feature.
"""

import csv
import json
import os
import sys
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# Priority mapping: Japanese to English
PRIORITY_MAP = {
    "低": "Low",
    "中": "Medium",
    "高": "High",
    "": "No priority",
}

# Load assignee mapping from environment variable
# Falls back to default mapping if not set in .env
_assignee_map_str = os.getenv('ASSIGNEE_MAP')
if _assignee_map_str:
    try:
        ASSIGNEE_MAP = json.loads(_assignee_map_str)
    except json.JSONDecodeError:
        print("⚠️  Warning: Failed to parse ASSIGNEE_MAP from .env, using default mapping")
        ASSIGNEE_MAP = {
            "堀江莉貴": "horie@elw.co.jp",
            "hide": "h.yoshida@elw.co.jp",
            "yuya takayanagi": "takayanagi@elw.co.jp",
            "長谷川雄一": "yuichi@elw.co.jp",
            "坂本仁美": "h.sakamoto@elw.co.jp",
            "濵田佑梨": "hamada@elw.co.jp",
            "山口舞子": "m.yamaguchi@elw.co.jp",
            "k-yamaguchi": "yamaguchi@elw.co.jp",
            "Naoya Murakami": "murakami@elw.co.jp",
            "西岡大輔": "nishioka@elw.co.jp",
        }
else:
    # Default mapping (fallback if .env is not configured)
    ASSIGNEE_MAP = {
        "堀江莉貴": "horie@elw.co.jp",
        "hide": "h.yoshida@elw.co.jp",
        "yuya takayanagi": "takayanagi@elw.co.jp",
        "長谷川雄一": "yuichi@elw.co.jp",
        "坂本仁美": "h.sakamoto@elw.co.jp",
        "濵田佑梨": "hamada@elw.co.jp",
        "山口舞子": "m.yamaguchi@elw.co.jp",
        "k-yamaguchi": "yamaguchi@elw.co.jp",
        "Naoya Murakami": "murakami@elw.co.jp",
        "西岡大輔": "nishioka@elw.co.jp",
    }


def parse_json_field(field_value: str) -> Optional[dict]:
    """Parse a JSON field from the CSV, handling single quotes."""
    if not field_value or field_value.strip() == "":
        return None

    try:
        # Replace single quotes with double quotes for valid JSON
        json_str = field_value.replace("'", '"')
        return json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None


def convert_iso_to_gmt(iso_date: str) -> str:
    """
    Convert ISO 8601 date to Linear's GMT format.

    From: 2024-08-26T02:38:00.000Z
    To: Mon Oct 27 2025 10:16:55 GMT+0000 (GMT)
    """
    if not iso_date or iso_date.strip() == "":
        return ""

    try:
        # Parse ISO 8601 format
        dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))

        # Format to Linear's GMT format
        # Day name, Month name DD YYYY HH:MM:SS GMT+0000 (GMT)
        formatted = dt.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (GMT)")
        return formatted
    except (ValueError, AttributeError):
        return ""


def extract_status_name(status_json: str) -> str:
    """Extract the status name from the JSON status field."""
    status_dict = parse_json_field(status_json)
    if status_dict and 'name' in status_dict:
        return status_dict['name']
    return ""


def map_priority(priority_jp: str) -> str:
    """Map Japanese priority to English Linear format."""
    return PRIORITY_MAP.get(priority_jp, "No priority")


def should_have_completed_date(status: str) -> bool:
    """Check if the task should have a completed date based on status."""
    completed_statuses = {"完了", "done"}
    return status.lower() in {s.lower() for s in completed_statuses}


def convert_assignee(assignee_str: str) -> str:
    """
    Convert assignee name to email address.

    If multiple assignees (separated by ;), take the first one.
    If not in mapping, return empty string.

    Args:
        assignee_str: Raw assignee string from Notion (may contain multiple names)

    Returns:
        Email address of the first assignee, or empty string if not found
    """
    if not assignee_str or assignee_str.strip() == "":
        return ""

    # Handle multiple assignees - take first one
    first_assignee = assignee_str.split(';')[0].strip()

    # Look up in mapping, return empty if not found
    return ASSIGNEE_MAP.get(first_assignee, "")


def convert_labels(labels_str: str) -> str:
    """
    Convert semicolon-separated labels to Linear format.

    From: FE;BE
    To: "FE", "BE"

    Args:
        labels_str: Semicolon-separated labels from Notion

    Returns:
        Comma-separated quoted labels for Linear
    """
    if not labels_str or labels_str.strip() == "":
        return ""

    # Split by semicolon and strip whitespace
    labels = [label.strip() for label in labels_str.split(';')]

    # Filter out empty labels
    labels = [label for label in labels if label]

    # Join with comma+space (CSV writer will handle quoting)
    return ', '.join(labels)


def convert_release_labels(release_str: str, prefix: str = "release:") -> str:
    """
    Convert semicolon-separated release values to Linear label format with prefix.

    From: v1.2.3;v1.3.0
    To: "release:v1.2.3", "release:v1.3.0"

    Args:
        release_str: Semicolon-separated release values from Notion
        prefix: Prefix to add to each release value (default: "release:")

    Returns:
        Comma-separated quoted labels for Linear with prefix
    """
    if not release_str or release_str.strip() == "" or release_str.strip() == "未定":
        return ""

    # Split by semicolon and strip whitespace
    releases = [release.strip() for release in release_str.split(';')]

    # Filter out empty releases and "未定"
    releases = [release for release in releases if release and release != "未定"]

    # Add prefix (CSV writer will handle quoting)
    return ', '.join(f'{prefix}{release}' for release in releases)


def convert_notion_to_linear(input_file: str, output_file: str):
    """
    Convert Notion CSV export to Linear CSV import format.

    Args:
        input_file: Path to the Notion export CSV
        output_file: Path to save the Linear format CSV
    """
    linear_rows = []

    # Read Notion CSV
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Extract and transform fields
            title = row.get('タスク名', '').strip()

            # Skip rows without a title
            if not title:
                continue

            description = row.get('Page Content', '').strip()

            # Priority mapping
            priority_jp = row.get('優先度', '').strip()
            priority = map_priority(priority_jp)

            # Status extraction from JSON
            status_json = row.get('ステータス', '')
            status = extract_status_name(status_json)

            # Assignee conversion (name to email)
            assignee_raw = row.get('担当者', '').strip()
            assignee = convert_assignee(assignee_raw)

            # Date conversions
            created_iso = row.get('作成日時', '')
            created = convert_iso_to_gmt(created_iso)

            # Completed date - only set if status is "完了"
            completed = ""
            if should_have_completed_date(status):
                last_edited_iso = row.get('Last edited time (page)', '')
                completed = convert_iso_to_gmt(last_edited_iso)

            # Labels conversion (semicolon-separated to quoted comma-separated)
            labels_raw = row.get('対象', '').strip()
            labels = convert_labels(labels_raw)

            # Release labels conversion with prefix
            release_raw = row.get('リリース', '').strip()
            release_labels = convert_release_labels(release_raw)

            # Combine labels
            all_labels = labels
            if release_labels:
                if all_labels:
                    all_labels = f"{all_labels}, {release_labels}"
                else:
                    all_labels = release_labels

            # Add from:notion label to all issues
            if all_labels:
                all_labels = f"{all_labels}, from:notion"
            else:
                all_labels = "from:notion"

            # Estimate - not available in Notion data
            estimate = ""

            # Create Linear row
            linear_row = {
                'Title': title,
                'Description': description,
                'Priority': priority,
                'Status': status,
                'Assignee': assignee,
                'Created': created,
                'Completed': completed,
                'Labels': all_labels,
                'Estimate': estimate,
            }

            linear_rows.append(linear_row)

    # Write Linear CSV
    if linear_rows:
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['Title', 'Description', 'Priority', 'Status', 'Assignee',
                         'Created', 'Completed', 'Labels', 'Estimate']
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            writer.writeheader()
            writer.writerows(linear_rows)

        print(f"✓ Converted {len(linear_rows)} tasks")
        print(f"✓ Output written to: {output_file}")
    else:
        print("⚠ No tasks found to convert")


def main():
    """Main entry point for the script."""
    if len(sys.argv) < 2:
        print("Usage: python notion_to_linear.py <input_file> [output_file]")
        print("\nExample:")
        print("  python notion_to_linear.py notion_export.csv")
        print("  python notion_to_linear.py notion_export.csv linear_import.csv")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'linear_import.csv'

    print(f"Converting {input_file} to Linear format...")
    print(f"Output will be saved to: {output_file}\n")

    try:
        convert_notion_to_linear(input_file, output_file)
    except FileNotFoundError:
        print(f"❌ Error: File not found: {input_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
