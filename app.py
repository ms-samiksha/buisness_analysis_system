"""
Pics-to-Excel OCR - Streamlit Web App
CPU-only PaddleOCR pipeline with three extraction modes:
Printed Table, Excel (Proper), Excel (Enhanced).
"""
import io
from datetime import datetime
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

# Ensure src package is importable
sys.path.insert(0, str(Path(__file__).parent / "src"))

from preprocess import preprocess_for_ocr, preprocess_for_ocr_advanced
from ocr_engine import OCREngine
from table_extractor import extract_table_from_ocr
from exporter import export_with_formatting


# Page config
st.set_page_config(
    page_title="Pics-to-Excel OCR",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📊 Pics-to-Excel OCR")
st.markdown(
    "Upload an image of a table, run CPU-only OCR, review/edit the extracted "
    "table, then download as Excel. Prioritizes stability and editability."
)

# Sidebar instructions (concise)
with st.sidebar:
    st.header("ℹ️ Instructions")
    st.markdown(
        "- Upload a clear photo or screenshot (PNG/JPG/BMP).\n"
        "- Choose mode matching your image (Printed / Excel Proper / Excel Enhanced).\n"
        "- Review and edit before download — OCR isn't perfect.\n"
        "- This app uses PaddleOCR on CPU (no cloud, no GPU)."
    )
    st.divider()
    st.caption("Human-in-the-loop: always review before saving.")

# Upload + mode selector
col1, col2 = st.columns([2, 1])
with col1:
    uploaded_file = st.file_uploader(
        "Choose an image file (JPG/PNG/BMP)",
        type=["jpg", "jpeg", "png", "bmp"],
        help="Upload a clear image or screenshot of a table",
    )
with col2:
    mode = st.selectbox(
        "Mode",
        ["Printed Table", "Excel (Proper)", "Excel (Enhanced)"],
        help="Pick the extraction behavior that best matches your image",
    )

# Preview
if uploaded_file:
    image = Image.open(uploaded_file).convert("RGB")
    st.image(image, caption="Uploaded Image", use_column_width=True)
    st.info(f"Image size: {image.size[0]}×{image.size[1]} px")

# Run OCR / extraction
if uploaded_file:
    st.divider()
    if st.button("🚀 Run OCR & Extract Table"):
        with st.spinner("Processing (CPU only)... First run loads models, may take 1-2 min"):
            try:
                img_np = np.array(image)[:, :, ::-1]  # RGB->BGR for PaddleOCR
                
                st.info(f"📐 Image shape: {img_np.shape}, dtype: {img_np.dtype}")
                
                # Choose preprocessing based on mode
                if mode == "Printed Table":
                    # For clean printed tables: use RAW image (no preprocessing)
                    processed = img_np
                    st.info("Using RAW image (no preprocessing)")
                elif mode == "Excel (Enhanced)":
                    # More aggressive for poor images
                    processed = preprocess_for_ocr_advanced(img_np)
                    st.info("Using ENHANCED preprocessing")
                else:  # Excel (Proper)
                    # Standard light preprocessing
                    processed = preprocess_for_ocr(img_np, is_handwritten=False)
                    st.info("Using STANDARD preprocessing")

                st.info(f"🔍 Running PaddleOCR...")
                ocr_engine = OCREngine(use_gpu=False)
                ocr_results = ocr_engine.run_ocr(processed)

                st.info(f"Raw OCR results: {len(ocr_results) if ocr_results else 0} items detected")
                
                if ocr_results:
                    # Show first few raw results
                    with st.expander("🔎 Raw OCR Debug Info"):
                        for i, (txt, conf, bbox) in enumerate(ocr_results[:5]):
                            st.write(f"**{i+1}.** Text: `{txt}` | Conf: {conf:.2%} | Bbox points: {len(bbox)}")

                if not ocr_results:
                    st.warning(
                        "⚠️ **No text detected by PaddleOCR.**\n\n"
                        "Try:\n"
                        "1. **Use 'Excel (Enhanced)' mode** for better preprocessing\n"
                        "2. **Check image quality** — must be readable by human eye\n"
                        "3. **High contrast** — ensure text stands out from background\n"
                        "4. Try different image if this doesn't work"
                    )
                    st.session_state.extracted_df = None
                    st.session_state.ocr_results = []
                else:
                    st.info(f"📊 Extracting table from {len(ocr_results)} items...")
                    # Extract table based on mode
                    df, meta = extract_table_from_ocr(ocr_results, mode=mode)
                    st.session_state.extracted_df = df
                    st.session_state.ocr_results = ocr_results
                    st.session_state.extract_meta = meta
                    st.success(f"✅ Extraction finished — {len(df)} rows, {len(df.columns)} columns")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                import traceback
                st.text(traceback.format_exc())

# If we have an extracted DataFrame, show and allow editing
if "extracted_df" in st.session_state and st.session_state.extracted_df is not None:
    st.divider()
    st.subheader("📋 Extracted Table (editable)")
    df = st.session_state.extracted_df.copy()

    # Show a warning reminding to verify
    st.warning("OCR accuracy depends on image quality. Please review and edit extracted data.")

    # Show metrics and confidence if available
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Rows", len(df))
    with col2:
        st.metric("Columns", len(df.columns))
    with col3:
        if "row_confidence" in st.session_state.get("extract_meta", {}):
            avg_conf = float(st.session_state["extract_meta"]["row_confidence"].mean())
            st.metric("Avg Row Confidence", f"{avg_conf:.2%}")

    # ================ EDITABLE TABLE SECTION ================
    st.subheader("✏️ Edit Table Data")
    st.markdown("Click cells to edit. Changes are live.")
    
    # Use data_editor for in-place editing
    edited_df = st.data_editor(
        df, 
        use_container_width=True, 
        height=400, 
        key="editor",
        num_rows="dynamic"  # Allow adding/removing rows
    )
    
    # Track changes
    if not edited_df.equals(df):
        st.session_state.extracted_df = edited_df
        st.success("✅ Table updated in memory")
    
    # Show original raw OCR (collapsible)
    with st.expander("🔍 View raw OCR outputs"):
        st.write("Original text detected by OCR engine (before parsing):")
        st.write("Format: (text, confidence, bbox)")
        ocr_list = st.session_state.get("ocr_results") or []
        if ocr_list:
            for i, (text, conf, bbox) in enumerate(ocr_list[:20]):  # show first 20
                st.caption(f"**{i+1}.** Text: `{text}` | Conf: {conf:.2%}")
        else:
            st.info("No raw OCR results.")

    # ================ DOWNLOAD SECTION ================
    st.divider()
    st.subheader("⬇️ Download")
    try:
        bytes_xlsx = export_with_formatting(
            st.session_state.extracted_df,
            sheet_name="Extracted Table",
            title="OCR Extracted Table Data",
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"extracted_table_{timestamp}.xlsx"
        st.download_button(
            label="📥 Download as Excel",
            data=bytes_xlsx,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        st.success(f"Ready to download: {filename}")
    except Exception as e:
        st.error(f"Could not generate Excel: {e}")

# If no extraction yet, show a hint
if "extracted_df" not in st.session_state or st.session_state.extracted_df is None:
    st.info("Upload an image and click 'Run OCR & Extract Table' to begin.")
