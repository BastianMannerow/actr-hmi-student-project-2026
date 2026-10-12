"""Small local raster assets; decoded/scaled once, never fetched at runtime."""
from functools import lru_cache
from pathlib import Path
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QImageReader, QPainter, QPixmap

ASSET_DIR = Path(__file__).resolve().parents[1] / 'assets' / 'environment'

@lru_cache(maxsize=8)
def source_pixmap(name: str) -> QPixmap:
    image = QImageReader(str(ASSET_DIR / name)).read()
    if image.isNull():
        return QPixmap()
    pixmap = QPixmap.fromImage(image)
    if name == 'squirtle.png':
        from PyQt6.QtGui import QRegion
        bounds = QRegion(pixmap.mask()).boundingRect()
        return pixmap.copy(bounds) if not bounds.isEmpty() else pixmap
    return pixmap

@lru_cache(maxsize=96)
def scaled_pixmap(name: str, size: int) -> QPixmap:
    return source_pixmap(name).scaled(
        max(1, size), max(1, size), Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation if name == 'squirtle.png'
        else Qt.TransformationMode.SmoothTransformation)

def draw_asset(painter: QPainter, rect: QRectF, name: str) -> bool:
    pixmap = scaled_pixmap(name, round(min(rect.width(), rect.height())))
    if pixmap.isNull():
        return False
    painter.drawPixmap(round(rect.center().x() - pixmap.width() / 2),
                       round(rect.center().y() - pixmap.height() / 2), pixmap)
    return True
