"""
exporter.py

Export a pandas DataFrame to an Excel file (in-memory) with basic formatting.
Returns bytes suitable for Streamlit download_button.
"""
import io
from typing import Optional

import pandas as pd
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment
from openpyxl.worksheet.worksheet import Worksheet


def _auto_width(ws: Worksheet, df: pd.DataFrame, extra: int = 2):
    """Set column widths based on max content length in each column."""
    for i, col in enumerate(df.columns, 1):
        max_len = max(
            df[col].astype(str).map(len).max() if not df.empty else 0,
            len(str(col)),
        )
        ws.column_dimensions[get_column_letter(i)].width = max_len + extra


def export_with_formatting(df: pd.DataFrame, sheet_name: str = "Sheet1", title: Optional[str] = None) -> bytes:
    """
    Export df to Excel bytes with simple formatting:
    - Title row (merged)
    - Bold headers
    - Freeze top row
    - Auto column widths
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False, startrow=1 if title else 0)
        workbook = writer.book
        ws = writer.sheets[sheet_name]

        # Title
        if title:
            # Merge across number of columns
            ncols = max(1, len(df.columns))
            ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
            cell = ws.cell(row=1, column=1)
            cell.value = title
            cell.font = Font(size=14, bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Header formatting (if title present, header is in row 2)
        header_row = 2 if title else 1
        for cell in ws[header_row]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        # Freeze panes below header
        freeze_row = header_row + 1
        ws.freeze_panes = ws.cell(row=freeze_row, column=1)

        # Auto width
        _auto_width(ws, df)
        # Context manager auto-saves on exit
    
    # Read bytes after ExcelWriter closes
    output.seek(0)
    return output.read()
    worksheet.title = sheet_name
    
    # Add title
    worksheet['A1'] = title
    worksheet['A1'].font = Font(bold=True, size=14, color="FFFFFF")
    worksheet['A1'].fill = PatternFill(start_color="203864", end_color="203864", fill_type="solid")
    worksheet.merge_cells('A1:Z1')
    worksheet['A1'].alignment = Alignment(horizontal="center", vertical="center")
    
    # Add data
    row_num = 3
    
    # Headers
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for col_num, column_title in enumerate(df.columns, 1):
        cell = worksheet.cell(row=row_num, column=col_num)
        cell.value = column_title
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    worksheet.row_dimensions[row_num].height = 25
    
    # Data rows
    data_alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    
    for r_idx, row in enumerate(df.values, row_num + 1):
        for col_num, value in enumerate(row, 1):
            cell = worksheet.cell(row=r_idx, column=col_num)
            cell.value = value
            cell.border = thin_border
            cell.alignment = data_alignment
            
            # Light alternate row coloring
            if r_idx % 2 == 0:
                cell.fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")
    
    # Adjust column widths
    for col_num in range(1, len(df.columns) + 1):
        max_length = 0
        
        for row in worksheet.iter_rows(min_col=col_num, max_col=col_num):
            for cell in row:
                # Skip merged cells
                if cell.coordinate in worksheet.merged_cells:
                    continue
                
                try:
                    if cell.value and len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
        
        adjusted_width = min(max_length + 2, 50)
        column_letter = get_column_letter(col_num)
        worksheet.column_dimensions[column_letter].width = adjusted_width
    
    workbook.save(output)
    output.seek(0)
    return output.getvalue()
