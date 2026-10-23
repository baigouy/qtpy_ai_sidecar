from qtpy.QtCore import Qt, QRect
from qtpy.QtGui import QImage, QPainter, QColor
from qtpy.QtWidgets import QWidget, QVBoxLayout, QSlider, QLabel


class Wipe(QWidget):
    def __init__(self, before, after):
        super().__init__()
        self.before, self.after = QImage(str(before)), QImage(str(after))
        self.value = 50
        self.setMinimumHeight(220)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor('#ebe5dd'))
        images = [self.before, self.after]
        if any(i.isNull() for i in images):
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Comparison unavailable')
            return
        scale = min(self.width() / max(i.width() for i in images), self.height() / max(i.height() for i in images))
        split = self.width() * self.value // 100
        for image, clip in zip(images, [QRect(0, 0, split, self.height()), QRect(split, 0, self.width() - split, self.height())]):
            painter.save()
            painter.setClipRect(clip)
            painter.drawImage(QRect(0, 0, int(image.width() * scale), int(image.height() * scale)), image)
            painter.restore()
        painter.drawLine(split, 0, split, self.height())


class Comparison(QWidget):
    def __init__(self, before, after):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Before ← drag divider → After'))
        self.wipe = Wipe(before, after)
        layout.addWidget(self.wipe)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(50)
        slider.valueChanged.connect(self.move)
        layout.addWidget(slider)

    def move(self, value):
        self.wipe.value = value
        self.wipe.update()
