"""汎用 日本語対応 PDFビルダー (fpdf2ベース)

Usage:
    from pdf_builder import PDFBuilder

    pdf = PDFBuilder(title="ドキュメント名 v1.0")
    pdf.set_margins(20, 20, 20)
    pdf.title_page(["タイトル行1", "タイトル行2"], meta=[("項目", "値")])
    pdf.add_page()
    pdf.h1("1. セクション")
    pdf.body("本文テキスト")
    pdf.output("output.pdf")
"""

import os
from fpdf import FPDF
from fpdf.enums import TableCellFillMode, TableBordersLayout
from fpdf.fonts import FontFace

# --- フォントパス (Noto Sans CJK JP) ---
FONT_DIR = os.path.expanduser("~/Library/Fonts")
NOTO_REGULAR = f"{FONT_DIR}/NotoSansCJKjp-Regular.otf"
NOTO_BOLD = f"{FONT_DIR}/NotoSansCJKjp-Bold.otf"


class PDFBuilder(FPDF):
    """日本語対応の汎用PDFビルダー。

    サブクラスで色定義 (C_*) をオーバーライドすることでテーマ変更可能。
    """

    # --- 色定義 (サブクラスでオーバーライド可能) ---
    C_PRIMARY = (26, 35, 126)
    C_ACCENT = (13, 71, 161)
    C_LIGHT_BG = (245, 245, 245)
    C_BORDER = (189, 189, 189)
    C_WHITE = (255, 255, 255)
    C_BODY = (33, 33, 33)
    C_H3 = (55, 71, 79)
    C_NOTE = (117, 117, 117)
    C_CODE_BG = (236, 239, 241)

    def __init__(self, title="", footer_text="Confidential"):
        super().__init__()
        self._doc_title = title
        self._footer_text = footer_text
        self.set_auto_page_break(auto=True, margin=20)
        self.add_font("HG", "", NOTO_REGULAR)
        self.add_font("HG", "B", NOTO_BOLD)

    # --- ヘッダー / フッター ---

    def header(self):
        if self.page_no() > 1 and self._doc_title:
            self.set_font("HG", "", 7)
            self.set_text_color(*self.C_NOTE)
            self.cell(0, 5, self._doc_title, align="L")
            self.cell(0, 5, f"p. {self.page_no()}", align="R",
                      new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*self.C_BORDER)
            self.line(self.l_margin, self.get_y(),
                      self.w - self.r_margin, self.get_y())
            self.ln(3)

    def footer(self):
        if self._footer_text:
            self.set_y(-15)
            self.set_font("HG", "", 7)
            self.set_text_color(*self.C_NOTE)
            self.cell(0, 5, self._footer_text, align="C")

    # --- タイトルページ ---

    def title_page(self, title_lines, meta=None):
        """タイトルページを生成する。

        Args:
            title_lines: タイトル行のリスト (例: ["トビラフォン連携", "技術仕様書"])
            meta: メタ情報のリスト (例: [("対象読者", "..."), ("バージョン", "2.0")])
        """
        self.add_page()
        self.ln(40)
        self.set_font("HG", "B", 24)
        self.set_text_color(*self.C_PRIMARY)
        for line in title_lines:
            self.cell(0, 14, line, align="C",
                      new_x="LMARGIN", new_y="NEXT")
        self.ln(5)
        self.set_draw_color(*self.C_PRIMARY)
        self.set_line_width(1.0)
        cx = self.w / 2
        self.line(cx - 40, self.get_y(), cx + 40, self.get_y())
        self.ln(10)

        if meta:
            total_w = self.w - self.l_margin - self.r_margin
            self.set_draw_color(*self.C_BORDER)
            self.set_line_width(0.3)
            for label, value in meta:
                self.set_fill_color(*self.C_ACCENT)
                self.set_text_color(*self.C_WHITE)
                self.set_font("HG", "B", 10)
                self.cell(40, 9, f"  {label}", border=1, fill=True)
                self.set_fill_color(*self.C_LIGHT_BG)
                self.set_text_color(*self.C_BODY)
                self.set_font("HG", "", 10)
                self.cell(total_w - 40, 9, f"  {value}", border=1,
                          fill=True, new_x="LMARGIN", new_y="NEXT")

    # --- セクション見出し ---

    def h1(self, text):
        self.ln(6)
        self.set_font("HG", "B", 16)
        self.set_text_color(*self.C_PRIMARY)
        self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*self.C_PRIMARY)
        self.set_line_width(0.5)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(4)

    def h2(self, text):
        self.ln(3)
        self.set_font("HG", "B", 13)
        self.set_text_color(*self.C_ACCENT)
        self.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    # --- テキスト ---

    def body(self, text, indent=0):
        self.set_font("HG", "", 10)
        self.set_text_color(*self.C_BODY)
        x = self.l_margin + indent
        self.set_x(x)
        self.multi_cell(self.w - self.r_margin - x, 6, text)
        self.ln(1)

    def bold_body(self, text, indent=0):
        self.set_font("HG", "B", 10)
        self.set_text_color(*self.C_BODY)
        x = self.l_margin + indent
        self.set_x(x)
        self.multi_cell(self.w - self.r_margin - x, 6, text)
        self.ln(1)

    def bullet(self, text, indent=8):
        self.set_font("HG", "", 10)
        self.set_text_color(*self.C_BODY)
        x = self.l_margin + indent
        self.set_x(x)
        bw = self.get_string_width("\u2022  ")
        self.cell(bw, 6, "\u2022")
        self.multi_cell(self.w - self.r_margin - x - bw, 6, text)
        self.ln(0.5)

    def numbered(self, num, text, indent=8):
        self.set_font("HG", "", 10)
        self.set_text_color(*self.C_BODY)
        x = self.l_margin + indent
        self.set_x(x)
        ns = f"{num}. "
        nw = self.get_string_width(ns) + 1
        self.cell(nw, 6, ns)
        self.multi_cell(self.w - self.r_margin - x - nw, 6, text)
        self.ln(0.5)

    def checkbox(self, text, indent=8):
        self.set_font("HG", "", 10)
        self.set_text_color(*self.C_BODY)
        x = self.l_margin + indent
        y = self.get_y() + 1
        self.set_draw_color(*self.C_BORDER)
        self.set_line_width(0.3)
        self.rect(x, y, 3.5, 3.5)
        self.set_x(x + 5)
        self.multi_cell(self.w - self.r_margin - x - 5, 6, text)
        self.ln(0.5)

    def code_block(self, text, indent=8):
        self.set_font("HG", "", 9)
        self.set_text_color(*self.C_H3)
        x = self.l_margin + indent
        self.set_fill_color(*self.C_CODE_BG)
        self.set_draw_color(*self.C_BORDER)
        self.set_x(x)
        self.multi_cell(self.w - self.r_margin - x, 6, text,
                        border=1, fill=True)
        self.ln(1)

    # --- テーブル ---

    def spec_table(self, headers, rows, col_widths=None, first_col_bold=False):
        """fpdf2組み込みテーブルで描画。"""
        self.set_font("HG", "", 9)
        self.set_text_color(*self.C_BODY)
        total_w = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            col_widths = [total_w / len(headers)] * len(headers)

        header_style = FontFace(
            emphasis="B", color=self.C_WHITE, fill_color=self.C_ACCENT
        )
        bold_style = FontFace(emphasis="B")

        with self.table(
            borders_layout=TableBordersLayout.SINGLE_TOP_LINE,
            cell_fill_color=self.C_LIGHT_BG,
            cell_fill_mode=TableCellFillMode.EVEN_ROWS,
            col_widths=col_widths,
            line_height=6,
            text_align="LEFT",
            width=total_w,
            headings_style=header_style,
        ) as table:
            row = table.row()
            for h in headers:
                row.cell(h)
            for r in rows:
                row = table.row()
                for ci, cell_text in enumerate(r):
                    if ci == 0 and first_col_bold:
                        row.cell(cell_text, style=bold_style)
                    else:
                        row.cell(cell_text)
        self.ln(2)

    # --- フロー図 ---

    def flow_diagram(self, boxes, box_w=35, arrow_w=8, box_h=16):
        """簡易フロー図を描画する。

        Args:
            boxes: [(ラベル, (R,G,B)), ...] のリスト
            box_w: ボックス幅
            arrow_w: 矢印部分の幅
            box_h: ボックス高さ
        """
        total_w = self.w - self.l_margin - self.r_margin
        total_flow = len(boxes) * box_w + (len(boxes) - 1) * arrow_w
        start_x = self.l_margin + (total_w - total_flow) / 2
        flow_y = self.get_y()

        for i, (text, bg) in enumerate(boxes):
            x = start_x + i * (box_w + arrow_w)
            self.set_fill_color(*bg)
            self.set_draw_color(*self.C_BORDER)
            self.set_line_width(0.3)
            self.rect(x, flow_y, box_w, box_h, style="FD")
            self.set_xy(x, flow_y + 1)
            self.set_font("HG", "", 7.5)
            self.set_text_color(*self.C_BODY)
            self.multi_cell(box_w, 4, text, align="C")
            if i < len(boxes) - 1:
                ax = x + box_w
                ay = flow_y + box_h / 2
                self.set_draw_color(*self.C_NOTE)
                self.set_line_width(0.4)
                self.line(ax + 1, ay, ax + arrow_w - 1, ay)
                self.line(ax + arrow_w - 3, ay - 1.5, ax + arrow_w - 1, ay)
                self.line(ax + arrow_w - 3, ay + 1.5, ax + arrow_w - 1, ay)

        self.set_y(flow_y + box_h + 6)
