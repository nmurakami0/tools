// export_account_customprops_csv.js
(function () {
  const fs = require("fs");

  // ====== 設定（--eval で上書き可）======
  const COLL = globalThis.COLL || "account";
  const OUT = globalThis.OUT || "./export.csv";
  const QUERY = globalThis.QUERY || {};

  // ====== utils ======
  function csvEscape(v) {
    if (v === null || v === undefined) return "";
    const s = String(v);
    if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function getProp(doc, physicalName) {
    const arr = doc.customProperties || [];
    return arr.find((p) => p && p.physicalName === physicalName) || null;
  }

  // 文字列値を取得
  function getStringValue(doc, physicalName) {
    const p = getProp(doc, physicalName);
    return p?.value?.stringValue ?? "";
  }

  // ID値を取得（kind参照用）
  function getIdValue(doc, physicalName) {
    const p = getProp(doc, physicalName);
    return p?.value?._id ?? "";
  }

  // 数値を取得
  function getLongValue(doc, physicalName) {
    const p = getProp(doc, physicalName);
    return p?.value?.longValue ?? "";
  }

  // 日付を取得（YYYY-MM-DD形式で返す）
  function getDateValue(doc, physicalName) {
    const p = getProp(doc, physicalName);
    const d = p?.value?.localDateValue;
    if (!d) return "";
    let date;
    if (d instanceof Date) {
      date = d;
    } else if (d.$date) {
      date = new Date(d.$date);
    } else {
      return String(d);
    }
    // YYYY-MM-DD形式で返す（UTCベース）
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, "0");
    const day = String(date.getUTCDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  // URL値を取得
  function getUrlValue(doc, physicalName) {
    const p = getProp(doc, physicalName);
    return p?.value?.urlValue ?? "";
  }

  // 配列値を取得（valuesNames をカンマ区切りで結合）
  function getValuesNames(doc, physicalName) {
    const p = getProp(doc, physicalName);
    const names = p?.valuesNames || [];
    return names.join(",");
  }

  // ====== header（全customProperties対応）======
  const header = [
    "id",
    "customer_number", // stringValue
    "head_office_number", // stringValue
    "customer_segment", // _id (kind参照)
    "oasys_segment", // _id (kind参照)
    "biz_type_2", // stringValue
    "biz_type_3", // stringValue
    "it_staff", // stringValue
    "pc_count", // longValue
    "employees", // longValue
    "capital", // longValue
    "revenue", // longValue
    "founded_date", // localDateValue
    "main_bank", // stringValue
    "g_map", // urlValue
    "main_sales", // stringValue
    "os_sales", // stringValue
    "bs_sales", // stringValue
    "ec_sales", // stringValue
    "tom_sales", // stringValue
  ];
  fs.writeFileSync(OUT, header.map(csvEscape).join(",") + "\n", "utf8");

  // ====== export ======
  const cursor = db
    .getCollection(COLL)
    .find(QUERY, { _id: 1, customProperties: 1 })
    .noCursorTimeout();

  let count = 0;
  try {
    while (cursor.hasNext()) {
      const doc = cursor.next();
      const row = [
        doc._id,
        getStringValue(doc, "customer_number"),
        getStringValue(doc, "head_office_number"),
        getIdValue(doc, "customer_segment"),
        getIdValue(doc, "oasys_segment"),
        getStringValue(doc, "biz_type_2"),
        getStringValue(doc, "biz_type_3"),
        getStringValue(doc, "it_staff"),
        getLongValue(doc, "pc_count"),
        getLongValue(doc, "employees"),
        getLongValue(doc, "capital"),
        getLongValue(doc, "revenue"),
        getDateValue(doc, "founded_date"),
        getStringValue(doc, "main_bank"),
        getUrlValue(doc, "g_map"),
        getStringValue(doc, "main_sales"),
        getStringValue(doc, "os_sales"),
        getStringValue(doc, "bs_sales"),
        getStringValue(doc, "ec_sales"),
        getStringValue(doc, "tom_sales"),
      ];
      fs.appendFileSync(OUT, row.map(csvEscape).join(",") + "\n", "utf8");
      if (++count % 10000 === 0) print(`exported ${count}`);
    }
  } finally {
    cursor.close();
  }

  print(`done: ${count} rows -> ${OUT}`);
})();
