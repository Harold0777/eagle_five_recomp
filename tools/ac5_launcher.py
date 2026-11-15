#!/usr/bin/env python3
"""Launcher (Qt6) do Ace Combat 5 Static Recompilation - EAGLE FIVE.

- Escolhe a ISO e verifica (via SYSTEM.CNF) se é o Ace Combat 5 (USA).
- Edita as configurações gráficas do ac5_settings.ini.
- Gerenciamento de cartões de memória (saves) e backups.
- Lança o jogo com os argumentos corretos e console integrado.
"""
import html
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    from PySide6 import QtCore, QtGui, QtWidgets as W
except ImportError:
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets as W
    except ImportError:
        QtCore = QtGui = W = None
Qt = QtCore.Qt if QtCore else None
if W is None:
    class W:  # noqa
        QCheckBox = QMainWindow = QWidget = QFrame = QPushButton = object
        QComboBox = QSpinBox = QDoubleSpinBox = QSlider = QDialog = object

SECTOR = 2048
EXPECTED_SERIAL = "SLUS_208.51"  # Ace Combat 5: The Unsung War (USA)
IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not (IS_WIN or IS_MAC)
PLAT_DIR = "windows" if IS_WIN else "macos" if IS_MAC else "linux"
EXE_NAME = "ac5.exe" if IS_WIN else "ac5"
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
OLD_CFG = Path.home() / ".config" / "ac5-launcher.json"


APPIMAGE_BIN = os.environ.get("AC5_BIN")
GAME_DIR = (Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            / "eagle_five") if APPIMAGE_BIN else None


def backup_root():
    return (GAME_DIR or ROOT) / "backup_saves"


def find_exe():
    if APPIMAGE_BIN and Path(APPIMAGE_BIN).is_file():
        return Path(APPIMAGE_BIN)
    cands = [ROOT, ROOT / "build" / PLAT_DIR]
    if (ROOT / "build").is_dir():
        cands += sorted(p for p in (ROOT / "build").iterdir() if p.is_dir())
    for d in cands:
        if (d / EXE_NAME).is_file():
            return d / EXE_NAME
    return ROOT / "build" / PLAT_DIR / EXE_NAME


# ---------------------------------------------------------------------------
# Verificação da ISO (ISO9660, setores de 2048 bytes)
# ---------------------------------------------------------------------------
def _read_root_file(f, name_wanted):
    f.seek(16 * SECTOR)
    pvd = f.read(SECTOR)
    if len(pvd) < SECTOR or pvd[1:6] != b"CD001":
        raise ValueError("Não é uma ISO9660 válida (sem descritor CD001).")
    root = pvd[156:190]
    lba = int.from_bytes(root[2:6], "little")
    size = int.from_bytes(root[10:14], "little")
    if not 0 < size <= 1 << 20:
        raise ValueError("Diretório raiz da ISO inválido.")
    f.seek(lba * SECTOR)
    data = f.read(size)
    off = 0
    while off + 33 <= len(data):
        rec_len = data[off]
        if rec_len == 0:  # fim do setor: salta para o próximo
            off = (off // SECTOR + 1) * SECTOR
            continue
        name_len = data[off + 32]
        name = data[off + 33:off + 33 + name_len].decode("ascii", "replace")
        if name.split(";")[0].upper() == name_wanted:
            f_lba = int.from_bytes(data[off + 2:off + 6], "little")
            f_size = int.from_bytes(data[off + 10:off + 14], "little")
            f.seek(f_lba * SECTOR)
            return f.read(min(f_size, 4096))
        off += rec_len
    raise ValueError("%s não encontrado na raiz da ISO." % name_wanted)


BOOT2 = re.compile(r"BOOT2\s*=\s*cdrom0:\\?([A-Z]{4})[_-](\d{3})[._]?(\d{2})", re.I)


def verify_iso(path):
    try:
        with open(path, "rb") as f:
            cnf = _read_root_file(f, "SYSTEM.CNF").decode("ascii", "replace")
    except (OSError, ValueError, IndexError) as e:
        return "invalid", None, str(e) or "Falha ao ler a ISO."
    m = BOOT2.search(cnf)
    if not m:
        return "invalid", None, "SYSTEM.CNF sem linha BOOT2 reconhecível."
    serial = "%s_%s.%s" % tuple(g.upper() for g in m.groups())
    if serial == EXPECTED_SERIAL:
        return "ok", serial, "ISO correta: Ace Combat 5 (USA) [%s]" % serial
    return "wrong", serial, ("ISO de outro jogo ou região: %s "
                             "(esperado %s)" % (serial, EXPECTED_SERIAL))


# ---------------------------------------------------------------------------
# Ficheiro .ini
# ---------------------------------------------------------------------------
KV = re.compile(r"^(\s*)([A-Za-z0-9_.\-]+)(\s*[=:]\s*)(.*?)((?:\s+[;#].*)?\s*)$")


def load_ini(path):
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
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
    """Grava só as linhas alteradas, mantendo comentários e fim de linha,
    e de forma atómica (ficheiro temporário + replace)."""
    bak = path.with_name(path.name + ".launcher.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
    eol = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    for idx, value in changes.items():
        m = KV.match(lines[idx])
        if m:
            lines[idx] = "%s%s%s%s%s" % (m.group(1), m.group(2), m.group(3),
                                          value, m.group(5))
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(eol.join(lines) + eol)
    os.replace(tmp, path)


def load_cfg():
    for p in (CFG_FILE, OLD_CFG):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def save_cfg(cfg):
    try:
        CFG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CFG_FILE.with_name(CFG_FILE.name + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        os.replace(tmp, CFG_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Interface Qt6 - EAGLE FIVE HUD Theme
# ---------------------------------------------------------------------------
import glob
import math
import os
import struct

SECTION_TITLES = {"graphics": "Imagem", "postfx": "Pós-processamento",
                  "display": "Janela e tela", "input": "Entrada",
                  "analog": "Analógicos", "keyboard": "Teclado",
                  "controller": "Controle"}
# Aba que mostra cada seção do .ini; seções desconhecidas vão para "adv".
PAGE_SECTIONS = {"graphics": "gfx", "postfx": "gfx", "display": "disp",
                 "input": "ctl", "analog": "ctl", "keyboard": "map",
                 "controller": "map"}
BIND_SECTIONS = ("keyboard", "controller")
BIND_NAMES = {
    "select": "Select", "start": "Start", "l1": "L1", "l2": "L2", "l3": "L3",
    "r1": "R1", "r2": "R2", "r3": "R3",
    "up": "Direcional ↑", "right": "Direcional →", "down": "Direcional ↓",
    "left": "Direcional ←", "triangle": "Triângulo", "circle": "Círculo",
    "cross": "X (cruz)", "square": "Quadrado",
    "lstick_up": "Analógico esq. ↑", "lstick_down": "Analógico esq. ↓",
    "lstick_left": "Analógico esq. ←", "lstick_right": "Analógico esq. →",
    "rstick_up": "Analógico dir. ↑", "rstick_down": "Analógico dir. ↓",
    "rstick_left": "Analógico dir. ←", "rstick_right": "Analógico dir. →",
}
ACTION_ORDER = ["cross", "circle", "square", "triangle", "l1", "l2", "r1", "r2",
                "l3", "r3", "select", "start", "up", "down", "left", "right",
                "lstick_up", "lstick_down", "lstick_left", "lstick_right",
                "rstick_up", "rstick_down", "rstick_left", "rstick_right"]
# (evdev, scancode SDL, nome): o SDL usa os códigos USB HID de teclado
_KEYS = [
    (1, 41, "Esc"), (2, 30, "1"), (3, 31, "2"), (4, 32, "3"), (5, 33, "4"),
    (6, 34, "5"), (7, 35, "6"), (8, 36, "7"), (9, 37, "8"), (10, 38, "9"),
    (11, 39, "0"), (12, 45, "-"), (13, 46, "="), (14, 42, "Backspace"),
    (15, 43, "Tab"), (16, 20, "Q"), (17, 26, "W"), (18, 8, "E"), (19, 21, "R"),
    (20, 23, "T"), (21, 28, "Y"), (22, 24, "U"), (23, 12, "I"), (24, 18, "O"),
    (25, 19, "P"), (26, 47, "["), (27, 48, "]"), (28, 40, "Enter"),
    (29, 224, "Ctrl esq."), (30, 4, "A"), (31, 22, "S"), (32, 7, "D"),
    (33, 9, "F"), (34, 10, "G"), (35, 11, "H"), (36, 13, "J"), (37, 14, "K"),
    (38, 15, "L"), (39, 51, ";"), (40, 52, "'"), (41, 53, "`"),
    (42, 225, "Shift esq."), (43, 49, "\\"), (44, 29, "Z"), (45, 27, "X"),
    (46, 6, "C"), (47, 25, "V"), (48, 5, "B"), (49, 17, "N"), (50, 16, "M"),
    (51, 54, ","), (52, 55, "."), (53, 56, "/"), (54, 229, "Shift dir."),
    (55, 85, "Num *"), (56, 226, "Alt esq."), (57, 44, "Espaço"),
    (58, 57, "Caps Lock"), (59, 58, "F1"), (60, 59, "F2"), (61, 60, "F3"),
    (62, 61, "F4"), (63, 62, "F5"), (64, 63, "F6"), (65, 64, "F7"),
    (66, 65, "F8"), (67, 66, "F9"), (68, 67, "F10"), (69, 83, "Num Lock"),
    (70, 71, "Scroll Lock"), (71, 95, "Num 7"), (72, 96, "Num 8"),
    (73, 97, "Num 9"), (74, 86, "Num -"), (75, 92, "Num 4"), (76, 93, "Num 5"),
    (77, 94, "Num 6"), (78, 87, "Num +"), (79, 89, "Num 1"), (80, 90, "Num 2"),
    (81, 91, "Num 3"), (82, 98, "Num 0"), (83, 99, "Num ."), (86, 100, "< >"),
    (87, 68, "F11"), (88, 69, "F12"), (96, 88, "Num Enter"),
    (97, 228, "Ctrl dir."), (98, 84, "Num /"), (99, 70, "Print Screen"),
    (100, 230, "Alt dir."), (102, 74, "Home"), (103, 82, "Seta ↑"),
    (104, 75, "Page Up"), (105, 80, "Seta ←"), (106, 79, "Seta →"),
    (107, 77, "End"), (108, 81, "Seta ↓"), (109, 78, "Page Down"),
    (110, 73, "Insert"), (111, 76, "Delete"), (119, 72, "Pause"),
    (125, 227, "Meta esq."), (126, 231, "Meta dir."),
]
EVDEV_TO_SDL = {e: s for e, s, _n in _KEYS}
KEY_NAME = {s: n for _e, s, n in _KEYS}
# Controle (SDL3): botão = 1 + SDL_GAMEPAD_BUTTON; eixo = 256 | eixo << 1 | positivo
# (código, nome completo, nome curto)
PAD_INPUTS = [
    (1, "A (Cruz)", "A"), (2, "B (Bola)", "B"), (3, "X (Quadrado)", "X"),
    (4, "Y (Triângulo)", "Y"), (5, "Back / Select", "Back"),
    (6, "Guide / Home", "Guide"), (7, "Start", "Start"),
    (8, "Clique do analógico esquerdo (L3)", "L3"),
    (9, "Clique do analógico direito (R3)", "R3"),
    (10, "LB / L1", "LB"), (11, "RB / R1", "RB"),
    (12, "Direcional ↑", "↑"), (13, "Direcional ↓", "↓"),
    (14, "Direcional ←", "←"), (15, "Direcional →", "→"),
    (256, "Analógico esquerdo ←", "LS ←"), (257, "Analógico esquerdo →", "LS →"),
    (258, "Analógico esquerdo ↑", "LS ↑"), (259, "Analógico esquerdo ↓", "LS ↓"),
    (260, "Analógico direito ←", "RS ←"), (261, "Analógico direito →", "RS →"),
    (262, "Analógico direito ↑", "RS ↑"), (263, "Analógico direito ↓", "RS ↓"),
    (265, "Gatilho esquerdo (LT / L2)", "LT"), (267, "Gatilho direito (RT / R2)", "RT"),
]
PAD_NAME = {c: (n, sn) for c, n, sn in PAD_INPUTS}
PAD_BY_NAME = {n: c for c, n, _sn in PAD_INPUTS}
TRUE_VALUES = ("1", "true", "yes", "on")
DEFAULT_INIS = [ROOT / "ac5_settings.default.ini",
                ROOT / "tools" / "ac5_settings.default.ini"]
# opção -> (opção que a habilita, valores que a habilitam)
DEPENDS = {
    ("display", "aspect_custom"): (("display", "aspect"), ("4",)),
    ("display", "hud_layout"): (("display", "widescreen"), TRUE_VALUES),
}


def page_of(sec):
    return PAGE_SECTIONS.get(sec, "adv")


ANISO = [("Desligado", "1"), ("2x", "2"), ("4x", "4"), ("8x", "8"), ("16x", "16")]
BOOL_STYLES = [("1", "0"), ("true", "false"), ("yes", "no"), ("on", "off")]
# Resolução interna: 0 = automática, N = N x 640x448 (nativa do PS2)
INTERNAL_RES = [("Automática (cobre a janela)", "0")] + [
    ("%dx  ·  %d×%d%s" % (n, 640 * n, 448 * n, " (nativa)" if n == 1 else ""), str(n))
    for n in range(1, 9)]


def _hw(preset, res, tex, aniso, scale, fxaa, sharpen, sat, con, fps):
    return {
        ("graphics", "preset"): str(preset),
        ("graphics", "internal_resolution"): str(res),
        ("graphics", "texture_filter"): str(tex),
        ("graphics", "anisotropy"): str(aniso),
        ("graphics", "scale_filter"): str(scale),
        ("graphics", "deinterlace"): True,
        ("postfx", "fxaa"): fxaa,
        ("postfx", "sharpen"): sharpen,
        ("postfx", "saturation"): sat,
        ("postfx", "contrast"): con,
        ("display", "fps_limit"): fps,
    }


# Presets rápidos só mexem em [postfx]; presets de hardware mexem em várias
# seções. Nada vai para o .ini até clicar em SALVAR (ou DECOLAR).
PRESETS = {
    "original": {"fxaa": 0, "sharpen": 0.0, "saturation": 1.0, "contrast": 1.0},
    "cinematic": {"fxaa": 1, "sharpen": 0.55, "saturation": 1.10, "contrast": 1.05},
    "sharp": {"fxaa": 1, "sharpen": 0.85, "saturation": 1.0},
}
HW_PRESETS = {
    "low": _hw(0, 1, 1, 0, 0, False, 0.0, 1.0, 1.0, "60"),
    "medium": _hw(1, 2, 0, 4, 1, True, 0.55, 1.10, 1.05, "0"),
    "high": _hw(2, 3, 0, 16, 2, True, 0.85, 1.0, 1.0, "0"),
}

# (tipo, rótulo, ...) por (seção, chave)
#   check  | slider lo hi | combo itens | spin lo hi sufixo especial
#   dspin lo hi casas sufixo especial
CURATED = {
    ("graphics", "preset"): ("combo", "Qualidade (preset)", [
        ("Baixa", "0"), ("Média", "1"), ("Alta", "2"), ("Ultra", "3"),
        ("Personalizada", "4")]),
    ("graphics", "internal_resolution"): ("combo", "Resolução interna", INTERNAL_RES),
    ("graphics", "texture_filter"): ("combo", "Filtro de textura", [
        ("Como o jogo pede", "0"), ("Forçar pixelado (nearest)", "1"),
        ("Forçar bilinear", "2")]),
    ("graphics", "anisotropy"): ("combo", "Filtragem anisotrópica", ANISO),
    ("graphics", "deinterlace"): ("check", "Desentrelaçamento (junta os campos)"),
    ("graphics", "scale_filter"): ("combo", "Filtro de escala", [
        ("Pixelado (nearest)", "0"), ("Bilinear", "1"), ("Bilinear nítido", "2")]),
    ("postfx", "fxaa"): ("check", "Anti-aliasing (FXAA)"),
    ("postfx", "sharpen"): ("slider", "Nitidez", 0.0, 1.0),
    ("postfx", "brightness"): ("slider", "Brilho", -0.5, 0.5),
    ("postfx", "contrast"): ("slider", "Contraste", 0.5, 1.5),
    ("postfx", "gamma"): ("slider", "Gama", 0.5, 2.0),
    ("postfx", "saturation"): ("slider", "Saturação", 0.0, 2.0),
    ("display", "window_mode"): ("combo", "Modo de tela", [
        ("Janela", "0"), ("Tela cheia sem bordas", "1"),
        ("Tela cheia exclusiva", "2")]),
    ("display", "fullscreen_type"): ("combo", "Tela cheia ao apertar F11", [
        ("Sem bordas", "1"), ("Exclusiva", "2")]),
    ("display", "window_width"): ("spin", "Largura da janela", 320, 7680, " px", None),
    ("display", "window_height"): ("spin", "Altura da janela", 240, 4320, " px", None),
    ("display", "fullscreen_width"): ("spin", "Largura em tela cheia exclusiva",
                                      0, 7680, " px", "Resolução da área de trabalho"),
    ("display", "fullscreen_height"): ("spin", "Altura em tela cheia exclusiva",
                                       0, 4320, " px", "Resolução da área de trabalho"),
    ("display", "fullscreen_refresh"): ("dspin", "Taxa de atualização (tela cheia)",
                                        0.0, 1000.0, 2, " Hz", "Taxa da área de trabalho"),
    ("display", "aspect"): ("combo", "Proporção da imagem", [
        ("Esticar para a janela", "0"), ("Automática", "1"), ("4:3", "2"),
        ("16:9", "3"), ("Personalizada", "4")]),
    ("display", "aspect_custom"): ("dspin", "Proporção personalizada (larg./alt.)",
                                   0.5, 4.0, 3, "", None),
    ("display", "integer_scale"): ("check", "Escala apenas em números inteiros"),
    ("display", "widescreen"): ("check", "Patch widescreen 16:9"),
    ("display", "hud_layout"): ("combo", "HUD no modo widescreen", [
        ("Esticar", "0"), ("Manter 4:3 centralizado", "1")]),
    ("display", "present_mode"): ("combo", "Sincronização (VSync)", [
        ("Mailbox (baixa latência)", "0"), ("VSync (FIFO)", "1"),
        ("Imediato (sem VSync)", "2"), ("Adaptativo", "3")]),
    ("display", "fps_limit"): ("spin", "Limite de FPS", 0, 1000, " FPS", "Sem limite"),
    ("display", "show_fps"): ("check", "Mostrar FPS na tela"),
    ("display", "menu_scale"): ("slider", "Escala do menu", 0.5, 3.0),
    ("input", "block_game_input_in_menu"): ("check", "Bloquear entrada do jogo nos menus"),
    ("analog", "deadzone"): ("slider", "Zona morta do analógico", 0.0, 1.0),
    ("analog", "axis_scale"): ("slider", "Sensibilidade do analógico", 0.01, 2.0),
    ("analog", "button_deadzone"): ("slider", "Zona morta de botões e gatilhos", 0.0, 1.0),
    ("analog", "invert_left"): ("combo", "Inverter analógico esquerdo", [
        ("Nenhum", "0"), ("Esquerda/direita", "1"), ("Cima/baixo", "2"), ("Ambos", "3")]),
    ("analog", "invert_right"): ("combo", "Inverter analógico direito", [
        ("Nenhum", "0"), ("Esquerda/direita", "1"), ("Cima/baixo", "2"), ("Ambos", "3")]),
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
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#0a0f15; border:1px solid @LINE; border-radius:2px;
    padding:8px 10px; selection-background-color:#7a5410; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color:@AMBER; }
QComboBox::drop-down { border:none; width:24px; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled { color:#4b5a6b; background:#0a0e13; }
QToolTip { background:#101720; color:@TEXT; border:1px solid @LINE; padding:4px; }
QPushButton#bindBtn { background:#0f1722; color:#bae6fd; border:1px solid #243649; border-radius:4px; padding:4px 8px; font-weight:600; }
QPushButton#bindBtn:hover { border-color:#38bdf8; background:#142334; }
QPushButton#bindBtn[active="true"] { border-color:#f59e0b; background:#2b1e0a; color:#fde68a; }
QPushButton#modeTab { background:#0d131b; color:#8ba0b5; border:1px solid #1e2c3a; border-radius:4px; padding:5px 12px; font-weight:700; }
QPushButton#modeTab:hover { border-color:#38bdf8; color:#e0f2fe; }
QPushButton#modeTab[checked="true"] { background:#11293d; border-color:#38bdf8; color:#7dd3fc; }
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
QPushButton#ghost:checked { border-color:@AMBER; color:@AMBER; background:#121b26; }
QTableWidget { background:#0a0f15; border:1px solid @LINE; gridline-color:#16212d; selection-background-color:#7a5410; outline:none; }
QTableWidget::item { padding:4px 8px; }
QHeaderView::section { background:#101720; color:@MUTED; border:none; border-bottom:1px solid @LINE; padding:6px 8px; font-family:@MONO; font-size:11px; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { width:8px; background:transparent; }
QScrollBar::handle:vertical { background:#243142; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""
for _k, _v in PAL.items():
    STYLE = STYLE.replace(_k, _v)


def draw_emblem(p, size):
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
        if not self.isEnabled():
            p.setOpacity(0.35)
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


def truthy(x):
    return str(x).strip().lower() in TRUE_VALUES


def ini_comment(line):
    m = KV.match(line)
    return m.group(5).strip().lstrip(";# ").strip() if m else ""


class _Quiet:
    """Roda do mouse só age no controle com foco (não mexe nos valores ao rolar a página)."""

    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class QuietCombo(_Quiet, W.QComboBox):
    pass


class QuietSpin(_Quiet, W.QSpinBox):
    pass


class QuietDSpin(_Quiet, W.QDoubleSpinBox):
    pass


class QuietSlider(_Quiet, W.QSlider):
    pass


def frow(label, widget, tip=""):
    h = row(label, widget)
    if tip:
        h.itemAt(0).widget().setToolTip(tip)
        widget.setToolTip(tip)
    return h


class Field:
    """Uma opção do .ini ligada ao seu controle."""
    __slots__ = ("sec", "key", "get", "set", "orig", "sig", "ctl")

    def __init__(self, sec, key, get, set_, orig, sig=None, ctl=None):
        self.sec, self.key, self.get, self.set, self.orig = sec, key, get, set_, orig
        self.sig, self.ctl = sig, ctl


_QT_SDL = {}


def key_to_sdl(e):
    """Scancode SDL da tecla pressionada (0 = não reconhecida)."""
    if IS_LINUX:  # código nativo = evdev + 8, independe do layout do teclado
        v = EVDEV_TO_SDL.get(e.nativeScanCode() - 8)
        if v:
            return v
    if not _QT_SDL:
        def kv(name):
            x = getattr(Qt.Key, "Key_" + name)
            return int(getattr(x, "value", x))
        for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            _QT_SDL[kv(ch)] = 4 + i
        for i in range(1, 10):
            _QT_SDL[kv(str(i))] = 29 + i
        _QT_SDL[kv("0")] = 39
        for i in range(1, 13):
            _QT_SDL[kv("F%d" % i)] = 57 + i
        for n, c in (("Return", 40), ("Enter", 88), ("Escape", 41), ("Backspace", 42),
                     ("Tab", 43), ("Space", 44), ("Minus", 45), ("Equal", 46),
                     ("BracketLeft", 47), ("BracketRight", 48), ("Backslash", 49),
                     ("Semicolon", 51), ("Apostrophe", 52), ("QuoteLeft", 53),
                     ("Comma", 54), ("Period", 55), ("Slash", 56), ("Insert", 73),
                     ("Home", 74), ("PageUp", 75), ("Delete", 76), ("End", 77),
                     ("PageDown", 78), ("Right", 79), ("Left", 80), ("Down", 81),
                     ("Up", 82), ("Control", 224), ("Shift", 225), ("Alt", 226),
                     ("Meta", 227)):
            _QT_SDL[kv(n)] = c
    return _QT_SDL.get(int(e.key()), 0)


import ctypes
import ctypes.util


class PadReader:
    """Lê botões e eixos dos controles via SDL3 (ctypes) para capturar um mapeamento."""
    TH = 16000                      # ~50% do curso do eixo
    CODES = [c for c, _n, _s in PAD_INPUTS]
    GAMEPAD = 0x2000                # SDL_INIT_GAMEPAD

    def __init__(self, lib=None):
        self.lib = lib if lib is not None else self._load()
        self.pads, self.armed, self.up = {}, {}, False

    @staticmethod
    def _load():
        c = ctypes
        names = ["libSDL3.so.0", "libSDL3.so", "libSDL3.0.dylib", "SDL3.dll"]
        found = c.util.find_library("SDL3")
        if found:
            names.insert(0, found)
        for n in names:
            try:
                lib = c.CDLL(n)
                lib.SDL_Init.argtypes, lib.SDL_Init.restype = [c.c_uint32], c.c_bool
                lib.SDL_QuitSubSystem.argtypes, lib.SDL_QuitSubSystem.restype = [c.c_uint32], None
                lib.SDL_SetHint.argtypes, lib.SDL_SetHint.restype = [c.c_char_p, c.c_char_p], c.c_bool
                lib.SDL_PumpEvents.restype = None
                lib.SDL_UpdateGamepads.restype = None
                lib.SDL_GetGamepads.argtypes = [c.POINTER(c.c_int)]
                lib.SDL_GetGamepads.restype = c.POINTER(c.c_uint32)
                lib.SDL_free.argtypes, lib.SDL_free.restype = [c.c_void_p], None
                lib.SDL_OpenGamepad.argtypes, lib.SDL_OpenGamepad.restype = [c.c_uint32], c.c_void_p
                lib.SDL_CloseGamepad.argtypes, lib.SDL_CloseGamepad.restype = [c.c_void_p], None
                lib.SDL_GetGamepadButton.argtypes = [c.c_void_p, c.c_int]
                lib.SDL_GetGamepadButton.restype = c.c_bool
                lib.SDL_GetGamepadAxis.argtypes = [c.c_void_p, c.c_int]
                lib.SDL_GetGamepadAxis.restype = c.c_int16
                lib.SDL_GetGamepadName.argtypes, lib.SDL_GetGamepadName.restype = [c.c_void_p], c.c_char_p
                lib.SDL_GetError.restype = c.c_char_p
                return lib
            except (OSError, AttributeError):
                continue
        return None

    def start(self):
        """Devolve "" se deu certo, ou a mensagem do problema."""
        if self.lib is None:
            return "SDL3 não encontrada neste sistema."
        self.lib.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if not self.lib.SDL_Init(self.GAMEPAD):
            err = self.lib.SDL_GetError()
            return "SDL3: " + (err.decode("utf-8", "replace") if err else "falha ao iniciar")
        self.up = True
        self.refresh()
        return ""

    def _active(self, ptr, code):
        if code < 256:
            return bool(self.lib.SDL_GetGamepadButton(ptr, code - 1))
        v = self.lib.SDL_GetGamepadAxis(ptr, (code & 255) >> 1)
        return v > self.TH if code & 1 else v < -self.TH

    def refresh(self):
        lib = self.lib
        lib.SDL_PumpEvents()
        n = ctypes.c_int(0)
        arr = lib.SDL_GetGamepads(ctypes.byref(n))
        ids = [int(arr[i]) for i in range(n.value)] if arr else []
        if arr:
            lib.SDL_free(arr)
        for i in ids:
            if i not in self.pads:
                ptr = lib.SDL_OpenGamepad(i)
                if ptr:
                    self.pads[i] = ptr
                    for code in self.CODES:   # o que já está pressionado só vale depois de soltar
                        self.armed[(i, code)] = not self._active(ptr, code)
        for i in [i for i in self.pads if i not in ids]:
            lib.SDL_CloseGamepad(self.pads.pop(i))

    def names(self):
        return [(self.lib.SDL_GetGamepadName(p) or b"?").decode("utf-8", "replace")
                for p in self.pads.values()]

    def poll(self):
        """Código do primeiro botão/eixo acionado agora (0 = nenhum)."""
        self.lib.SDL_PumpEvents()
        self.lib.SDL_UpdateGamepads()
        hit = 0
        for i, ptr in self.pads.items():
            for code in self.CODES:
                on = self._active(ptr, code)
                if on and self.armed.get((i, code)) and not hit:
                    hit = code
                if not on:
                    self.armed[(i, code)] = True
        return hit

    def stop(self):
        if self.lib is None or not self.up:
            return
        for p in self.pads.values():
            self.lib.SDL_CloseGamepad(p)
        self.pads.clear()
        self.lib.SDL_QuitSubSystem(self.GAMEPAD)
        self.up = False


class PadWidget(W.QWidget):
    """Desenho de um controle (estilo DualShock 2); clique escolhe a ação."""
    DW, DH = 600, 380
    LABELS = {"l1": "L1", "l2": "L2", "r1": "R1", "r2": "R2", "l3": "L3", "r3": "R3",
              "select": "SELECT", "start": "START",
              "up": "▲", "down": "▼", "left": "◀", "right": "▶",
              "lstick_up": "▲", "lstick_down": "▼", "lstick_left": "◀",
              "lstick_right": "▶", "rstick_up": "▲", "rstick_down": "▼",
              "rstick_left": "◀", "rstick_right": "▶"}
    # posição (x, y, alinhamento) da legenda com a entrada atribuída
    CAPS = {"l2": (160, 30, "c"), "r2": (440, 30, "c"), "l1": (105, 89, "r"),
            "r1": (495, 89, "l"), "up": (185, 112, "c"), "down": (185, 218, "c"),
            "left": (138, 165, "r"), "right": (232, 165, "l"),
            "triangle": (436, 128, "l"), "circle": (478, 165, "l"),
            "cross": (415, 232, "c"), "square": (392, 192, "r"),
            "select": (270, 176, "c"), "start": (330, 176, "c"),
            "l3": (240, 282, "c"), "r3": (360, 282, "c")}

    def __init__(self, on_pick):
        super().__init__()
        self.on_pick = on_pick
        self.sel = self.hover = None
        self.caps, self.tips = {}, {}
        self._tf = (0.0, 0.0, 1.0)
        self.setMouseTracking(True)
        self.setMinimumSize(360, 228)
        self.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Expanding)
        P, R = QtCore.QPointF, QtCore.QRectF

        def rr(x, y, w, h, r):
            p = QtGui.QPainterPath()
            p.addRoundedRect(R(x, y, w, h), r, r)
            return p

        def ci(cx, cy, r):
            p = QtGui.QPainterPath()
            p.addEllipse(P(cx, cy), r, r)
            return p

        self.body = QtGui.QPainterPath()
        self.body.addRoundedRect(R(100, 95, 400, 170), 70, 70)
        self.body.addEllipse(P(150, 250), 58, 85)
        self.body.addEllipse(P(450, 250), 58, 85)
        self.body.setFillRule(Qt.FillRule.WindingFill)
        self.body = self.body.simplified()  # une as formas num contorno só
        self.shapes = {
            "l2": rr(115, 40, 90, 34, 8), "l1": rr(110, 78, 100, 22, 8),
            "r1": rr(390, 78, 100, 22, 8), "r2": rr(395, 40, 90, 34, 8),
            "up": rr(173, 123, 24, 30, 4), "down": rr(173, 177, 24, 30, 4),
            "left": rr(143, 153, 30, 24, 4), "right": rr(197, 153, 30, 24, 4),
            "triangle": ci(415, 128, 17), "circle": ci(452, 165, 17),
            "cross": ci(415, 202, 17), "square": ci(378, 165, 17),
            "select": rr(248, 150, 44, 16, 5), "start": rr(308, 150, 44, 16, 5),
            "l3": ci(240, 235, 16), "r3": ci(360, 235, 16),
            "lstick_up": ci(240, 208, 9), "lstick_down": ci(240, 262, 9),
            "lstick_left": ci(213, 235, 9), "lstick_right": ci(267, 235, 9),
            "rstick_up": ci(360, 208, 9), "rstick_down": ci(360, 262, 9),
            "rstick_left": ci(333, 235, 9), "rstick_right": ci(387, 235, 9),
        }

    def sizeHint(self):
        return QtCore.QSize(self.DW, self.DH)

    def _symbol(self, p, a, c, on):
        C, P = QtGui.QColor, QtCore.QPointF
        col = {"triangle": PAL["@GREEN"], "circle": PAL["@RED"],
               "cross": PAL["@CYAN"], "square": "#ff8ad8"}[a]
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(C("#0a0e13" if on else col), 2.2))
        x, y = c.x(), c.y()
        if a == "triangle":
            p.drawPolygon(QtGui.QPolygonF([P(x, y - 8), P(x - 8, y + 6), P(x + 8, y + 6)]))
        elif a == "circle":
            p.drawEllipse(c, 8, 8)
        elif a == "cross":
            p.drawLine(P(x - 7, y - 7), P(x + 7, y + 7))
            p.drawLine(P(x + 7, y - 7), P(x - 7, y + 7))
        else:
            p.drawRect(QtCore.QRectF(x - 7, y - 7, 14, 14))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        s = min(self.width() / self.DW, self.height() / self.DH)
        ox, oy = (self.width() - self.DW * s) / 2, (self.height() - self.DH * s) / 2
        self._tf = (ox, oy, s)
        p.translate(ox, oy)
        p.scale(s, s)
        C = QtGui.QColor
        p.setPen(QtGui.QPen(C("#243142"), 2))
        p.setBrush(C("#0f1620"))
        p.drawPath(self.body)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QtGui.QPen(C("#1d2a38"), 2))
        for cx in (240, 360):
            p.drawEllipse(QtCore.QPointF(cx, 235), 38, 38)
        f = QtGui.QFont()
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        for a, path in self.shapes.items():
            on, hov = a == self.sel, a == self.hover
            p.setPen(QtGui.QPen(C(PAL["@AMBER"] if on or hov else "#2a3b4e"), 1.5))
            p.setBrush(C(PAL["@AMBER"]) if on else C("#243142") if hov else C("#1a2634"))
            p.drawPath(path)
            r = path.boundingRect()
            if a in ("triangle", "circle", "cross", "square"):
                self._symbol(p, a, r.center(), on)
            else:
                p.setPen(C("#0a0e13" if on else PAL["@TEXT"]))
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.LABELS.get(a, a))
        f2 = QtGui.QFont()
        f2.setPixelSize(11)
        p.setFont(f2)
        vc = Qt.AlignmentFlag.AlignVCenter
        for a, (x, y, al) in self.CAPS.items():
            text = self.caps.get(a)
            if text is None:
                continue
            if al == "c":
                rect, fl = QtCore.QRectF(x - 70, y - 8, 140, 16), Qt.AlignmentFlag.AlignHCenter | vc
            elif al == "l":
                rect, fl = QtCore.QRectF(x, y - 8, 130, 16), Qt.AlignmentFlag.AlignLeft | vc
            else:
                rect, fl = QtCore.QRectF(x - 130, y - 8, 130, 16), Qt.AlignmentFlag.AlignRight | vc
            p.setPen(C(PAL["@CYAN"] if text != "—" else "#4b5a6b"))
            p.drawText(rect, fl, text)

    def _hit(self, pos):
        ox, oy, s = self._tf
        pt = QtCore.QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)
        for a, path in self.shapes.items():
            if path.contains(pt):
                return a
        return None

    def mouseMoveEvent(self, e):
        a = self._hit(e.position())
        if a != self.hover:
            self.hover = a
            self.setToolTip(self.tips.get(a, "") if a else "")
            self.setCursor(Qt.CursorShape.PointingHandCursor if a else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            a = self._hit(e.position())
            if a:
                self.sel = a
                self.on_pick(a)


class MappingEditor(W.QWidget):
    """Editor de teclado/controle: desenho clicável + tabela de ações."""

    def __init__(self, binds, on_change):
        super().__init__()
        self.on_change = on_change
        self.data = {"keyboard": {}, "controller": {}}
        for sec, items in binds.items():
            if sec not in self.data:
                continue
            for key, _c, idx, val in items:
                try:
                    nums = [int(x) for x in val.split()[:2]]
                except ValueError:
                    continue
                if nums:
                    nums = (nums + [0])[:2]
                    self.data[sec][key] = {"idx": idx, "vals": nums, "orig": tuple(nums)}
        seen = [a for a in ACTION_ORDER if any(a in d for d in self.data.values())]
        extra = sorted({a for d in self.data.values() for a in d} - set(seen))
        self.actions = seen + extra
        self.mode = "keyboard" if self.data["keyboard"] else "controller"
        self.cap = None
        self.reader, self.hint, self.ticks = None, "", 0
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.tick)
        self.sel = self.actions[0] if self.actions else None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root = W.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        top = W.QHBoxLayout()
        top.addWidget(lbl("MAPEAR:", "tag"))
        self.mode_btns = {}
        for m, text in (("keyboard", "TECLADO"), ("controller", "CONTROLE")):
            b = ghost(text, lambda _=False, m=m: self.set_mode(m))
            b.setCheckable(True)
            self.mode_btns[m] = b
            top.addWidget(b)
        top.addStretch()
        root.addLayout(top)

        body = W.QHBoxLayout()
        body.setSpacing(16)
        self.pad = PadWidget(self.pick)
        body.addWidget(self.pad, 3)
        right = W.QVBoxLayout()
        t = W.QTableWidget(len(self.actions), 3)
        t.setHorizontalHeaderLabels(["Ação", "Principal", "Secundária"])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        t.horizontalHeader().setSectionResizeMode(0, W.QHeaderView.ResizeMode.ResizeToContents)
        for c in (1, 2):
            t.horizontalHeader().setSectionResizeMode(c, W.QHeaderView.ResizeMode.Stretch)
        t.setMinimumSize(300, 340)
        t.cellClicked.connect(self.cell_clicked)
        self.table = t
        right.addWidget(t, 1)
        br = W.QHBoxLayout()
        br.addWidget(lbl("DEFINIR:", "tag"))
        br.addWidget(ghost("PRINCIPAL", lambda: self.begin(self.sel, 0)))
        br.addWidget(ghost("SECUNDÁRIA", lambda: self.begin(self.sel, 1)))
        br.addStretch()
        right.addLayout(br)
        br2 = W.QHBoxLayout()
        br2.addWidget(ghost("LIMPAR", self.clear_sel))
        br2.addWidget(ghost("LISTA…", self.list_sel))
        br2.addStretch()
        right.addLayout(br2)
        body.addLayout(right, 2)
        root.addLayout(body)
        self.status = lbl("", "muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.refresh()

    # ---------- nomes e conflitos ----------
    def code_name(self, code, short=False):
        if not code:
            return "—"
        if self.mode == "keyboard":
            return KEY_NAME.get(code, "Tecla #%d" % code)
        n = PAD_NAME.get(code)
        return (n[1] if short else n[0]) if n else "Código %d" % code

    def conflicts(self, mode):
        used = {}
        for a, e in self.data[mode].items():
            for c in set(e["vals"]):
                if c:
                    used.setdefault(c, []).append(a)
        return {c: acts for c, acts in used.items() if len(acts) > 1}

    # ---------- exibição ----------
    def refresh(self):
        d, dup, t = self.data[self.mode], self.conflicts(self.mode), self.table
        red, amber = QtGui.QBrush(QtGui.QColor(PAL["@RED"])), QtGui.QBrush(QtGui.QColor(PAL["@AMBER"]))
        caps, tips = {}, {}
        for r, a in enumerate(self.actions):
            name = BIND_NAMES.get(a, a)
            t.setItem(r, 0, W.QTableWidgetItem(name))
            e = d.get(a)
            for slot in (0, 1):
                if e is None:
                    text = "—"
                elif self.cap == (a, slot):
                    text = "Pressione uma tecla…"
                else:
                    text = self.code_name(e["vals"][slot])
                it = W.QTableWidgetItem(text)
                it.setToolTip(text)
                if self.cap == (a, slot):
                    it.setForeground(amber)
                elif e is not None and e["vals"][slot] in dup:
                    it.setForeground(red)
                t.setItem(r, 1 + slot, it)
            if e is None:
                tips[a] = name + "\n(sem entrada neste modo)"
                continue
            short = [self.code_name(c, True) for c in e["vals"] if c]
            caps[a] = " · ".join(short) if short else "—"
            tips[a] = "%s\nPrincipal: %s\nSecundária: %s" % (
                name, self.code_name(e["vals"][0]), self.code_name(e["vals"][1]))
        self.pad.caps, self.pad.tips, self.pad.sel = caps, tips, self.sel
        self.pad.update()
        for m, b in self.mode_btns.items():
            b.setChecked(m == self.mode)
        if self.sel in self.actions:
            t.selectRow(self.actions.index(self.sel))
        if self.cap:
            a, slot = self.cap
            what = "a tecla" if self.mode == "keyboard" else "um botão (ou mova um analógico) no controle"
            msg = ("Pressione %s para «%s» (%s). Esc cancela%s."
                   % (what, BIND_NAMES.get(a, a), "principal" if slot == 0 else "secundária",
                      ", Delete limpa" if self.mode == "keyboard" else ""))
            if self.hint:
                msg += "  " + self.hint
        elif dup:
            msg = "Atenção: %s usado em mais de uma ação (em vermelho)." % ", ".join(
                self.code_name(c) for c in dup)
        elif self.sel:
            msg = ("Selecionado: %s. Clique numa célula da tabela, ou use DEFINIR."
                   % BIND_NAMES.get(self.sel, self.sel))
            if self.hint:
                msg += "  " + self.hint
        else:
            msg = "Sem ações de mapeamento no .ini."
        self.status.setText(msg)

    # ---------- interação ----------
    def set_mode(self, m):
        if not self.data.get(m):
            self.refresh()
            return
        self.cancel(False)
        self.hint = ""
        self.mode = m
        self.refresh()

    def pick(self, action):
        self.cancel(False)
        self.hint = ""
        self.sel = action
        self.refresh()

    def cell_clicked(self, row, col):
        a = self.actions[row]
        if col == 0:
            self.pick(a)
        else:
            self.begin(a, col - 1)

    def begin(self, action, slot):
        if not action:
            return
        self.cancel(False)
        self.sel = action
        e = self.data[self.mode].get(action)
        if e is None:
            self.refresh()
            return
        if self.mode == "keyboard":
            self.cap = (action, slot)
            self.refresh()
            self.setFocus()
            self.grabKeyboard()
            return
        rd = PadReader()
        err = rd.start()
        if err:
            self.hint = err + " Escolha na lista."
            self.begin_list(action, slot)
            return
        self.hint, self.ticks, self.reader = "", 0, rd
        self.cap = (action, slot)
        self.refresh()
        self.setFocus()
        self.timer.start()

    def tick(self):
        rd = self.reader
        if rd is None or not self.cap:
            self.timer.stop()
            return
        self.ticks += 1
        if self.ticks % 15 == 0:
            rd.refresh()
        code = rd.poll()
        if code:
            action, slot = self.cap
            self.assign(action, slot, code)
        elif rd.pads and not self.hint:
            self.hint = "Controle: " + ", ".join(rd.names())
            self.refresh()
        elif self.ticks == 90 and not rd.pads:
            self.hint = "Nenhum controle reconhecido. Conecte um ou use LISTA…"
            self.refresh()
        elif self.ticks > 900:
            self.hint = "Tempo esgotado."
            self.cancel()

    def list_sel(self):
        if self.mode != "controller":
            self.hint = "A lista serve só para o controle; no teclado, aperte a tecla."
            self.refresh()
            return
        self.begin_list(self.sel, self.cap[1] if self.cap else 0)

    def begin_list(self, action, slot):
        e = self.data[self.mode].get(action) if action else None
        if e is None:
            return
        self.cancel(False)
        items = ["— Nenhum —"] + [n for _c, n, _s in PAD_INPUTS]
        cur = PAD_NAME.get(e["vals"][slot])
        name, ok = W.QInputDialog.getItem(
            self, "Mapear controle",
            "%s (%s):" % (BIND_NAMES.get(action, action),
                          "principal" if slot == 0 else "secundária"),
            items, items.index(cur[0]) if cur else 0, False)
        if ok:
            self.assign_pad(action, slot, name)
        else:
            self.refresh()

    def assign_pad(self, action, slot, name):
        self.assign(action, slot, PAD_BY_NAME.get(name, 0))

    def assign(self, action, slot, code):
        e = self.data[self.mode].get(action)
        if e is None:
            return
        self.cancel(False)
        e["vals"][slot] = code
        self.refresh()
        self.on_change()

    def clear_sel(self):
        e = self.data[self.mode].get(self.sel)
        if e is not None:
            self.cancel(False)
            e["vals"] = [0, 0]
            self.refresh()
            self.on_change()

    def cancel(self, refresh=True):
        if self.cap:
            if self.mode == "keyboard":
                self.releaseKeyboard()
            self.cap = None
            self.timer.stop()
            if self.reader:
                self.reader.stop()
                self.reader = None
            if refresh:
                self.refresh()

    def event(self, e):
        if self.cap and e.type() == QtCore.QEvent.Type.KeyPress:
            if self.mode == "keyboard":
                if not e.isAutoRepeat():
                    self.on_key(e)
                return True
            if int(e.key()) == int(getattr(Qt.Key.Key_Escape, "value", Qt.Key.Key_Escape)):
                self.cancel()
                return True
        return super().event(e)

    def on_key(self, e):
        action, slot = self.cap
        if int(e.key()) == int(getattr(Qt.Key.Key_Escape, "value", Qt.Key.Key_Escape)):
            self.cancel()
            return
        if int(e.key()) == int(getattr(Qt.Key.Key_Delete, "value", Qt.Key.Key_Delete)):
            self.assign(action, slot, 0)
            return
        code = key_to_sdl(e)
        if not code:
            self.status.setText("Tecla não reconhecida, tente outra (Esc cancela).")
            return
        self.assign(action, slot, code)

    # ---------- salvar / padrões ----------
    def changes(self):
        out = {}
        for d in self.data.values():
            for e in d.values():
                if tuple(e["vals"]) != e["orig"]:
                    out[e["idx"]] = "%d   %d" % tuple(e["vals"])
        return out

    def load_defaults(self, defaults):
        self.cancel(False)
        for sec, d in self.data.items():
            for a, e in d.items():
                raw = defaults.get((sec, a))
                if raw is None:
                    continue
                try:
                    nums = [int(x) for x in raw.split()[:2]]
                except ValueError:
                    continue
                if nums:
                    e["vals"] = (nums + [0])[:2]
        self.refresh()
        self.on_change()


class Launcher(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EAGLE FIVE - Ace Combat 5 Launcher")
        self.resize(1080, 700)
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
        self.infos = []  # um rótulo de estado por página de definições

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
                 ("03  TELA", self.page_settings("03 // EXIBIÇÃO", "Janela e tela", "disp")),
                 ("04  CONTROLES", self.page_settings("04 // ENTRADA", "Controles", "ctl")),
                 ("05  MAPEAMENTO", self.page_settings("05 // ENTRADA", "Mapeamento", "map")),
                 ("06  AVANÇADO", self.page_settings("06 // SISTEMA", "Avançado", "adv")),
                 ("07  CONSOLE", self.page_console())]
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
        foot = lbl("ARRASTE A ISO PARA\nA JANELA  ·  %s" % PLAT_DIR.upper(), "muted", 1)
        foot.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(foot)
        h.addWidget(side)
        h.addWidget(self.stack, 1)

        self.build_settings()
        self.refresh_cmd()
        self.check_iso()

    # ---------------- utilitários ----------------
    def notify(self, text):
        for lab in self.infos:
            lab.setText(text)

    def goto(self, i):
        self.stack.setCurrentIndex(i)
        self.navs[i].setChecked(True)

    def persist_cfg(self):
        save_cfg({"iso": self.iso.text().strip(), "exe": str(self.exe()),
                  "mango": self.mango.isChecked(), "watchdog_off": self.wd.isChecked(),
                  "driver": self.drv.currentText(), "data": self.data.text().strip()})

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
        self.iso.setPlaceholderText("Escolha ou arraste a ISO do jogo…")
        # debounce: não abre a ISO a cada tecla digitada
        self.iso_timer = QtCore.QTimer(self)
        self.iso_timer.setSingleShot(True)
        self.iso_timer.setInterval(250)
        self.iso_timer.timeout.connect(self.check_iso)
        self.iso.textChanged.connect(lambda _t: self.iso_timer.start())
        r.addWidget(self.iso, 1)
        r.addWidget(ghost("PROCURAR", self.browse))
        cl.addLayout(r)
        self.st_title = lbl("", "readout")
        self.st_detail = lbl("", "muted")
        cl.addWidget(self.st_title)
        cl.addWidget(self.st_detail)
        v.addWidget(c)

        c2, c2l = card("Inicialização")
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
        if IS_LINUX:
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

    _loading = False

    def page_settings(self, tag, title, key):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 22)
        v.addLayout(header(tag, title))

        if key == "gfx":
            hbar = W.QHBoxLayout()
            hbar.addWidget(lbl("PRESET DE HARDWARE:", "tag"))
            hbar.addWidget(ghost("BAIXO", lambda: self.apply_hw_preset("low")))
            hbar.addWidget(ghost("MÉDIO", lambda: self.apply_hw_preset("medium")))
            hbar.addWidget(ghost("ALTO", lambda: self.apply_hw_preset("high")))
            hbar.addStretch()
            v.addLayout(hbar)

            pbar = W.QHBoxLayout()
            pbar.addWidget(lbl("PRESET RÁPIDO:", "tag"))
            pbar.addWidget(ghost("Original", lambda: self.apply_preset("original")))
            pbar.addWidget(ghost("Cinematográfico", lambda: self.apply_preset("cinematic")))
            pbar.addWidget(ghost("Nitidez Máxima", lambda: self.apply_preset("sharp")))
            pbar.addStretch()
            v.addLayout(pbar)

        area = W.QScrollArea()
        area.setWidgetResizable(True)
        inner = W.QWidget()
        lay = W.QVBoxLayout(inner)
        lay.setContentsMargins(0, 10, 10, 10)
        lay.setSpacing(16)
        area.setWidget(inner)
        v.addWidget(area, 1)
        self.hosts[key] = lay

        if key == "adv":
            sc, scl = card("Dados e pastas")
            scl.addWidget(lbl("Backup e restauração dos cartões de memória "
                              "(saves/*.ps2mc) e atalhos para as pastas.", "muted"))
            r1 = W.QHBoxLayout()
            r1.addWidget(ghost("FAZER BACKUP DOS SAVES", self.backup_save))
            r1.addWidget(ghost("RESTAURAR BACKUP", self.restore_save))
            r1.addStretch()
            r2 = W.QHBoxLayout()
            r2.addWidget(ghost("ABRIR SAVES", lambda: self.open_folder("saves")))
            r2.addWidget(ghost("ABRIR CAPTURAS (OUT)", lambda: self.open_folder("out")))
            r2.addWidget(ghost("ABRIR PASTA DO JOGO", lambda: self.open_folder("")))
            r2.addStretch()
            scl.addLayout(r1)
            scl.addLayout(r2)
            lay.addWidget(sc)

        bar = W.QHBoxLayout()
        info = lbl("", "muted")
        self.infos.append(info)
        bar.addWidget(info)
        bar.addStretch()
        bar.addWidget(ghost("DESCARTAR", self.build_settings))
        bar.addWidget(ghost("PADRÕES", lambda _=False, k=key: self.restore_defaults(k)))
        bar.addWidget(ghost("SALVAR", lambda: self.save_settings()))
        v.addLayout(bar)
        return page

    def page_console(self):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 22)
        v.addLayout(header("07 // TELEMETRIA", "Console"))
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
            self.check_iso()
            self.goto(0)

    def browse(self):
        cur = self.iso.text().strip()
        start = str(Path(cur).parent) if cur else str(Path.home() / "Downloads")
        p, _ = W.QFileDialog.getOpenFileName(
            self, "Escolher ISO do Ace Combat 5", start,
            "Imagens de disco (*.iso *.ISO);;Todos (*)")
        if p:
            self.iso.setText(p)
            self.check_iso()

    def set_status(self, color, text):
        self.st_title.setText('<span style="color:%s">■</span>&nbsp; %s'
                              % (color, html.escape(text)))

    def check_iso(self):
        self.iso_timer.stop()
        p = self.iso.text().strip()
        self.st_detail.setText("")
        if not p:
            self.ok = False
            self.set_status(PAL["@MUTED"], "AGUARDANDO ISO")
        elif not os.path.isfile(p):
            self.ok = False
            self.set_status(PAL["@RED"], "ARQUIVO NÃO ENCONTRADO")
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

    # ---------------- saves e pastas ----------------
    def saves_dir(self):
        return (GAME_DIR or self.exe().parent) / "saves"

    def backup_save(self):
        if self.proc:
            W.QMessageBox.warning(self, "Aviso", "Feche o jogo antes de fazer backup dos saves.")
            return
        cards = sorted(self.saves_dir().glob("*.ps2mc"))
        if not cards:
            W.QMessageBox.warning(self, "Aviso", "Nenhum cartão (*.ps2mc) encontrado na pasta saves/ do jogo.")
            return
        backup_dir = backup_root()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            for c in cards:
                dest = backup_dir / ("%s_%s.ps2mc" % (c.stem, ts))
                shutil.copy2(c, dest)
                self.log.appendPlainText("[save] Backup criado: %s" % dest)
        except OSError as e:
            W.QMessageBox.critical(self, "Erro", "Falha no backup:\n%s" % e)
            return
        W.QMessageBox.information(self, "Sucesso", "%d cartão(ões) copiado(s) para:\n%s"
                                  % (len(cards), backup_dir))

    def restore_save(self):
        if self.proc:
            W.QMessageBox.warning(self, "Aviso", "Feche o jogo antes de restaurar saves.")
            return
        backup_dir = backup_root()
        src, _ = W.QFileDialog.getOpenFileName(
            self, "Escolher backup para restaurar", str(backup_dir),
            "Cartão de memória (*.ps2mc)")
        if not src:
            return
        src = Path(src)
        m = re.match(r"^(.*)_\d{8}_\d{6}$", src.stem)
        target = self.saves_dir() / ((m.group(1) if m else "card0") + ".ps2mc")
        if W.QMessageBox.question(
                self, "Restaurar backup",
                "Substituir %s por %s?\n\nO arquivo atual será salvo antes."
                % (target.name, src.name)) != W.QMessageBox.StandardButton.Yes:
            return
        try:
            self.saves_dir().mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(target, backup_dir / ("%s_%s_antes-restauro.ps2mc" % (target.stem, ts)))
            shutil.copy2(src, target)
        except OSError as e:
            W.QMessageBox.critical(self, "Erro", "Falha ao restaurar:\n%s" % e)
            return
        self.log.appendPlainText("[save] Restaurado %s -> %s" % (src.name, target))
        self.notify("SAVE RESTAURADO: %s" % target.name)

    def open_folder(self, rel_path):
        base = GAME_DIR or self.exe().parent
        if not base.is_dir():
            W.QMessageBox.warning(self, "Aviso", "Pasta do jogo não encontrada:\n%s" % base)
            return
        p = base / rel_path if rel_path else base
        p.mkdir(exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(p)))

    # ---------------- definições ----------------
    def exe(self):
        if APPIMAGE_BIN:
            return Path(APPIMAGE_BIN)
        return Path(self.exe_edit.text().strip())

    bind_mode = "controller"
    selected_bind_key = "cross"
    bind_entries = {}       # (sec, key) -> dict(idx, codes, comment_prefix, buttons)
    bind_code_names = {}    # sec -> {int_code: label}
    bind_unbound = {"keyboard": 0, "controller": -1}
    ds_widget = None
    bind_mode_btns = {}

    map_editor = None

    def on_map_changed(self):
        if not self._loading:
            self.notify("ALTERAÇÕES PENDENTES // CLIQUE EM SALVAR")

    def apply_preset(self, name):
        values = PRESETS[name]
        n = 0
        self._loading = True
        try:
            for f in self.fields.values():
                if f.sec == "postfx" and f.key in values and f.set:
                    f.set(values[f.key])
                    n += 1
        finally:
            self._loading = False
        self.apply_deps()
        self.notify(("PRESET '%s' CARREGADO // CLIQUE EM SALVAR PARA APLICAR" % name.upper())
                    if n else "SEM OPÇÕES [postfx] NO .INI (rode o jogo uma vez)")

    def apply_hw_preset(self, name):
        values = HW_PRESETS.get(name)
        if not values:
            return
        n = 0
        self._loading = True
        try:
            for f in self.fields.values():
                if (f.sec, f.key) in values and f.set:
                    try:
                        f.set(values[(f.sec, f.key)])
                        n += 1
                    except (ValueError, TypeError):
                        pass
        finally:
            self._loading = False
        self.apply_deps()
        self.notify(("PRESET DE HARDWARE '%s' CARREGADO // CLIQUE EM SALVAR PARA APLICAR"
                     % name.upper()) if n
                    else "SEM CHAVES CORRESPONDENTES NO .INI (rode o jogo uma vez)")

    def apply_deps(self):
        by = {(f.sec, f.key): f for f in self.fields.values()}
        for tgt, (src, vals) in DEPENDS.items():
            if tgt in by and src in by:
                by[tgt].ctl.setEnabled(by[src].get().strip().lower() in vals)

    def on_field_changed(self, f):
        if self._loading:
            return
        self.apply_deps()
        if f.sec == "graphics" and f.key != "preset":
            # mexeu numa opção de imagem: o preset deixa de valer
            p = next((x for x in self.fields.values()
                      if (x.sec, x.key) == ("graphics", "preset")), None)
            if p and p.get() != "4":
                self._loading = True
                try:
                    p.set("4")
                finally:
                    self._loading = False
        self.notify("ALTERAÇÕES PENDENTES // CLIQUE EM SALVAR")

    def restore_defaults(self, page):
        path = next((p for p in DEFAULT_INIS if p.is_file()), None)
        if not path:
            self.notify("ARQUIVO DE PADRÕES NÃO ENCONTRADO")
            return
        try:
            _lines, entries = load_ini(path)
        except OSError as e:
            self.notify("Erro ao ler os padrões: %s" % e)
            return
        defaults = {(s, k): v.strip() for _i, s, k, v in entries}
        n = 0
        self._loading = True
        try:
            for f in self.fields.values():
                d = defaults.get((f.sec, f.key))
                if page_of(f.sec) == page and d is not None:
                    try:
                        f.set(d)
                        n += 1
                    except (ValueError, TypeError):
                        pass
        finally:
            self._loading = False
        if page == "map" and self.map_editor:
            self.map_editor.load_defaults(defaults)
            n += 1
        self.apply_deps()
        self.notify("%d PADRÕES CARREGADOS // CLIQUE EM SALVAR PARA APLICAR" % n)

    def build_settings(self):
        self._loading = True
        try:
            self._build_settings()
        finally:
            self._loading = False

    def _build_settings(self):
        self.map_editor = None
        for key, lay in self.hosts.items():
            if key == "adv":  # preserva o cartão de saves (índice 0)
                while lay.count() > 1:
                    it = lay.takeAt(1)
                    if it.widget():
                        it.widget().deleteLater()
            else:
                clear(lay)
        self.fields.clear()
        ini = (GAME_DIR or self.exe().parent) / "ac5_settings.ini"
        if not ini.is_file():
            self.notify("SEM ac5_settings.ini EM %s (rode o jogo uma vez)" % ini)
            return
        try:
            self.lines, entries = load_ini(ini)
        except OSError as e:
            self.notify("Erro ao ler o .ini: %s" % e)
            return
        cards, binds = {}, {}
        for idx, sec, key, val in entries:
            comment = ini_comment(self.lines[idx])
            if sec in BIND_SECTIONS:
                binds.setdefault(sec, []).append((key, comment, idx, val))
                continue
            host = page_of(sec)
            if (host, sec) not in cards:
                c, cl = card(SECTION_TITLES.get(sec) or sec or "global")
                self.hosts[host].addWidget(c)
                cards[(host, sec)] = cl
            self.add_field(cards[(host, sec)], sec, key, val, idx, comment)
        self.add_mapping_editor(binds)
        for k in self.hosts:
            self.hosts[k].addStretch()
        self.apply_deps()
        self.notify("%d OPÇÕES CARREGADAS" % len(self.fields))

    def add_mapping_editor(self, binds):
        c, cl = card("Mapeamento de entrada")
        if binds:
            self.map_editor = MappingEditor(binds, self.on_map_changed)
            cl.addWidget(self.map_editor)
        else:
            cl.addWidget(lbl("Sem seções [keyboard] ou [controller] no .ini.", "muted"))
        self.hosts["map"].addWidget(c)

    def add_field(self, lay, sec, key, val, idx, comment=""):
        spec = CURATED.get((sec, key))
        kind, label = (spec[0], spec[1]) if spec else ("entry", key)
        raw = val.strip()
        tip = "%s.%s" % (sec, key) + (" — %s" % comment if comment else "")
        if kind == "slider":
            lo, hi = spec[2], spec[3]
            try:
                f0 = float(raw)
            except ValueError:
                kind = "entry"

        if kind == "slider":
            def to_pos(x, lo=lo, hi=hi):
                return int(max(0, min(1000, round((x - lo) / (hi - lo) * 1000))))

            def to_val(p, lo=lo, hi=hi):
                return lo + p / 1000 * (hi - lo)

            init = to_pos(f0)
            s = QuietSlider(Qt.Orientation.Horizontal)
            s.setRange(0, 1000)
            s.setValue(init)
            s.setFixedWidth(260)
            out = lbl("%.2f" % to_val(init), "val")
            out.setFixedWidth(46)
            s.valueChanged.connect(lambda x, o=out: o.setText("%.2f" % to_val(x)))
            w = W.QWidget()
            hb = W.QHBoxLayout(w)
            hb.setContentsMargins(0, 0, 0, 0)
            hb.addWidget(s)
            hb.addWidget(out)
            get = lambda: raw if s.value() == init else "%.6f" % to_val(s.value())
            set_ = lambda x: s.setValue(to_pos(float(x)))
            sig = s.valueChanged
        elif kind == "check":
            low = raw.lower()
            style = next((st for st in BOOL_STYLES if low in st), BOOL_STYLES[0])
            was_on = low == style[0]
            w = Switch(was_on)
            get = lambda: (raw if w.isChecked() == was_on
                           else style[0] if w.isChecked() else style[1])
            set_ = lambda x: w.setChecked(truthy(x))
            sig = w.toggled
        elif kind == "combo":
            w = QuietCombo()
            for disp, data in spec[2]:
                w.addItem(disp, data)
            i = w.findData(raw)
            if i < 0:
                # valor fora da lista: mantém-no em vez de o trocar em silêncio
                w.addItem("Personalizado (%s)" % raw, raw)
                i = w.count() - 1
            w.setCurrentIndex(i)
            get = lambda: str(w.currentData())

            def set_(x, w=w):
                j = w.findData(str(x))
                if j >= 0:
                    w.setCurrentIndex(j)
            sig = w.currentIndexChanged
        elif kind == "spin":
            lo, hi, suffix, special = spec[2:6]
            w = QuietSpin()
            w.setRange(lo, hi)
            w.setButtonSymbols(W.QAbstractSpinBox.ButtonSymbols.NoButtons)
            if suffix:
                w.setSuffix(suffix)
            if special:
                w.setSpecialValueText(special)
            try:
                w.setValue(int(float(raw)))
            except ValueError:
                pass
            init = w.value()
            w.setFixedWidth(240)
            get = lambda: raw if w.value() == init else str(w.value())
            set_ = lambda x: w.setValue(int(float(x)))
            sig = w.valueChanged
        elif kind == "dspin":
            lo, hi, dec, suffix, special = spec[2:7]
            w = QuietDSpin()
            w.setRange(lo, hi)
            w.setDecimals(dec)
            w.setButtonSymbols(W.QAbstractSpinBox.ButtonSymbols.NoButtons)
            if suffix:
                w.setSuffix(suffix)
            if special:
                w.setSpecialValueText(special)
            try:
                w.setValue(float(raw))
            except ValueError:
                pass
            init = w.value()
            w.setFixedWidth(240)
            get = lambda: raw if w.value() == init else "%.6f" % w.value()
            set_ = lambda x: w.setValue(float(x))
            sig = w.valueChanged
        else:
            w = W.QLineEdit(val)
            w.setFixedWidth(200)
            get = lambda: w.text().strip()
            set_ = lambda x: w.setText(str(x))
            sig = w.textChanged
        lay.addLayout(frow(label, w, tip))
        f = Field(sec, key, get, set_, val, sig, w)
        self.fields[idx] = f
        sig.connect(lambda *_a, f=f: self.on_field_changed(f))

    def save_settings(self, quiet=False):
        changes = {}
        for i, f in self.fields.items():
            new = f.get()
            if new != f.orig.strip():
                changes[i] = new
        if self.map_editor:
            changes.update(self.map_editor.changes())
        if changes:
            try:
                save_ini((GAME_DIR or self.exe().parent) / "ac5_settings.ini",
                         self.lines, changes)
            except OSError as e:
                W.QMessageBox.critical(self, "Erro", "Não foi possível salvar o .ini:\n%s" % e)
                return False
        if not quiet:
            self.build_settings()
            self.notify("%d ALTERAÇÃO(ÕES) SALVA(S)" % len(changes))
        return True

    # ---------------- lançar ----------------
    def build_cmd(self):
        cmd = [str(self.exe())]
        data = self.data.text().strip()
        if data:
            cmd += ["--data", data]
        cmd += ["--disc", self.iso.text().strip()]
        return cmd + (["--watchdog", "0"] if self.wd.isChecked() else [])

    def extra_env(self):
        env = {}
        if IS_LINUX and self.mango.isChecked():
            env["MANGOHUD"] = "1"
        if IS_LINUX and self.drv.currentText() != "auto":
            # SDL2 lê SDL_VIDEODRIVER, SDL3 lê SDL_VIDEO_DRIVER: define ambas
            env["SDL_VIDEODRIVER"] = env["SDL_VIDEO_DRIVER"] = self.drv.currentText()
        return env

    def refresh_cmd(self):
        if not hasattr(self, "cmd_lbl"):
            return
        cmd = self.build_cmd()
        line = subprocess.list2cmdline(cmd) if IS_WIN else shlex.join(cmd)
        pre = "".join("%s=%s " % kv for kv in self.extra_env().items())
        self.cmd_lbl.setText(pre + line)

    def ensure_image(self):
        data = Path(self.data.text().strip() or "generated")
        if not data.is_absolute():
            data = (GAME_DIR or ROOT) / data
        if (data / "ps2_image.bin").is_file():
            return
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import make_image
        self.log.appendPlainText("Gerando ps2_image.bin a partir da ISO...")
        out, _base, size = make_image.build_image(self.iso.text().strip(), data)
        self.log.appendPlainText("ps2_image.bin criado: %s (%d bytes)" % (out, size))

    def play(self):
        if self.proc:
            self.stop_game()
            return
        if not self.ok:
            return
        if not self.exe().is_file():
            W.QMessageBox.critical(self, "Erro", "Executável não encontrado:\n%s"
                                   % self.exe())
            return
        if not self.save_settings(quiet=True):
            return
        try:
            self.ensure_image()
        except Exception as e:
            W.QMessageBox.critical(self, "Erro", "Não foi possível gerar o ps2_image.bin:\n%s" % e)
            return
        self.persist_cfg()
        env = QtCore.QProcessEnvironment.systemEnvironment()
        for k, v in self.extra_env().items():
            env.insert(k, v)
        p = QtCore.QProcess(self)
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(str(GAME_DIR or ROOT))
        p.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        p.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(
            bytes(p.readAll()).decode("utf-8", "replace").rstrip()))
        p.finished.connect(lambda code, status: self.on_finished(code, status))
        p.errorOccurred.connect(lambda e: self.on_error(p, e))
        self.log.appendPlainText("$ " + self.cmd_lbl.text())
        self.proc = p
        cmd = self.build_cmd()
        p.start(cmd[0], cmd[1:])
        self.play_btn.running = True
        self.play_btn.setText("ABORTAR")
        self.play_btn.update()
        self.goto(6)

    def stop_game(self):
        p = self.proc
        if not p:
            return
        p.terminate()
        # se o jogo ignorar o pedido, força o encerramento
        def force():
            try:
                if p.state() != QtCore.QProcess.ProcessState.NotRunning:
                    p.kill()
            except RuntimeError:  # objeto já destruído
                pass
        QtCore.QTimer.singleShot(5000, force)

    def on_error(self, p, err):
        self.log.appendPlainText("[erro do processo: %s]" % err)
        # se nem arrancou, 'finished' nunca é emitido: repõe a interface aqui
        if err == QtCore.QProcess.ProcessError.FailedToStart and p is self.proc:
            self.on_finished(-1, None)

    def on_finished(self, code, status):
        crashed = status == QtCore.QProcess.ExitStatus.CrashExit
        self.log.appendPlainText("[jogo terminou, código %s%s]"
                                 % (code, " — CRASH" if crashed else ""))
        if self.proc:
            self.proc.deleteLater()
        self.proc = None
        self.play_btn.running = False
        self.play_btn.setText("DECOLAR")
        self.check_iso()

    def closeEvent(self, e):
        if self.proc:
            if W.QMessageBox.question(
                    self, "Jogo em execução",
                    "O jogo ainda está em execução. Encerrar e sair?"
            ) != W.QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.proc.terminate()
            if not self.proc.waitForFinished(3000):
                self.proc.kill()
                self.proc.waitForFinished(1000)
        self.persist_cfg()
        e.accept()


def main():
    if QtCore is None:
        print("Falta o Qt6 para Python. Instale com:\n"
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
        i = sys.argv.index("--selftest")
        if i + 1 >= len(sys.argv):
            sys.exit("Uso: ac5_launcher.py --selftest caminho/para/jogo.iso")
        print(verify_iso(sys.argv[i + 1]))
    else:
        main()
