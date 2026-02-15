"""
table_extractor.py

Convert OCR outputs (text, confidence, bbox) into a pandas DataFrame.
Supports three modes:
- Printed Table
- Excel (Proper)
- Excel (Enhanced)

Design goals:
- Stability and explainability
- Human-in-the-loop (preserve raw text)
- CPU-friendly heuristics (no heavy image morph ops)
"""
from typing import List, Tuple, Dict, Any
import math
import re
from collections import defaultdict

import numpy as np
import pandas as pd
from difflib import get_close_matches

# Preferred header mapping suggestions (used when normalizing)
PREFERRED_NAMES = [
    "salesperson",
    "date",
    "item",
    "quantity",
    "qty",
    "rate",
    "amount",
    "total",
    "sales",
    "payment_mode",
    "remarks",
    "description",
    "price",
    "month",
    "name",
]


def _bbox_center(bbox: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Return center (x, y) of bbox (4 corner points)."""
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _group_by_rows(ocr_items: List[Tuple[str, float, List[Tuple[float, float]]]], y_tol: int = 15):
    """
    Group OCR items into rows based on Y coordinate proximity.
    Returns list of rows, each row is a list of items (text, conf, bbox, center).
    """
    rows = []
    centers = []
    for text, conf, bbox in ocr_items:
        if not bbox:
            # if bbox missing, skip grouping by position: put at end
            cy = None
        else:
            _, cy = _bbox_center(bbox)
        centers.append((text, conf, bbox, cy))

    # Sort by y
    centers_sorted = sorted(centers, key=lambda x: float(x[3]) if x[3] is not None else 1e9)

    for text, conf, bbox, cy in centers_sorted:
        if cy is None:
            # append to last row or new row
            if rows:
                rows[-1].append((text, conf, bbox))
            else:
                rows.append([(text, conf, bbox)])
            continue

        placed = False
        for r in rows:
            # use first element of r to get its y center
            _, _, rbbox = r[0]
            if rbbox:
                _, rcy = _bbox_center(rbbox)
            else:
                rcy = None
            if rcy is None:
                continue
            if abs(cy - rcy) <= y_tol:
                r.append((text, conf, bbox))
                placed = True
                break
        if not placed:
            rows.append([(text, conf, bbox)])
    return rows


def _is_header_row(row_items: List[Tuple[str, float, List[Tuple[float, float]]]]):
    """
    Decide whether a row is likely a header:
    - contains mostly alphabetic tokens
    - average confidence not too low
    """
    alpha_count = 0
    token_count = 0
    confs = []
    for text, conf, _ in row_items:
        tokens = re.findall(r"[A-Za-z]+", text)
        token_count += max(1, len(tokens or [text]))
        if tokens:
            alpha_count += 1
        confs.append(conf)
    alpha_ratio = alpha_count / max(1, len(row_items))
    avg_conf = sum(confs) / max(1, len(confs))
    return alpha_ratio >= 0.5 and avg_conf >= 0.3


def _normalize_header_text(s: str) -> str:
    """
    Normalize OCR header text to safe column name:
    - strip punctuation, lower-case, replace spaces with underscore
    - prefer friendly names where possible
    """
    s = s.strip()
    s = re.sub(r"[^\w\s]", " ", s)  # remove punctuation
    s = re.sub(r"\s+", " ", s)
    s = s.lower().strip()
    # fuzzy map to preferred names
    match = get_close_matches(s, PREFERRED_NAMES, n=1, cutoff=0.7)
    if match:
        return match[0]
    # map common words
    s = s.replace(" ", "_")
    if not s:
        return "column_1"
    return s


def _clean_numeric(text: str) -> str:
    """Remove currency symbols and thousands separators; keep decimal and minus."""
    if text is None:
        return ""
    t = text.strip()
    # Replace common OCR errors
    t = t.replace("O", "0")
    t = re.sub(r"[^\d\.\-]", "", t)
    # collapse multiple dots
    if t.count(".") > 1:
        parts = t.split(".")
        t = parts[0] + "." + "".join(parts[1:])
    return t


def extract_table_from_ocr(
    ocr_items: List[Tuple[str, float, List[Tuple[float, float]]]], mode: str = "Printed Table"
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Main entry point to convert OCR items into a DataFrame.
    Returns (df, meta) where meta includes raw_rows and row_confidence for traceability.
    """
    # Group into rows
    rows = _group_by_rows(ocr_items, y_tol=18)

    # Convert each row into list of tokens with x-centers for column inference
    structured_rows = []
    for r in rows:
        tokens = []
        for text, conf, bbox in r:
            if bbox:
                cx, cy = _bbox_center(bbox)
            else:
                # put at x large so it lands later
                cx = 99999
            tokens.append({"text": text, "conf": conf, "cx": cx, "bbox": bbox})
        # sort tokens by x
        tokens_sorted = sorted(tokens, key=lambda t: t["cx"])
        structured_rows.append(tokens_sorted)

    # Heuristics per mode
    if mode == "Printed Table":
        return _extract_printed_table(structured_rows)
    elif mode == "Excel (Proper)":
        return _extract_excel_proper(structured_rows)
    else:  # Excel (Enhanced)
        return _extract_excel_enhanced(structured_rows)


def _infer_columns_from_header(header_tokens: List[Dict]) -> List[float]:
    """
    Given header tokens (sorted left->right), return column anchors as x positions.
    We'll use token centers as anchors.
    """
    anchors = [t["cx"] for t in header_tokens]
    return anchors


def _assign_tokens_to_anchors(row_tokens: List[Dict], anchors: List[float]) -> List[str]:
    """
    Assign tokens in a row to the nearest anchor by x-distance.
    Returns list of text values aligned with anchors; if no token for an anchor, empty string.
    If there are more tokens than anchors, append to last column (fallback).
    """
    values = [""] * len(anchors)
    for tok in row_tokens:
        # find nearest anchor index
        dists = [abs(tok["cx"] - a) for a in anchors]
        idx = int(np.argmin(dists))
        if values[idx]:
            # If collision, concatenate with space
            values[idx] = values[idx] + " " + tok["text"]
        else:
            values[idx] = tok["text"]
    return values


def _extract_printed_table(structured_rows: List[List[Dict]]):
    """
    Printed Table mode:
    - Find first header row by heuristic
    - Use header token centers as anchors
    - Assign subsequent rows to nearest anchors
    - If header not found, fallback to column_N naming and provide raw_row_text column
    """
    header_row = None
    header_idx = None
    for i, r in enumerate(structured_rows):
        if _is_header_row([(t["text"], t["conf"], t["bbox"]) for t in r]):
            header_row = r
            header_idx = i
            break

    meta = {"raw_rows": [], "row_confidence": []}

    if header_row:
        anchors = _infer_columns_from_header(header_row)
        headers = [_normalize_header_text(t["text"]) for t in header_row]

        data_rows = structured_rows[header_idx + 1 :]
        rows_out = []
        for r in data_rows:
            values = _assign_tokens_to_anchors(r, anchors)
            row_conf = float(np.mean([t["conf"] for t in r]) if r else 0.0)
            rows_out.append(values)
            meta["raw_rows"].append(" | ".join([t["text"] for t in r]))
            meta["row_confidence"].append(row_conf)

        df = pd.DataFrame(rows_out, columns=headers)
        # If some columns are empty strings in header, rename them to column_N
        df.columns = [
            c if c and not c.startswith("column_") else f"column_{i+1}"
            for i, c in enumerate(df.columns)
        ]
        return df, pd.DataFrame(meta)  # return meta as DataFrame for convenience
    else:
        # Fallback: create single column raw_row_text
        rows_text = [" | ".join([t["text"] for t in r]) for r in structured_rows]
        confs = [float(np.mean([t["conf"] for t in r])) if r else 0.0 for r in structured_rows]
        df = pd.DataFrame({"raw_row_text": rows_text})
        meta["raw_rows"] = rows_text
        meta["row_confidence"] = confs
        return df, pd.DataFrame(meta)


def _extract_excel_proper(structured_rows: List[List[Dict]]):
    """
    Excel (Proper) mode:
    - Strong header detection
    - Normalize header text aggressively
    - Enforce placing values under closest header
    - Clean numeric fields (remove $ ,)
    """
    header_row = None
    header_idx = None
    # Prefer top-most header with alphabetic content and reasonable token count
    for i, r in enumerate(structured_rows[:6]):  # assume header in top 6 rows
        if _is_header_row([(t["text"], t["conf"], t["bbox"]) for t in r]):
            header_row = r
            header_idx = i
            break

    meta = {"raw_rows": [], "row_confidence": []}

    if not header_row:
        # degrade to printed mode fallback
        return _extract_printed_table(structured_rows)

    anchors = _infer_columns_from_header(header_row)
    headers = []
    for t in header_row:
        h = _normalize_header_text(t["text"])
        # enforce friendly naming (avoid column_ placeholders)
        if h.startswith("column_"):
            h = f"column_{len(headers)+1}"
        headers.append(h)

    data_rows = structured_rows[header_idx + 1 :]
    rows_out = []
    for r in data_rows:
        raw_texts = [t["text"] for t in r]
        values = _assign_tokens_to_anchors(r, anchors)
        # Clean numeric-looking values
        cleaned = []
        for val in values:
            if val and re.search(r"[\d\$\€\,\.-]", val):
                cleaned.append(_clean_numeric(val))
            else:
                cleaned.append(val)
        rows_out.append(cleaned)
        meta["raw_rows"].append(" | ".join(raw_texts))
        meta["row_confidence"].append(float(np.mean([t["conf"] for t in r]) if r else 0.0))

    df = pd.DataFrame(rows_out, columns=headers)
    # Try to coerce numeric columns
    for col in df.columns:
        # if majority of values look numeric, convert
        non_null = df[col].dropna().astype(str)
        numeric_like = non_null.str.match(r"^-?\d+(\.\d+)?$").sum()
        if len(non_null) > 0 and numeric_like / len(non_null) >= 0.5:
            df[col] = pd.to_numeric(df[col].replace("", None), errors="coerce")
    return df, pd.DataFrame(meta)


def _extract_excel_enhanced(structured_rows: List[List[Dict]]):
    """
    Excel (Enhanced) mode:
    - Fuzzy match headers to common business terms
    - Merge split numeric tokens heuristically
    - Flag low-confidence cells
    - Preserve raw_row_text and per-row confidence
    """
    # find header candidates in top rows
    header_row = None
    header_idx = None
    for i, r in enumerate(structured_rows[:8]):
        texts = " ".join([t["text"] for t in r]).lower()
        if any(k in texts for k in ["name", "date", "amount", "total", "sales", "item", "qty"]):
            header_row = r
            header_idx = i
            break
    if not header_row:
        # fallback
        return _extract_printed_table(structured_rows)

    anchors = _infer_columns_from_header(header_row)
    # normalize headers with fuzzy match to preferred names
    headers = []
    for t in header_row:
        raw = t["text"]
        # try close matches by token
        best = get_close_matches(raw.lower(), PREFERRED_NAMES, n=1, cutoff=0.5)
        if best:
            headers.append(best[0])
        else:
            headers.append(_normalize_header_text(raw))

    # Enforce no generic 'col' names; use column_N if necessary
    headers = [h if not h.startswith("column_") else f"column_{i+1}" for i, h in enumerate(headers)]

    data_rows = structured_rows[header_idx + 1 :]
    rows_out = []
    row_conf_list = []
    needs_review_flags = []
    raw_rows = []

    for r in data_rows:
        # Merge adjacent tokens that likely form a single numeric cell:
        merged_tokens = []
        i = 0
        tokens = r
        while i < len(tokens):
            cur = tokens[i]
            cur_text = cur["text"]
            # Heuristic: if token looks like a number fragment and next token also numericish, merge
            def is_num_fragment(s):
                return bool(re.match(r"^[\d\$\€\-,\.O]+$", s))  # O (letter) sometimes 0
            if i + 1 < len(tokens) and is_num_fragment(cur_text) and is_num_fragment(tokens[i + 1]["text"]):
                merged_text = cur_text + tokens[i + 1]["text"]
                merged_conf = float((cur["conf"] + tokens[i + 1]["conf"]) / 2.0)
                merged_cx = (cur["cx"] + tokens[i + 1]["cx"]) / 2.0
                merged_tokens.append({"text": merged_text, "conf": merged_conf, "cx": merged_cx, "bbox": cur["bbox"]})
                i += 2
            else:
                merged_tokens.append(cur)
                i += 1

        # Assign to anchors
        values = _assign_tokens_to_anchors(merged_tokens, anchors)
        # Flag low-confidence cells
        cell_flags = []
        for j, val in enumerate(values):
            # find tokens assigned to this anchor to compute confidence
            assigned_tokens = [t for t in merged_tokens if abs(t["cx"] - anchors[j]) == min(abs(t["cx"] - a) for a in anchors)]
            avg_conf = float(np.mean([t["conf"] for t in assigned_tokens])) if assigned_tokens else 0.0
            cell_flags.append(avg_conf < 0.6)  # needs review if below 0.6
        # Build output row, and compute row-level confidence (avg of tokens)
        row_conf = float(np.mean([t["conf"] for t in merged_tokens])) if merged_tokens else 0.0
        rows_out.append(values)
        row_conf_list.append(row_conf)
        needs_review_flags.append(any(cell_flags))
        raw_rows.append(" | ".join([t["text"] for t in r]))

    df = pd.DataFrame(rows_out, columns=headers)
    # Add traceability & flags
    df["_raw_row_text"] = raw_rows
    df["_needs_review"] = needs_review_flags
    meta = pd.DataFrame({"raw_rows": raw_rows, "row_confidence": row_conf_list, "needs_review": needs_review_flags})
    return df, meta
