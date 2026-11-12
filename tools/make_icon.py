"""Draw the app icon with Qt and save assets/zerobox.ico (16-256) + zerobox.png."""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication
from PIL import Image
app = QGuiApplication([])
from zerobox.ui.brand import logo_pixmap
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
imgs = []
for s in (16, 24, 32, 48, 64, 128, 256):
    buf = QBuffer(); buf.open(QIODevice.WriteOnly); logo_pixmap(s).save(buf, "PNG")
    imgs.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
imgs[-1].save(os.path.join(out, "zerobox.ico"), sizes=[(i.width, i.height) for i in imgs], append_images=imgs[:-1])
logo_pixmap(512).save(os.path.join(out, "zerobox.png"))
print("ok")
