#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Auto-detect which CSV has customer_number etc. and validate against original.

Inputs:
  --a: one of the split CSVs (Mongo or PG)
  --b: the other split CSV (PG or Mongo)
  --orig: original CSV (must have customer_number)

Process:
  1) Join A and B by id (normalized)
  2) Determine which side provides customer_number (prefer existing columns)
  3) Ignore rows with missing customer_number
  4) Join with original by customer_number
  5) Compare available columns vs original, output mismatches
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

# =========================
# Normalizers
# =========================

def normalize_int_string(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return None
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    s = re.sub(r"[^\d]", "", s)
    return s if s else None


def normalize_tel(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = re.sub(r"[^\d]", "", s)
    return s if s else None


def normalize_zip(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = s.replace("-", "").replace(" ", "")
    s = re.sub(r"[^\d]", "", s)
    return s if s else None


def normalize_text(x) -> str | None:
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s)
    # バックスラッシュのエスケープを統一（\\ → \）
    s = s.replace("\\\\", "\\")
    return s


def normalize_numeric_truncate(x) -> str | None:
    """数値を整数に切り捨てて文字列で返す（4.8 → "4", 4.4 → "4"）"""
    if x is None:
        return None
    if isinstance(x, float) and pd.isna(x):
        return None
    s = str(x).strip()
    if s == "" or s.lower() == "nan":
        return None
    # カンマやスペースを除去
    s = s.replace(",", "").replace(" ", "")
    try:
        return str(int(float(s)))
    except ValueError:
        return None


# =========================
# Helpers
# =========================

def find_customer_number_col(df: pd.DataFrame) -> str | None:
    # candidate names
    candidates = [
        "customer_number",
        "customerNumber",
        "customer_no",
        "customerNo",
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def write_columns(outdir: Path, name: str, df: pd.DataFrame) -> None:
    (outdir / f"{name}_columns.txt").write_text("\n".join(df.columns.tolist()), encoding="utf-8")


def pick_source_col(joined: pd.DataFrame, base: str) -> str | None:
    """
    In joined df, a column might appear as:
      - base (if unique)
      - base_a / base_b (if collision)
    Prefer base, else check suffixed ones.
    """
    if base in joined.columns:
        return base
    if f"{base}_a" in joined.columns:
        return f"{base}_a"
    if f"{base}_b" in joined.columns:
        return f"{base}_b"
    return None


# =========================
# Main
# =========================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", required=True, help="Split CSV A (Mongo or PG)")
    parser.add_argument("--b", required=True, help="Split CSV B (PG or Mongo)")
    parser.add_argument("--orig", required=True, help="Original CSV (must contain customer_number)")
    parser.add_argument("--outdir", default="csv_validation_out")
    parser.add_argument("--limit-samples", type=int, default=100)
    args = parser.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    a_df = pd.read_csv(args.a, dtype=str, keep_default_na=False)
    b_df = pd.read_csv(args.b, dtype=str, keep_default_na=False)
    orig_df = pd.read_csv(args.orig, dtype=str, keep_default_na=False)

    write_columns(outdir, "a", a_df)
    write_columns(outdir, "b", b_df)
    write_columns(outdir, "orig", orig_df)

    if "id" not in a_df.columns:
        raise ValueError("CSV A must contain 'id' column.")
    if "id" not in b_df.columns:
        raise ValueError("CSV B must contain 'id' column.")
    if "customer_number" not in orig_df.columns:
        raise ValueError("Original CSV must contain 'customer_number' column.")

    # Normalize join keys
    a_df["id_norm"] = a_df["id"].map(normalize_int_string)
    b_df["id_norm"] = b_df["id"].map(normalize_int_string)
    orig_df["customer_number_norm"] = orig_df["customer_number"].map(normalize_int_string)

    # Dedup by id_norm
    a_u = a_df.drop_duplicates(subset=["id_norm"], keep="first")
    b_u = b_df.drop_duplicates(subset=["id_norm"], keep="first")

    # Join by id_norm (outer to see missing on either side)
    joined = pd.merge(
        a_u,
        b_u,
        on="id_norm",
        how="outer",
        suffixes=("_a", "_b"),
        indicator="ab_join_status",
    )
    joined.to_csv(outdir / "joined_a_b_by_id.csv", index=False)

    # Decide customer_number column source (A or B)
    a_cust = find_customer_number_col(a_df)
    b_cust = find_customer_number_col(b_df)

    # In joined dataframe, customer_number columns become either customer_number_a / customer_number_b
    cust_col_in_joined = None
    cust_source = None

    # Prefer the side that actually has customer_number in its original df
    if a_cust and f"{a_cust}_a" in joined.columns:
        cust_col_in_joined = f"{a_cust}_a"
        cust_source = "A"
    elif b_cust and f"{b_cust}_b" in joined.columns:
        cust_col_in_joined = f"{b_cust}_b"
        cust_source = "B"
    else:
        # Maybe it didn't collide and is plain 'customer_number'
        if a_cust and a_cust in joined.columns:
            cust_col_in_joined = a_cust
            cust_source = "A"
        elif b_cust and b_cust in joined.columns:
            cust_col_in_joined = b_cust
            cust_source = "B"

    # If still none, we cannot join with original
    if cust_col_in_joined is None:
        summary = pd.DataFrame([{
            "a_rows": len(a_df),
            "b_rows": len(b_df),
            "joined_rows_by_id": len(joined),
            "customer_number_available": False,
            "note": "Neither CSV A nor B has a customer_number column. Cannot validate against original.",
        }])
        summary.to_csv(outdir / "summary_counts.csv", index=False)
        print("=== Validation Summary ===")
        print(summary.to_string(index=False))
        print(f"Output dir: {outdir.resolve()}")
        print("See a_columns.txt / b_columns.txt to confirm available columns.")
        return

    # Normalize customer_number from joined
    joined["customer_number_norm"] = joined[cust_col_in_joined].map(normalize_int_string)

    # Ignore rows without customer_number
    joined_valid = joined[joined["customer_number_norm"].notna()].copy()

    # Join with original by customer_number_norm
    orig_u = orig_df.drop_duplicates(subset=["customer_number_norm"], keep="first")

    merged = pd.merge(
        joined_valid,
        orig_u,
        on="customer_number_norm",
        how="left",
        suffixes=("", "_orig"),
        indicator="orig_join_status",
    )
    merged.to_csv(outdir / "joined_all.csv", index=False)

    # Missing in original
    merged[merged["orig_join_status"] != "both"][[
        "id_norm",
        cust_col_in_joined,
        "customer_number_norm",
        "orig_join_status",
    ]].to_csv(outdir / "missing_in_original_by_customer_number.csv", index=False)

    # Compare columns (only those that exist)
    desired_compare = [
        "name",
        "address",
        "tel",
        "zip_code",
        "biz_type_2",
        "biz_type_3",
        "head_office_number",
        "customer_segment",
        "oasys_segment",
        "it_staff",
        "pc_count",
        "employees",
        "capital",
        "revenue",
        "founded_date",
        "main_bank",
        "g_map",
        "main_sales",
        "os_sales",
        "bs_sales",
        "ec_sales",
        "tom_sales",
    ]

    mismatch_mask = pd.Series(False, index=merged.index)

    for base in desired_compare:
        left_col = pick_source_col(merged, base)  # base or base_a/base_b
        if left_col is None:
            continue

        right_col = f"{base}_orig" if f"{base}_orig" in merged.columns else base
        if right_col not in merged.columns:
            continue

        # フィールドタイプに応じた正規化
        numeric_fields = ["pc_count", "employees", "capital", "revenue"]
        id_fields = ["head_office_number"]
        date_fields = ["founded_date"]

        # customer_segment: ID→テキスト変換マッピング
        customer_segment_map = {
            "7": "情報",
            "8": "顧客",
            "9": "取引先",
            "10": "その他",
            "11": "得意先顧客",
            "12": "代理店顧客",
            "13": "顧客別法人",
            "14": "代番別",
        }

        # oasys_segment: ID→テキスト変換マッピング
        oasys_segment_map = {
            "72": "カルテ",
            "73": "プレミアム",
        }

        if base == "tel":
            l = merged[left_col].map(normalize_tel)
            r = merged[right_col].map(normalize_tel)
        elif base == "zip_code":
            l = merged[left_col].map(normalize_zip)
            r = merged[right_col].map(normalize_zip)
        elif base == "customer_segment":
            # 左側(A/B)はIDなのでテキストに変換、右側(orig)はそのまま
            l = merged[left_col].map(lambda x: customer_segment_map.get(normalize_int_string(x), normalize_int_string(x)))
            r = merged[right_col].map(normalize_text)
        elif base == "oasys_segment":
            # 左側(A/B)はIDなのでテキストに変換、右側(orig)はそのまま
            l = merged[left_col].map(lambda x: oasys_segment_map.get(normalize_int_string(x), normalize_int_string(x)))
            r = merged[right_col].map(normalize_text)
        elif base in numeric_fields:
            # 数値は整数に切り捨てて比較（4.8 → 4）
            l = merged[left_col].map(normalize_numeric_truncate)
            r = merged[right_col].map(normalize_numeric_truncate)
        elif base in id_fields:
            l = merged[left_col].map(normalize_int_string)
            r = merged[right_col].map(normalize_int_string)
        elif base in date_fields:
            # 日付は YYYY-MM-DD 形式で比較（先頭10文字）
            l = merged[left_col].map(lambda x: str(x)[:10] if pd.notna(x) and str(x).strip() else None)
            r = merged[right_col].map(lambda x: str(x)[:10] if pd.notna(x) and str(x).strip() else None)
        else:
            l = merged[left_col].map(normalize_text)
            r = merged[right_col].map(normalize_text)

        diff = (l != r) & ~(pd.isna(l) & pd.isna(r))
        merged[f"mismatch__{base}"] = diff
        mismatch_mask |= diff

    mismatches = merged[mismatch_mask].copy()
    mismatches.to_csv(outdir / "mismatches_full.csv", index=False)
    mismatches.head(args.limit_samples).to_csv(outdir / "mismatch_samples.csv", index=False)

    # Summary
    summary = pd.DataFrame([{
        "a_rows": len(a_df),
        "b_rows": len(b_df),
        "joined_rows_by_id": len(joined),
        "customer_number_source": cust_source,
        "customer_number_column_used": cust_col_in_joined,
        "rows_with_customer_number": len(joined_valid),
        "orig_joined_by_customer_number": int((merged["orig_join_status"] == "both").sum()),
        "missing_in_original": int((merged["orig_join_status"] != "both").sum()),
        "mismatched_rows": int(len(mismatches)),
    }])
    summary.to_csv(outdir / "summary_counts.csv", index=False)

    print("=== Validation Summary ===")
    print(summary.to_string(index=False))
    print(f"Output dir: {outdir.resolve()}")


if __name__ == "__main__":
    main()
