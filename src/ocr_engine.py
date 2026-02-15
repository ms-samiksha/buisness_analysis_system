"""
ocr_engine.py

Wrapper around PaddleOCR configured for CPU-only usage.
Returns list of tuples: (text, confidence, bbox)
- bbox is a list of four (x, y) corner points.
This wrapper is defensive: handles a few PaddleOCR result shapes.
"""
from typing import List, Tuple, Any
import numpy as np

try:
    from paddleocr import PaddleOCR
except Exception as e:
    raise ImportError(
        "PaddleOCR is required. Install with `pip install paddleocr`.\n"
        "Note: This app uses PaddleOCR on CPU only."
    ) from e


class OCREngine:
    def __init__(self, use_gpu: bool = False, lang: str = "en"):
        """
        Initialize PaddleOCR engine.
        Keep parameters minimal for CPU operation.
        Note: use_gpu param is kept for API compatibility but CPU is always used (safer).
        """
        self.use_gpu = False  # force CPU for stability
        # Newer PaddleOCR versions don't accept use_gpu directly; use det_model, rec_model params
        # or rely on environment. We use minimal init for CPU.
        try:
            self.ocr = PaddleOCR(use_angle_cls=False, lang=lang)
        except TypeError:
            # Fallback for older versions that may accept use_gpu
            try:
                self.ocr = PaddleOCR(use_angle_cls=False, use_gpu=False, lang=lang)
            except Exception as e:
                raise RuntimeError(
                    f"Failed to initialize PaddleOCR: {e}. "
                    "Ensure paddleocr is installed: pip install paddleocr"
                ) from e

    def _normalize_paddle_result(self, res_item: Any) -> Tuple[str, float, List[Tuple[float, float]]]:
        """
        Normalize one OCR result item into (text, confidence, bbox).
        PaddleOCR format: [[[x1,y1], [x2,y2], [x3,y3], [x4,y4]], (text, score)]
        """
        # Default fallback values
        bbox = []
        text = ""
        conf = 0.0

        try:
            # Standard PaddleOCR format
            if isinstance(res_item, (list, tuple)) and len(res_item) >= 2:
                bbox_raw = res_item[0]
                
                # Parse bbox — should be list of 4 points [[x,y], [x,y], ...]
                if isinstance(bbox_raw, (list, tuple)):
                    try:
                        bbox = [(float(p[0]), float(p[1])) for p in bbox_raw if isinstance(p, (list, tuple)) and len(p) >= 2]
                    except (TypeError, ValueError, IndexError):
                        bbox = []
                
                # Parse text and confidence
                txt_part = res_item[1]
                if isinstance(txt_part, (list, tuple)) and len(txt_part) >= 2:
                    text = str(txt_part[0]).strip()
                    try:
                        conf = float(txt_part[1])
                    except (TypeError, ValueError):
                        conf = 0.0
                elif isinstance(txt_part, dict):
                    text = str(txt_part.get("text", "")).strip()
                    try:
                        conf = float(txt_part.get("confidence", 0.0))
                    except (TypeError, ValueError):
                        conf = 0.0
                elif isinstance(txt_part, str):
                    text = txt_part.strip()
                    conf = 0.0
            
            elif isinstance(res_item, dict):
                # Fallback dict format
                text = str(res_item.get("text", "")).strip()
                try:
                    conf = float(res_item.get("confidence", 0.0))
                except (TypeError, ValueError):
                    conf = 0.0
                bbox_raw = res_item.get("bbox", [])
                if isinstance(bbox_raw, (list, tuple)):
                    try:
                        bbox = [(float(p[0]), float(p[1])) for p in bbox_raw if isinstance(p, (list, tuple)) and len(p) >= 2]
                    except (TypeError, ValueError, IndexError):
                        bbox = []
        
        except Exception as e:
            print(f"Error normalizing result: {e}")
            pass

        return text, conf, bbox

    def run_ocr(self, image: np.ndarray) -> List[Tuple[str, float, List[Tuple[float, float]]]]:
        """
        Run OCR on an input image (numpy array).
        Returns a list of (text, confidence, bbox).
        Defensive: handles many result format variations.
        """
        # Validate input
        if image is None or image.size == 0:
            return []
        
        try:
            # Run OCR — PaddleOCR.ocr() returns a list of lines where each line is list of detections
            results = self.ocr.ocr(image)
        except Exception as e:
            print(f"OCR Error: {e}")
            return []
        
        # Handle empty/None results
        if not results:
            print("PaddleOCR returned empty results")
            return []
        
        parsed = []
        
        # PaddleOCR returns: [line1, line2, ...]
        # where each line is: [[bbox1, (text1, conf1)], [bbox2, (text2, conf2)], ...]
        for line_idx, line in enumerate(results):
            if line is None:
                continue
            
            # Each line is a list of detection items
            if not isinstance(line, list):
                continue
            
            for item in line:
                if item is None:
                    continue
                
                txt, conf, bbox = self._normalize_paddle_result(item)
                
                # Filter empty text
                if not txt or txt.isspace():
                    continue
                
                parsed.append((txt.strip(), float(conf), bbox))
        
        print(f"OCR parsed {len(parsed)} items from {len(results)} lines")
        return parsed
