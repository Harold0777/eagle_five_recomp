#!/usr/bin/env python3
"""Launcher (Qt6) do Ace Combat 5 Static Recompilation.

- Escolhe a ISO e verifica (via SYSTEM.CNF) se e o Ace Combat 5 (USA).
- Edita as configuracoes graficas do ac5_settings.ini.
- Lanca o jogo com os argumentos certos.

Colocar em <projeto>/tools/ac5_launcher.py e correr: python3 tools/ac5_launcher.py
Requer Qt6 para Python:  sudo pacman -S pyside6   (ou: python-pyqt6)
"""
import html
import json
import math
import os
import re
import sys
from pathlib import Path


try:
    from PySide6 import QtCore, QtGui, QtWidgets as W
except ImportError:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets as W
    except ImportError:
        QtCore = QtGui = W = None
Qt = QtCore.Qt if QtCore else None
if W is None:  # sem Qt: permite importar o modulo (ex.: --selftest)
    class W:  # noqa
        QCheckBox = QMainWindow = QWidget = QFrame = QPushButton = object

SECTOR = 2048
EXPECTED_SERIAL = "SLUS_208.51"  # Ace Combat 5: The Unsung War (USA)
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not (IS_WIN or IS_MAC)
PLAT_DIR = "windows" if IS_WIN else "macos" if IS_MAC else "linux"
EXE_NAME = "ac5.exe" if IS_WIN else "ac5"
# Empacotado (PyInstaller): o launcher fica ao lado do jogo; em dev: <projeto>/tools/
ROOT = (Path(sys.executable).parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent)


def config_dir():
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif IS_MAC:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "eagle-five-launcher"


CFG_FILE = config_dir() / "config.json"
OLD_CFG = Path.home() / ".config" / "ac5-launcher.json"  # versao anterior


def find_exe():
    """Procura o executavel ao lado do launcher e em build/<plataforma>."""
    cands = [ROOT, ROOT / "build" / PLAT_DIR]
    if (ROOT / "build").is_dir():
        cands += sorted(p for p in (ROOT / "build").iterdir() if p.is_dir())
    for d in cands:
        if (d / EXE_NAME).is_file():
            return d / EXE_NAME
    return ROOT / "build" / PLAT_DIR / EXE_NAME

GFX_HINTS = ("fxaa", "sharp", "filter", "aniso", "deinterlace", "bright",
             "contrast", "gamma", "satur", "scale", "res", "vsync",
             "fullscreen", "msaa", "fsr", "aspect", "window", "present")


# ---------------------------------------------------------------------------
# Verificacao da ISO (ISO9660, setores de 2048 bytes)
# ---------------------------------------------------------------------------
def _read_root_file(f, name_wanted):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if pvd[1:6] != b"CD001":
        raise ValueError("Nao e uma ISO9660 valida (sem descritor CD001).")
    root = pvd[156:190]
    lba = int.from_bytes(root[2:6], "little")
    size = int.from_bytes(root[10:14], "little")
    f.seek(lba * SECTOR)
    data = f.read(size)
    off = 0
    while off < len(data):
        rec_len = data[off]
        if rec_len == 0:  # padding ate ao proximo setor
            off = (off // SECTOR + 1) * SECTOR
            continue
        name_len = data[off + 32]
        name = data[off + 33:off + 33 + name_len].decode("ascii", "replace")
        name = name.split(";")[0].upper()
        if name == name_wanted:
            f_lba = int.from_bytes(data[off + 2:off + 6], "little")
            f_size = int.from_bytes(data[off + 10:off + 14], "little")
            f.seek(f_lba * SECTOR)
            return f.read(min(f_size, 4096))
        off += rec_len
    raise ValueError("%s nao encontrado na raiz da ISO." % name_wanted)


def verify_iso(path):
    """Devolve (estado, serial, mensagem). estado: 'ok' | 'wrong' | 'invalid'."""
    try:
        with open(path, "rb") as f:
            cnf = _read_root_file(f, "SYSTEM.CNF").decode("ascii", "replace")
    except (OSError, ValueError) as e:
        return "invalid", None, str(e)
    m = re.search(r"BOOT2\s*=\s*cdrom0:\\?([A-Z]{4})[_-](\d{3})[._]?(\d{2})", cnf)
    if not m:
        return "invalid", None, "SYSTEM.CNF sem linha BOOT2 reconhecivel."
    serial = "%s_%s.%s" % m.groups()
    if serial == EXPECTED_SERIAL:
        return "ok", serial, "ISO correta: Ace Combat 5 (USA) [%s]" % serial
    return "wrong", serial, ("ISO de outro jogo ou regiao: %s "
                             "(esperado %s)" % (serial, EXPECTED_SERIAL))


# ---------------------------------------------------------------------------
# Ficheiro .ini (preserva comentarios e ordem das linhas)
# ---------------------------------------------------------------------------
KV = re.compile(r"^(\s*)([A-Za-z0-9_.\-]+)(\s*[=:]\s*)(.*?)((?:\s+[;#].*)?\s*)$")


def load_ini(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    entries, section = [], ""
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1]
            continue
        m = KV.match(line)
        if m:
            entries.append((i, section, m.group(2), m.group(4)))
    return lines, entries


def save_ini(path, lines, changes):
    bak = path.with_name(path.name + ".launcher.bak")
    if not bak.exists():
        bak.write_text(path.read_text(encoding="utf-8", errors="replace"),
                       encoding="utf-8")
    for idx, value in changes.items():
        m = KV.match(lines[idx])
        lines[idx] = "%s%s%s%s%s" % (m.group(1), m.group(2), m.group(3),
                                      value, m.group(5))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_cfg():
    try:
        return json.loads((CFG_FILE if CFG_FILE.exists() else OLD_CFG).read_text())
    except (OSError, ValueError):
        return {}


def save_cfg(cfg):
    CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CFG_FILE.write_text(json.dumps(cfg, indent=2))


# ---------------------------------------------------------------------------
# Interface Qt6  -  identidade "EAGLE FIVE" (HUD de cockpit, desenhada em codigo)
# ---------------------------------------------------------------------------
SECTION_TITLES = {"graphics": "Imagem", "postfx": "Pós-processamento",
                  "display": "Janela e ecrã"}
GFX_SECTIONS = ("graphics", "postfx", "display")
CURATED = {  # (secção, chave) -> (tipo, rótulo, extras)
    ("postfx", "fxaa"): ("check", "Anti-aliasing FXAA"),
    ("postfx", "sharpen"): ("slider", "Nitidez", 0.0, 1.0),
    ("postfx", "brightness"): ("slider", "Brilho", -0.5, 0.5),
    ("postfx", "contrast"): ("slider", "Contraste", 0.5, 1.5),
    ("postfx", "gamma"): ("slider", "Gama", 0.5, 2.0),
    ("postfx", "saturation"): ("slider", "Saturação", 0.0, 2.0),
    ("graphics", "scale_filter"): ("combo", "Filtro de escala", [
        "Pixelado (nearest)", "Bilinear", "Bilinear nítido"]),
}

PAL = {"@BG": "#0a0e13", "@LINE": "#1d2a38", "@TEXT": "#dfe8f1",
       "@MUTED": "#7a8ba0", "@AMBER": "#ffb224", "@CYAN": "#4dd8ff",
       "@RED": "#ff5a4f", "@GREEN": "#5ef2a0",
       "@MONO": "'JetBrains Mono','IBM Plex Mono','Cascadia Mono','Menlo',monospace"}
STYLE = """
* { font-family:'Inter','Segoe UI','Noto Sans',sans-serif; font-size:13px; color:@TEXT; }
#side { background:#080b10; border-right:1px solid #16212d; }
#brand { font-family:@MONO; font-size:17px; font-weight:800; }
#tag { font-family:@MONO; font-size:11px; color:@AMBER; }
#muted { color:@MUTED; }
#h1 { font-size:27px; font-weight:800; }
#cardtitle { font-family:@MONO; font-size:11px; color:@CYAN; }
#readout { font-family:@MONO; font-size:12px; }
#val { font-family:@MONO; font-size:12px; color:@CYAN; }
QPushButton#nav { text-align:left; padding:13px 16px; border:none;
    border-left:3px solid transparent; color:@MUTED; background:transparent;
    font-family:@MONO; font-size:12px; }
QPushButton#nav:hover { color:@TEXT; background:#0e151d; }
QPushButton#nav:checked { color:@AMBER; border-left:3px solid @AMBER; background:#121b26; }
#card { background:rgba(16,23,32,238); border:1px solid @LINE; border-radius:2px; }
QLineEdit, QComboBox { background:#0a0f15; border:1px solid @LINE; border-radius:2px;
    padding:8px 10px; selection-background-color:#7a5410; }
QLineEdit:focus, QComboBox:focus { border-color:@AMBER; }
QComboBox::drop-down { border:none; width:24px; }
QComboBox QAbstractItemView { background:#101720; border:1px solid @LINE;
    selection-background-color:#7a5410; outline:none; }
QPushButton#ghost { background:transparent; border:1px solid #2a3b4e; border-radius:2px;
    padding:8px 16px; font-family:@MONO; font-size:12px; }
QPushButton#ghost:hover { border-color:@AMBER; color:@AMBER; }
QSlider::groove:horizontal { height:4px; background:@LINE; }
QSlider::sub-page:horizontal { background:@AMBER; }
QSlider::handle:horizontal { background:@AMBER; width:8px; height:18px; margin:-7px 0;
    border-radius:1px; }
QPlainTextEdit { background:#070a0e; border:1px solid @LINE; border-radius:2px;
    font-family:@MONO; font-size:11px; color:@GREEN; padding:8px; }
QScrollArea { border:none; background:transparent; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { width:8px; background:transparent; }
QScrollBar::handle:vertical { background:#243142; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""
for _k, _v in PAL.items():
    STYLE = STYLE.replace(_k, _v)


def draw_emblem(p, size):
    """Emblema original: hexágono (radar) + asa delta. Usado no logo e no ícone."""
    P, C = QtCore.QPointF, QtGui.QColor
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.save()
    p.scale(size / 64.0, size / 64.0)
    hexa = QtGui.QPolygonF([P(32 + 29 * math.cos(math.radians(60 * i - 90)),
                              32 + 29 * math.sin(math.radians(60 * i - 90)))
                            for i in range(6)])
    p.setPen(QtGui.QPen(C(PAL["@CYAN"]), 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPolygon(hexa)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(C(PAL["@AMBER"]))
    p.drawPolygon(QtGui.QPolygonF([P(32, 12), P(49, 48), P(32, 40), P(15, 48)]))
    p.setBrush(C(PAL["@BG"]))
    p.drawPolygon(QtGui.QPolygonF([P(32, 25), P(37, 37), P(32, 34), P(27, 37)]))
    p.restore()


class Emblem(W.QWidget):
    def __init__(self, size=46):
        super().__init__()
        self.s = size
        self.setFixedSize(size, size)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        draw_emblem(p, self.s)


class HudBg(W.QWidget):
    """Fundo: grelha tática ténue + arcos de radar."""
    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(PAL["@BG"]))
        g = QtGui.QColor(PAL["@CYAN"])
        g.setAlpha(9)
        p.setPen(QtGui.QPen(g, 1))
        for x in range(0, self.width(), 48):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 48):
            p.drawLine(0, y, self.width(), y)
        a = QtGui.QColor(PAL["@AMBER"])
        a.setAlpha(16)
        p.setPen(QtGui.QPen(a, 1))
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = QtCore.QPointF(self.width() - 70, self.height() + 50)
        for r in (170, 270, 370, 470):
            p.drawEllipse(c, r, r)


class HudCard(W.QFrame):
    """Cartão com marcas de canto estilo mira/HUD."""
    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QtGui.QPainter(self)
        p.setPen(QtGui.QPen(QtGui.QColor(PAL["@AMBER"]), 2))
        w, h, n = self.width() - 1, self.height() - 1, 12
        for x, y, dx, dy in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)):
            p.drawLine(x, y, x + dx * n, y)
            p.drawLine(x, y, x, y + dy * n)


class HudButton(W.QPushButton):
    """Botão principal com cantos cortados. running=True -> modo ABORTAR."""
    def __init__(self, text):
        super().__init__(text)
        self.running = False
        self.setFixedSize(280, 56)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        r, c, P = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, QtCore.QPointF
        poly = QtGui.QPolygonF([P(r.left() + c, r.top()), P(r.right(), r.top()),
                                P(r.right(), r.bottom() - c), P(r.right() - c, r.bottom()),
                                P(r.left(), r.bottom()), P(r.left(), r.top() + c)])
        if not self.isEnabled():
            fill, txt = QtGui.QColor("#121a24"), QtGui.QColor("#4b5a6b")
        else:
            fill = QtGui.QColor(PAL["@RED"] if self.running else PAL["@AMBER"])
            if self.underMouse():
                fill = fill.lighter(112)
            txt = QtGui.QColor("#0a0e13" if not self.running else "white")
        p.setPen(QtGui.QPen(QtGui.QColor("#243142"), 1)
                 if not self.isEnabled() else Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPolygon(poly)
        f = QtGui.QFont(self.font())
        f.setBold(True)
        f.setPointSize(13)
        f.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, 3)
        p.setFont(f)
        p.setPen(txt)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class Switch(W.QCheckBox):
    def __init__(self, checked=False):
        super().__init__()
        self.setChecked(checked)
        self.setFixedSize(46, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(PAL["@AMBER"] if on else "#243142"))
        p.drawRoundedRect(self.rect(), 3, 3)
        p.setBrush(QtGui.QColor("#0a0e13" if on else "#7a8ba0"))
        p.drawRoundedRect(26 if on else 3, 3, 17, 18, 2, 2)


def lbl(text, name=None, track=0):
    w = W.QLabel(text)
    if name:
        w.setObjectName(name)
    if track:
        f = w.font()
        f.setLetterSpacing(QtGui.QFont.SpacingType.AbsoluteSpacing, track)
        w.setFont(f)
    return w


def card(title=None):
    f = HudCard()
    lay = W.QVBoxLayout(f)
    lay.setContentsMargins(22, 18, 22, 18)
    lay.setSpacing(12)
    if title:
        lay.addWidget(lbl(title.upper(), "cardtitle", 2))
    return f, lay


def row(label, widget):
    h = W.QHBoxLayout()
    h.addWidget(lbl(label))
    h.addStretch()
    h.addWidget(widget)
    return h


def ghost(text, fn):
    b = W.QPushButton(text)
    b.setObjectName("ghost")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.clicked.connect(fn)
    return b


def clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()


def header(tag, title):
    box = W.QVBoxLayout()
    box.setSpacing(2)
    box.addWidget(lbl(tag, "tag", 2))
    box.addWidget(lbl(title, "h1"))
    return box


class Launcher(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EAGLE FIVE  -  Ace Combat 5 Launcher")
        self.resize(1040, 680)
        self.setAcceptDrops(True)
        pm = QtGui.QPixmap(128, 128)
        pm.fill(Qt.GlobalColor.transparent)
        ip = QtGui.QPainter(pm)
        draw_emblem(ip, 128)
        ip.end()
        self.setWindowIcon(QtGui.QIcon(pm))

        self.cfg = load_cfg()
        self.proc, self.ok = None, False
        self.fields, self.lines, self.hosts = {}, [], {}
        self.info = lbl("", "muted")

        root = HudBg()
        self.setCentralWidget(root)
        h = W.QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = W.QFrame()
        side.setObjectName("side")
        side.setFixedWidth(230)
        sl = W.QVBoxLayout(side)
        sl.setContentsMargins(0, 26, 0, 16)
        top = W.QHBoxLayout()
        top.setContentsMargins(20, 0, 16, 0)
        top.addWidget(Emblem())
        bl = W.QVBoxLayout()
        bl.setSpacing(0)
        bl.addWidget(lbl("EAGLE FIVE", "brand", 2))
        bl.addWidget(lbl("AC5 // RECOMP", "tag", 2))
        top.addSpacing(6)
        top.addLayout(bl)
        sl.addLayout(top)
        sl.addSpacing(30)

        self.stack = W.QStackedWidget()
        self.navs = []
        pages = [("01  JOGO", self.page_game()),
                 ("02  GRÁFICOS", self.page_settings("02 // VÍDEO", "Gráficos", "gfx")),
                 ("03  AVANÇADO", self.page_settings("03 // SISTEMA", "Avançado", "adv")),
                 ("04  CONSOLA", self.page_console())]
        for i, (name, page) in enumerate(pages):
            b = W.QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.stack.setCurrentIndex(i))
            sl.addWidget(b)
            self.navs.append(b)
            self.stack.addWidget(page)
        self.navs[0].setChecked(True)
        sl.addStretch()
        foot = lbl("ARRASTA A ISO PARA\nA JANELA  ·  %s" % PLAT_DIR.upper(), "muted", 1)
        foot.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(foot)
        h.addWidget(side)
        h.addWidget(self.stack, 1)

        self.build_settings()
        self.refresh_cmd()
        self.check_iso()

    # ---------------- páginas ----------------
    def page_game(self):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 26)
        v.setSpacing(18)
        v.addLayout(header("01 // BRIEFING", "Pronto para decolar?"))

        c, cl = card("Disco")
        r = W.QHBoxLayout()
        self.iso = W.QLineEdit(self.cfg.get("iso", ""))
        self.iso.setPlaceholderText("Escolhe ou arrasta a ISO do jogo…")
        self.iso.textChanged.connect(lambda: self.check_iso())
        r.addWidget(self.iso, 1)
        r.addWidget(ghost("PROCURAR", self.browse))
        cl.addLayout(r)
        self.st_title = lbl("", "readout")
        self.st_detail = lbl("", "muted")
        cl.addWidget(self.st_title)
        cl.addWidget(self.st_detail)
        v.addWidget(c)

        c2, c2l = card("Arranque")
        self.exe_edit = W.QLineEdit(self.cfg.get("exe") or str(find_exe()))
        self.exe_edit.setMinimumWidth(380)
        self.exe_edit.editingFinished.connect(lambda: (self.build_settings(),
                                                       self.refresh_cmd()))
        self.mango = Switch(self.cfg.get("mango", False))
        self.wd = Switch(self.cfg.get("watchdog_off", True))
        self.drv = W.QComboBox()
        self.drv.addItems(["auto", "wayland", "x11"])
        self.drv.setCurrentText(self.cfg.get("driver", "auto"))
        self.data = W.QLineEdit(self.cfg.get("data", "generated"))
        self.data.setFixedWidth(200)
        rows = [("Executável do jogo", self.exe_edit),
                ("Pasta de dados (--data)", self.data),
                ("Desligar watchdog (--watchdog 0)", self.wd)]
        if IS_LINUX:  # opções que só existem em Linux
            rows += [("MangoHud", self.mango), ("Driver de vídeo SDL", self.drv)]
        for lab, w in rows:
            c2l.addLayout(row(lab, w))
        for w, sig in ((self.mango, "toggled"), (self.wd, "toggled"),
                       (self.drv, "currentTextChanged"), (self.data, "textChanged")):
            getattr(w, sig).connect(lambda *_: self.refresh_cmd())
        v.addWidget(c2)

        self.play_btn = HudButton("DECOLAR")
        self.play_btn.clicked.connect(self.play)
        v.addSpacing(4)
        v.addWidget(self.play_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        self.cmd_lbl = lbl("", "muted")
        self.cmd_lbl.setWordWrap(True)
        self.cmd_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.cmd_lbl)
        v.addStretch()
        return page

    def page_settings(self, tag, title, key):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 22)
        v.addLayout(header(tag, title))
        area = W.QScrollArea()
        area.setWidgetResizable(True)
        inner = W.QWidget()
        lay = W.QVBoxLayout(inner)
        lay.setContentsMargins(0, 10, 10, 10)
        lay.setSpacing(16)
        area.setWidget(inner)
        v.addWidget(area, 1)
        self.hosts[key] = lay
        bar = W.QHBoxLayout()
        if key == "gfx":
            bar.addWidget(self.info)
        bar.addStretch()
        bar.addWidget(ghost("DESCARTAR", self.build_settings))
        bar.addWidget(ghost("GUARDAR", lambda: self.save_settings()))
        v.addLayout(bar)
        return page

    def page_console(self):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 22)
        v.addLayout(header("04 // TELEMETRIA", "Consola"))
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        v.addWidget(self.log, 1)
        bar = W.QHBoxLayout()
        bar.addStretch()
        bar.addWidget(ghost("LIMPAR", self.log.clear))
        bar.addWidget(ghost("COPIAR TUDO", lambda: W.QApplication.clipboard()
                            .setText(self.log.toPlainText())))
        v.addLayout(bar)
        return page

    # ---------------- ISO ----------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.iso.setText(urls[0].toLocalFile())
            self.stack.setCurrentIndex(0)
            self.navs[0].setChecked(True)

    def browse(self):
        cur = self.iso.text().strip()
        start = str(Path(cur).parent) if cur else str(Path.home() / "Downloads")
        p, _ = W.QFileDialog.getOpenFileName(
            self, "Escolher ISO do Ace Combat 5", start,
            "Imagens de disco (*.iso *.ISO);;Todos (*)")
        if p:
            self.iso.setText(p)

    def set_status(self, color, text):
        self.st_title.setText('<span style="color:%s">■</span>&nbsp; %s'
                              % (color, html.escape(text)))

    def check_iso(self):
        p = self.iso.text().strip()
        self.st_detail.setText("")
        if not p:
            self.ok = False
            self.set_status(PAL["@MUTED"], "AGUARDANDO ISO")
        elif not os.path.isfile(p):
            self.ok = False
            self.set_status(PAL["@RED"], "FICHEIRO NÃO ENCONTRADO")
        else:
            st, serial, msg = verify_iso(p)
            self.ok = st == "ok"
            self.set_status(PAL["@GREEN"] if self.ok else PAL["@RED"],
                            ("ISO VERIFICADA // %s" % serial) if self.ok else msg)
            self.st_detail.setText("%s  ·  %.2f GB" % (
                os.path.basename(p), os.path.getsize(p) / 1024 ** 3))
        self.play_btn.setEnabled(self.ok or self.proc is not None)
        self.play_btn.update()
        self.refresh_cmd()

    # ---------------- definições ----------------
    def exe(self):
        return Path(self.exe_edit.text().strip())

    def build_settings(self):
        for lay in self.hosts.values():
            clear(lay)
        self.fields.clear()
        ini = self.exe().parent / "ac5_settings.ini"
        if not ini.exists():
            self.info.setText("ac5_settings.ini não existe (corre o jogo uma vez).")
            return
        self.lines, entries = load_ini(ini)
        cards = {}
        for idx, sec, key, val in entries:
            host = "gfx" if sec in GFX_SECTIONS else "adv"
            if (host, sec) not in cards:
                c, cl = card(SECTION_TITLES.get(sec) or sec or "global")
                self.hosts[host].addWidget(c)
                cards[(host, sec)] = cl
            self.add_field(cards[(host, sec)], sec, key, val, idx)
        for lay in self.hosts.values():
            lay.addStretch()
        self.info.setText("%d OPÇÕES CARREGADAS" % len(self.fields))

    def add_field(self, lay, sec, key, val, idx):
        spec = CURATED.get((sec, key))
        kind, label = (spec[0], spec[1]) if spec else ("entry", key)
        if kind == "slider":
            try:
                lo, hi, f = spec[2], spec[3], float(val)
            except ValueError:
                kind = "entry"
        if kind == "slider":
            init = int(max(0, min(1000, round((f - lo) / (hi - lo) * 1000))))
            s = W.QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 1000)
            s.setValue(init)
            s.setFixedWidth(260)
            out = lbl("%.2f" % (lo + s.value() / 1000 * (hi - lo)), "val")
            out.setFixedWidth(46)
            s.valueChanged.connect(lambda x, o=out, lo=lo, hi=hi:
                                   o.setText("%.2f" % (lo + x / 1000 * (hi - lo))))
            box = W.QHBoxLayout()
            box.addWidget(s)
            box.addWidget(out)
            h = W.QHBoxLayout()
            h.addWidget(lbl(label))
            h.addStretch()
            h.addLayout(box)
            lay.addLayout(h)
            self.fields[idx] = (lambda s=s, init=init, lo=lo, hi=hi, val=val:
                                val.strip() if s.value() == init
                                else "%.6f" % (lo + s.value() / 1000 * (hi - lo)), val)
            return
        if kind == "check":
            w = Switch(val.strip() == "1")
            getter = lambda w=w: "1" if w.isChecked() else "0"
        elif kind == "combo":
            w = W.QComboBox()
            w.addItems(spec[2])
            try:
                w.setCurrentIndex(int(val))
                getter = lambda w=w: str(w.currentIndex())
            except ValueError:
                getter = lambda val=val: val.strip()
        else:
            w = W.QLineEdit(val)
            w.setFixedWidth(200)
            getter = lambda w=w: w.text().strip()
        lay.addLayout(row(label, w))
        self.fields[idx] = (getter, val)

    def save_settings(self, quiet=False):
        changes = {i: g() for i, (g, o) in self.fields.items() if g() != o.strip()}
        if changes:
            save_ini(self.exe().parent / "ac5_settings.ini", self.lines, changes)
        if not quiet:
            self.build_settings()
            self.info.setText("%d ALTERAÇÃO(ÕES) GUARDADA(S)" % len(changes))

    # ---------------- lançar ----------------
    def build_cmd(self):
        cmd = [str(self.exe()), "--data", self.data.text(),
               "--disc", self.iso.text().strip()]
        return cmd + (["--watchdog", "0"] if self.wd.isChecked() else [])

    def refresh_cmd(self):
        if not hasattr(self, "cmd_lbl"):
            return
        pre = ""
        if IS_LINUX:
            pre = ("MANGOHUD=1 " if self.mango.isChecked() else "") + \
                  ("SDL_VIDEO_DRIVER=%s " % self.drv.currentText()
                   if self.drv.currentText() != "auto" else "")
        self.cmd_lbl.setText(pre + " ".join(
            '"%s"' % c if " " in c else c for c in self.build_cmd()))

    def play(self):
        if self.proc:
            self.proc.terminate()
            return
        if not self.ok:
            return
        if not self.exe().is_file():
            W.QMessageBox.critical(self, "Erro", "Executável não encontrado:\n%s"
                                   % self.exe())
            return
        self.save_settings(quiet=True)
        save_cfg({"iso": self.iso.text(), "exe": str(self.exe()),
                  "mango": self.mango.isChecked(), "watchdog_off": self.wd.isChecked(),
                  "driver": self.drv.currentText(), "data": self.data.text()})
        env = QtCore.QProcessEnvironment.systemEnvironment()
        if IS_LINUX and self.mango.isChecked():
            env.insert("MANGOHUD", "1")
        if IS_LINUX and self.drv.currentText() != "auto":
            env.insert("SDL_VIDEO_DRIVER", self.drv.currentText())
        p = QtCore.QProcess(self)
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(str(ROOT))
        p.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        p.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(
            bytes(p.readAll()).decode("utf-8", "replace").rstrip()))
        p.finished.connect(self.on_finished)
        p.errorOccurred.connect(lambda e: self.log.appendPlainText(
            "[erro ao iniciar: %s]" % e))
        self.log.appendPlainText("$ " + self.cmd_lbl.text())
        self.proc = p
        cmd = self.build_cmd()
        p.start(cmd[0], cmd[1:])
        self.play_btn.running = True
        self.play_btn.setText("ABORTAR")
        self.play_btn.update()
        self.stack.setCurrentIndex(3)
        self.navs[3].setChecked(True)

    def on_finished(self, code, _status):
        self.log.appendPlainText("[jogo terminou, código %s]" % code)
        self.proc = None
        self.play_btn.running = False
        self.play_btn.setText("DECOLAR")
        self.check_iso()


def main():
    if QtCore is None:
        print("Falta o Qt6 para Python. Instala com:\n"
              "  Linux (Arch): sudo pacman -S pyside6\n"
              "  Windows/macOS: pip install PySide6")
        sys.exit(1)
    app = W.QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = Launcher()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        print(verify_iso(sys.argv[sys.argv.index("--selftest") + 1]))
    else:
        main()
