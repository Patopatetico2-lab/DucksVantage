"""
Camada de Compatibilidade Qt (PyQt6 / PySide6) para o Ducksvantage.
Permite execução nativa com PyQt6 ou PySide6 no CachyOS / Arch Linux.
"""

QT_LIB = None

try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import (
        Qt, QTimer, pyqtSignal as Signal, pyqtSlot as Slot,
        QSize, QPoint, QPointF, QObject, QVariantAnimation, QRectF
    )
    from PyQt6.QtGui import (
        QColor, QFont, QPainter, QPainterPath, QPolygonF, QBrush, QPen,
        QLinearGradient, QConicalGradient, QIcon, QAction, QPixmap,
        QShortcut, QKeySequence
    )
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QLabel, QPushButton, QFrame, QScrollArea,
        QProgressBar, QStackedWidget, QMessageBox, QGraphicsDropShadowEffect,
        QSizePolicy, QSystemTrayIcon, QMenu, QGraphicsOpacityEffect,
        QSlider, QComboBox, QLineEdit, QDialog
    )
    QT_LIB = "PyQt6"
except ImportError:
    try:
        from PySide6.QtCore import (
            Qt, QTimer, Signal, Slot,
            QSize, QPoint, QPointF, QObject, QVariantAnimation, QRectF
        )
        from PySide6.QtGui import (
            QColor, QFont, QPainter, QPainterPath, QPolygonF, QBrush, QPen,
            QLinearGradient, QConicalGradient, QIcon, QAction, QPixmap,
            QShortcut, QKeySequence
        )
        from PySide6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QGridLayout, QLabel, QPushButton, QFrame, QScrollArea,
            QProgressBar, QStackedWidget, QMessageBox, QGraphicsDropShadowEffect,
            QSizePolicy, QSystemTrayIcon, QMenu, QGraphicsOpacityEffect,
            QSlider, QComboBox, QLineEdit, QDialog
        )
        QT_LIB = "PySide6"
    except ImportError:
        QT_LIB = None


def is_qt_available() -> bool:
    return QT_LIB is not None
