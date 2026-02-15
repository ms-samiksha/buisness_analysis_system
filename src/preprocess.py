"""
preprocess.py

CPU-friendly image preprocessing utilities used before OCR.
Focus: grayscale, contrast enhancement, adaptive thresholding, light denoising.
Avoid heavy morphological operations for speed and stability.
"""
import cv2
import numpy as np


def _to_gray(image_bgr: np.ndarray) -> np.ndarray:
    """Convert BGR to grayscale."""
    if len(image_bgr.shape) == 3 and image_bgr.shape[2] == 3:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_bgr.copy()
    return gray


def _increase_contrast(gray: np.ndarray) -> np.ndarray:
    """Use CLAHE (contrast limited adaptive histogram equalization) for local contrast."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _adaptive_thresh(gray: np.ndarray) -> np.ndarray:
    """Adaptive threshold to handle uneven lighting."""
    # Block size must be odd and >1
    block_size = 25
    if block_size % 2 == 0:
        block_size += 1
    thr = cv2.adaptiveThreshold(
        gray,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=block_size,
        C=10,
    )
    return thr


def _denoise(gray: np.ndarray) -> np.ndarray:
    """Light denoising using fastNlMeansDenoising (grayscale)."""
    return cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)


def preprocess_for_ocr(image_bgr: np.ndarray, is_handwritten: bool = False) -> np.ndarray:
    """
    Basic preprocessing for OCR:
    - Convert to grayscale
    - Increase contrast (CLAHE)
    - Light denoise
    For printed text: keep grayscale to preserve detail (PaddleOCR handles it better)
    For handwritten: apply adaptive thresholding for cleaner text
    Returns a 3-channel BGR image for PaddleOCR (it needs 3D, not 2D).
    """
    gray = _to_gray(image_bgr)
    contrast = _increase_contrast(gray)
    denoised = _denoise(contrast)

    if is_handwritten:
        # Handwritten benefits from binarization
        processed = _adaptive_thresh(denoised)
    else:
        # For printed text, keep grayscale detail—don't binarize, it removes text info
        processed = denoised

    # Convert back to 3-channel BGR for PaddleOCR (it needs shape (H,W,3) not (H,W))
    if len(processed.shape) == 2:
        processed = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)
    
    return processed


def preprocess_for_ocr_advanced(image_bgr: np.ndarray) -> np.ndarray:
    """
    Slightly stronger preprocessing for poor-quality images:
    - Grayscale -> CLAHE -> denoise -> small median blur
    Still avoids binarization to preserve text detail.
    Returns a 3-channel BGR image for PaddleOCR.
    """
    gray = _to_gray(image_bgr)
    contrast = _increase_contrast(gray)
    denoised = _denoise(contrast)
    # Small median blur only to reduce fine noise
    processed = cv2.medianBlur(denoised, 3)
    
    # Convert to 3-channel BGR for PaddleOCR
    if len(processed.shape) == 2:
        processed = cv2.cvtColor(processed, cv2.COLOR_GRAY2BGR)
    
    return processed
