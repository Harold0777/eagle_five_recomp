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


SUPPORTED_LANGS = ("en", "pt", "es", "fr")


def detect_lang():
    override = os.environ.get("AC5_LAUNCHER_LANG", "").strip()
    if override:
        prefix = override.split(".")[0].split("@")[0].replace("-", "_").lower().split("_")[0]
        return prefix if prefix in SUPPORTED_LANGS else "en"

    lc_all = os.environ.get("LC_ALL", "").strip()
    if lc_all:
        if lc_all.upper() in ("C", "POSIX"):
            return "en"
        prefix = lc_all.split(".")[0].split("@")[0].replace("-", "_").lower().split("_")[0]
        return prefix if prefix in SUPPORTED_LANGS else "en"

    lang_list = os.environ.get("LANGUAGE", "").strip()
    if lang_list:
        for raw in lang_list.split(":"):
            code = raw.split(".")[0].split("@")[0].replace("-", "_").lower().strip()
            prefix = code.split("_")[0]
            if prefix in SUPPORTED_LANGS:
                return prefix

    for var in ("LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "").strip()
        if val:
            if val.upper() in ("C", "POSIX"):
                return "en"
            prefix = val.split(".")[0].split("@")[0].replace("-", "_").lower().split("_")[0]
            return prefix if prefix in SUPPORTED_LANGS else "en"

    try:
        import locale as _loc
        loc_name = _loc.getlocale()[0]
        if loc_name:
            prefix = loc_name.replace("-", "_").lower().split("_")[0]
            if prefix in SUPPORTED_LANGS:
                return prefix
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF
            win_map = {0x09: "en", 0x16: "pt", 0x0A: "es", 0x0C: "fr"}
            if lang_id in win_map:
                return win_map[lang_id]
        except Exception:
            pass

    return "en"


LAUNCHER_CFG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "eagle_five",
)
LAUNCHER_CFG_FILE = os.path.join(LAUNCHER_CFG_DIR, "launcher.json")
LANG_CHOICES = (
    ("auto", "Auto (System)"),
    ("en", "English"),
    ("pt", "Português"),
    ("es", "Español"),
    ("fr", "Français"),
)


def load_lang_pref():
    try:
        with open(LAUNCHER_CFG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        val = str(data.get("lang", "auto")).strip().lower()
        if val == "auto" or val in SUPPORTED_LANGS:
            return val
    except Exception:
        pass
    return "auto"


def save_lang_pref(choice):
    try:
        os.makedirs(LAUNCHER_CFG_DIR, exist_ok=True)
        existing = {}
        if os.path.exists(LAUNCHER_CFG_FILE):
            with open(LAUNCHER_CFG_FILE, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        existing["lang"] = choice
        with open(LAUNCHER_CFG_FILE, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2)
    except Exception:
        pass


def resolve_initial_lang():
    override = os.environ.get("AC5_LAUNCHER_LANG", "").strip()
    if override:
        prefix = override.split(".")[0].split("@")[0].replace("-", "_").lower().split("_")[0]
        return prefix if prefix in SUPPORTED_LANGS else "en"
    pref = load_lang_pref()
    if pref in SUPPORTED_LANGS:
        return pref
    return detect_lang()


def find_default_ac5_binary():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    appdir_bin = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "usr", "bin", "ac5"))
    candidates = [
        os.path.join(repo_root, "build", "ac5"),
        os.path.join(os.getcwd(), "build", "ac5"),
        os.path.join(os.getcwd(), "ac5"),
        appdir_bin,
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


def find_default_data_dir():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    data_dir = os.path.join(repo_root, "generated")
    if os.path.isdir(data_dir):
        return data_dir
    user_data = os.path.expanduser("~/.local/share/eagle_five/generated")
    os.makedirs(user_data, exist_ok=True)
    return user_data

LANG = resolve_initial_lang()

TRANSLATIONS = {
    "Não é uma ISO9660 válida (sem descritor CD001).": {
        "en": "Not a valid ISO9660 image (missing CD001 descriptor).",
        "es": "No es una ISO9660 válida (falta el descriptor CD001).",
        "fr": "Image ISO9660 invalide (descripteur CD001 manquant).",
    },
    "Diretório raiz da ISO inválido.": {
        "en": "Invalid ISO root directory.",
        "es": "Directorio raíz de la ISO no válido.",
        "fr": "Répertoire racine de l’ISO invalide.",
    },
    "%s não encontrado na raiz da ISO.": {
        "en": "%s not found in the ISO root.",
        "es": "%s no encontrado en la raíz de la ISO.",
        "fr": "%s introuvable à la racine de l’ISO.",
    },
    "Falha ao ler a ISO.": {
        "en": "Failed to read the ISO.",
        "es": "Error al leer la ISO.",
        "fr": "Échec de la lecture de l’ISO.",
    },
    "SYSTEM.CNF sem linha BOOT2 reconhecível.": {
        "en": "SYSTEM.CNF has no recognizable BOOT2 line.",
        "es": "SYSTEM.CNF sin línea BOOT2 reconocible.",
        "fr": "SYSTEM.CNF sans ligne BOOT2 reconnaissable.",
    },
    "ISO correta: Ace Combat 5 (USA) [%s]": {
        "en": "Valid ISO: Ace Combat 5 (USA) [%s]",
        "es": "ISO correcta: Ace Combat 5 (USA) [%s]",
        "fr": "ISO valide : Ace Combat 5 (USA) [%s]",
    },
    "ISO de outro jogo ou região: %s (esperado %s)": {
        "en": "ISO is from another game or region: %s (expected %s)",
        "es": "ISO de otro juego o región: %s (se esperaba %s)",
        "fr": "ISO d’un autre jeu ou d’une autre région : %s (attendu : %s)",
    },
    "Imagem": {"en": "Picture", "es": "Imagen", "fr": "Image"},
    "Pós-processamento": {"en": "Post-processing", "es": "Posprocesado", "fr": "Post-traitement"},
    "Janela e tela": {"en": "Window & display", "es": "Ventana y pantalla", "fr": "Fenêtre et affichage"},
    "Entrada": {"en": "Input", "es": "Entrada", "fr": "Entrées"},
    "Analógicos": {"en": "Analog sticks", "es": "Sticks analógicos", "fr": "Sticks analogiques"},
    "Teclado": {"en": "Keyboard", "es": "Teclado", "fr": "Clavier"},
    "Controle": {"en": "Controller", "es": "Mando", "fr": "Manette"},
    "Direcional ↑": {"en": "D-Pad ↑", "es": "Cruceta ↑", "fr": "Croix dir. ↑"},
    "Direcional →": {"en": "D-Pad →", "es": "Cruceta →", "fr": "Croix dir. →"},
    "Direcional ↓": {"en": "D-Pad ↓", "es": "Cruceta ↓", "fr": "Croix dir. ↓"},
    "Direcional ←": {"en": "D-Pad ←", "es": "Cruceta ←", "fr": "Croix dir. ←"},
    "Triângulo": {"en": "Triangle", "es": "Triángulo", "fr": "Triangle"},
    "Círculo": {"en": "Circle", "es": "Círculo", "fr": "Rond"},
    "X (cruz)": {"en": "Cross (X)", "es": "Cruz (X)", "fr": "Croix (X)"},
    "Quadrado": {"en": "Square", "es": "Cuadrado", "fr": "Carré"},
    "Analógico esq. ↑": {"en": "Left stick ↑", "es": "Stick izq. ↑", "fr": "Stick gauche ↑"},
    "Analógico esq. ↓": {"en": "Left stick ↓", "es": "Stick izq. ↓", "fr": "Stick gauche ↓"},
    "Analógico esq. ←": {"en": "Left stick ←", "es": "Stick izq. ←", "fr": "Stick gauche ←"},
    "Analógico esq. →": {"en": "Left stick →", "es": "Stick izq. →", "fr": "Stick gauche →"},
    "Analógico dir. ↑": {"en": "Right stick ↑", "es": "Stick der. ↑", "fr": "Stick droit ↑"},
    "Analógico dir. ↓": {"en": "Right stick ↓", "es": "Stick der. ↓", "fr": "Stick droit ↓"},
    "Analógico dir. ←": {"en": "Right stick ←", "es": "Stick der. ←", "fr": "Stick droit ←"},
    "Analógico dir. →": {"en": "Right stick →", "es": "Stick der. →", "fr": "Stick droit →"},
    "Ctrl esq.": {"en": "Left Ctrl", "es": "Ctrl izq.", "fr": "Ctrl gauche"},
    "Shift esq.": {"en": "Left Shift", "es": "Shift izq.", "fr": "Maj gauche"},
    "Shift dir.": {"en": "Right Shift", "es": "Shift der.", "fr": "Maj droite"},
    "Alt esq.": {"en": "Left Alt", "es": "Alt izq.", "fr": "Alt gauche"},
    "Espaço": {"en": "Space", "es": "Espacio", "fr": "Espace"},
    "Ctrl dir.": {"en": "Right Ctrl", "es": "Ctrl der.", "fr": "Ctrl droite"},
    "Alt dir.": {"en": "Right Alt", "es": "Alt der.", "fr": "Alt droite"},
    "Seta ↑": {"en": "Up Arrow", "es": "Flecha ↑", "fr": "Flèche ↑"},
    "Seta ←": {"en": "Left Arrow", "es": "Flecha ←", "fr": "Flèche ←"},
    "Seta →": {"en": "Right Arrow", "es": "Flecha →", "fr": "Flèche →"},
    "Seta ↓": {"en": "Down Arrow", "es": "Flecha ↓", "fr": "Flèche ↓"},
    "Meta esq.": {"en": "Left Super", "es": "Super izq.", "fr": "Super gauche"},
    "Meta dir.": {"en": "Right Super", "es": "Super der.", "fr": "Super droite"},
    "A (Cruz)": {"en": "A (Cross)", "es": "A (Cruz)", "fr": "A (Croix)"},
    "B (Bola)": {"en": "B (Circle)", "es": "B (Círculo)", "fr": "B (Rond)"},
    "X (Quadrado)": {"en": "X (Square)", "es": "X (Cuadrado)", "fr": "X (Carré)"},
    "Y (Triângulo)": {"en": "Y (Triangle)", "es": "Y (Triángulo)", "fr": "Y (Triangle)"},
    "Guide / Home": {"en": "Guide / Home", "es": "Guide / Home", "fr": "Guide / Accueil"},
    "Clique do analógico esquerdo (L3)": {
        "en": "Left stick click (L3)",
        "es": "Clic stick izquierdo (L3)",
        "fr": "Clic stick gauche (L3)",
    },
    "Clique do analógico direito (R3)": {
        "en": "Right stick click (R3)",
        "es": "Clic stick derecho (R3)",
        "fr": "Clic stick droit (R3)",
    },
    "Analógico esquerdo ←": {"en": "Left stick ←", "es": "Stick izquierdo ←", "fr": "Stick gauche ←"},
    "Analógico esquerdo →": {"en": "Left stick →", "es": "Stick izquierdo →", "fr": "Stick gauche →"},
    "Analógico esquerdo ↑": {"en": "Left stick ↑", "es": "Stick izquierdo ↑", "fr": "Stick gauche ↑"},
    "Analógico esquerdo ↓": {"en": "Left stick ↓", "es": "Stick izquierdo ↓", "fr": "Stick gauche ↓"},
    "Analógico direito ←": {"en": "Right stick ←", "es": "Stick derecho ←", "fr": "Stick droit ←"},
    "Analógico direito →": {"en": "Right stick →", "es": "Stick derecho →", "fr": "Stick droit →"},
    "Analógico direito ↑": {"en": "Right stick ↑", "es": "Stick derecho ↑", "fr": "Stick droit ↑"},
    "Analógico direito ↓": {"en": "Right stick ↓", "es": "Stick derecho ↓", "fr": "Stick droit ↓"},
    "Gatilho esquerdo (LT / L2)": {
        "en": "Left trigger (LT / L2)",
        "es": "Gatillo izquierdo (LT / L2)",
        "fr": "Gâchette gauche (LT / L2)",
    },
    "Gatilho direito (RT / R2)": {
        "en": "Right trigger (RT / R2)",
        "es": "Gatillo derecho (RT / R2)",
        "fr": "Gâchette droite (RT / R2)",
    },
    "Desligado": {"en": "Off", "es": "Desactivado", "fr": "Désactivé"},
    "Automática (cobre a janela)": {
        "en": "Automatic (covers window)",
        "es": "Automática (cubre la ventana)",
        "fr": "Automatique (couvre la fenêtre)",
    },
    " (nativa)": {"en": " (native)", "es": " (nativa)", "fr": " (native)"},
    "Qualidade (preset)": {"en": "Quality (preset)", "es": "Calidad (preajuste)", "fr": "Qualité (préréglage)"},
    "Baixa": {"en": "Low", "es": "Baja", "fr": "Basse"},
    "Média": {"en": "Medium", "es": "Media", "fr": "Moyenne"},
    "Alta": {"en": "High", "es": "Alta", "fr": "Élevée"},
    "Personalizada": {"en": "Custom", "es": "Personalizada", "fr": "Personnalisée"},
    "Resolução interna": {"en": "Internal resolution", "es": "Resolución interna", "fr": "Résolution interne"},
    "Filtro de textura": {"en": "Texture filtering", "es": "Filtro de texturas", "fr": "Filtrage des textures"},
    "Como o jogo pede": {"en": "As the game requests", "es": "Como pide el juego", "fr": "Selon le jeu"},
    "Forçar pixelado (nearest)": {
        "en": "Force pixelated (nearest)",
        "es": "Forzar pixelado (nearest)",
        "fr": "Forcer pixelisé (nearest)",
    },
    "Forçar bilinear": {"en": "Force bilinear", "es": "Forzar bilineal", "fr": "Forcer bilinéaire"},
    "Filtragem anisotrópica": {
        "en": "Anisotropic filtering",
        "es": "Filtrado anisotrópico",
        "fr": "Filtrage anisotrope",
    },
    "Desentrelaçamento (junta os campos)": {
        "en": "Deinterlacing (weave fields)",
        "es": "Desentrelazado (une los campos)",
        "fr": "Désentrelacement (fusion des trames)",
    },
    "Filtro de escala": {"en": "Scaling filter", "es": "Filtro de escalado", "fr": "Filtre de mise à l’échelle"},
    "Pixelado (nearest)": {"en": "Pixelated (nearest)", "es": "Pixelado (nearest)", "fr": "Pixelisé (nearest)"},
    "Bilinear": {"en": "Bilinear", "es": "Bilineal", "fr": "Bilinéaire"},
    "Bilinear nítido": {"en": "Sharp bilinear", "es": "Bilineal nítido", "fr": "Bilinéaire net"},
    "Anti-aliasing (FXAA)": {"en": "Anti-aliasing (FXAA)", "es": "Suavizado (FXAA)", "fr": "Anticrénelage (FXAA)"},
    "Nitidez": {"en": "Sharpness", "es": "Nitidez", "fr": "Netteté"},
    "Brilho": {"en": "Brightness", "es": "Brillo", "fr": "Luminosité"},
    "Contraste": {"en": "Contrast", "es": "Contraste", "fr": "Contraste"},
    "Gama": {"en": "Gamma", "es": "Gama", "fr": "Gamma"},
    "Saturação": {"en": "Saturation", "es": "Saturación", "fr": "Saturation"},
    "Modo de tela": {"en": "Display mode", "es": "Modo de pantalla", "fr": "Mode d’affichage"},
    "Janela": {"en": "Windowed", "es": "Ventana", "fr": "Fenêtré"},
    "Tela cheia sem bordas": {
        "en": "Borderless fullscreen",
        "es": "Pantalla completa sin bordes",
        "fr": "Plein écran sans bordure",
    },
    "Tela cheia exclusiva": {
        "en": "Exclusive fullscreen",
        "es": "Pantalla completa exclusiva",
        "fr": "Plein écran exclusif",
    },
    "Tela cheia ao apertar F11": {
        "en": "Fullscreen when pressing F11",
        "es": "Pantalla completa al pulsar F11",
        "fr": "Plein écran avec F11",
    },
    "Sem bordas": {"en": "Borderless", "es": "Sin bordes", "fr": "Sans bordure"},
    "Exclusiva": {"en": "Exclusive", "es": "Exclusiva", "fr": "Exclusif"},
    "Largura da janela": {"en": "Window width", "es": "Ancho de ventana", "fr": "Largeur de la fenêtre"},
    "Altura da janela": {"en": "Window height", "es": "Alto de ventana", "fr": "Hauteur de la fenêtre"},
    "Largura em tela cheia exclusiva": {
        "en": "Exclusive fullscreen width",
        "es": "Ancho en pantalla completa exclusiva",
        "fr": "Largeur plein écran exclusif",
    },
    "Resolução da área de trabalho": {
        "en": "Desktop resolution",
        "es": "Resolución del escritorio",
        "fr": "Résolution du bureau",
    },
    "Altura em tela cheia exclusiva": {
        "en": "Exclusive fullscreen height",
        "es": "Alto en pantalla completa exclusiva",
        "fr": "Hauteur plein écran exclusif",
    },
    "Taxa de atualização (tela cheia)": {
        "en": "Refresh rate (fullscreen)",
        "es": "Frecuencia de actualización (pantalla completa)",
        "fr": "Taux de rafraîchissement (plein écran)",
    },
    "Taxa da área de trabalho": {"en": "Desktop rate", "es": "Frecuencia del escritorio", "fr": "Fréquence du bureau"},
    "Proporção da imagem": {"en": "Aspect ratio", "es": "Relación de aspecto", "fr": "Format d’image"},
    "Esticar para a janela": {"en": "Stretch to window", "es": "Estirar a la ventana", "fr": "Étirer à la fenêtre"},
    "Automática": {"en": "Automatic", "es": "Automática", "fr": "Automatique"},
    "Proporção personalizada (larg./alt.)": {
        "en": "Custom aspect ratio (W/H)",
        "es": "Relación personalizada (ancho/alto)",
        "fr": "Format personnalisé (L/H)",
    },
    "Escala apenas em números inteiros": {
        "en": "Integer scaling only",
        "es": "Escalado solo en números enteros",
        "fr": "Mise à l’échelle entière uniquement",
    },
    "Patch widescreen 16:9": {"en": "16:9 widescreen patch", "es": "Parche panorámico 16:9", "fr": "Correctif écran large 16:9"},
    "HUD no modo widescreen": {"en": "HUD in widescreen mode", "es": "HUD en modo panorámico", "fr": "ATH en mode écran large"},
    "Esticar": {"en": "Stretch", "es": "Estirar", "fr": "Étirer"},
    "Manter 4:3 centralizado": {"en": "Keep 4:3 centered", "es": "Mantener 4:3 centrado", "fr": "Garder 4:3 centré"},
    "Sincronização (VSync)": {"en": "Synchronization (VSync)", "es": "Sincronización (VSync)", "fr": "Synchronisation (VSync)"},
    "Mailbox (baixa latência)": {"en": "Mailbox (low latency)", "es": "Mailbox (baja latencia)", "fr": "Mailbox (faible latence)"},
    "Imediato (sem VSync)": {"en": "Immediate (no VSync)", "es": "Inmediato (sin VSync)", "fr": "Immédiat (sans VSync)"},
    "Adaptativo": {"en": "Adaptive", "es": "Adaptativo", "fr": "Adaptatif"},
    "Limite de FPS": {"en": "FPS limit", "es": "Límite de FPS", "fr": "Limite de FPS"},
    "Sem limite": {"en": "Unlimited", "es": "Sin límite", "fr": "Illimité"},
    "Mostrar FPS na tela": {"en": "Show FPS on screen", "es": "Mostrar FPS en pantalla", "fr": "Afficher les FPS à l’écran"},
    "Escala do menu": {"en": "Menu scale", "es": "Escala del menú", "fr": "Échelle du menu"},
    "Bloquear entrada do jogo nos menus": {
        "en": "Block game input in menus",
        "es": "Bloquear entrada del juego en los menús",
        "fr": "Bloquer les entrées du jeu dans les menus",
    },
    "Zona morta do analógico": {"en": "Analog stick deadzone", "es": "Zona muerta del stick", "fr": "Zone morte du stick"},
    "Sensibilidade do analógico": {
        "en": "Analog stick sensitivity",
        "es": "Sensibilidad del stick",
        "fr": "Sensibilité du stick",
    },
    "Zona morta de botões e gatilhos": {
        "en": "Button and trigger deadzone",
        "es": "Zona muerta de botones y gatillos",
        "fr": "Zone morte des boutons et gâchettes",
    },
    "Inverter analógico esquerdo": {"en": "Invert left stick", "es": "Invertir stick izquierdo", "fr": "Inverser le stick gauche"},
    "Nenhum": {"en": "None", "es": "Ninguno", "fr": "Aucun"},
    "Esquerda/direita": {"en": "Left/right", "es": "Izquierda/derecha", "fr": "Gauche/droite"},
    "Cima/baixo": {"en": "Up/down", "es": "Arriba/abajo", "fr": "Haut/bas"},
    "Ambos": {"en": "Both", "es": "Ambos", "fr": "Les deux"},
    "Inverter analógico direito": {"en": "Invert right stick", "es": "Invertir stick derecho", "fr": "Inverser le stick droit"},
    "SDL3 não encontrada neste sistema.": {
        "en": "SDL3 not found on this system.",
        "es": "SDL3 no encontrada en este sistema.",
        "fr": "SDL3 introuvable sur ce système.",
    },
    "falha ao iniciar": {"en": "failed to initialize", "es": "error al iniciar", "fr": "échec de l’initialisation"},
    "MAPEAR:": {"en": "MAP:", "es": "MAPEAR:", "fr": "CONFIGURER :"},
    "TECLADO": {"en": "KEYBOARD", "es": "TECLADO", "fr": "CLAVIER"},
    "CONTROLE": {"en": "CONTROLLER", "es": "MANDO", "fr": "MANETTE"},
    "Ação": {"en": "Action", "es": "Acción", "fr": "Action"},
    "Principal": {"en": "Primary", "es": "Principal", "fr": "Principale"},
    "Secundária": {"en": "Secondary", "es": "Secondaire", "fr": "Secondaire"},
    "DEFINIR:": {"en": "BIND:", "es": "ASIGNAR:", "fr": "DÉFINIR :"},
    "PRINCIPAL": {"en": "PRIMARY", "es": "PRINCIPAL", "fr": "PRINCIPALE"},
    "SECUNDÁRIA": {"en": "SECONDARY", "es": "SECUNDARIA", "fr": "SECONDAIRE"},
    "LIMPAR": {"en": "CLEAR", "es": "LIMPIAR", "fr": "EFFACER"},
    "LISTA…": {"en": "LIST…", "es": "LISTA…", "fr": "LISTE…"},
    "Tecla #%d": {"en": "Key #%d", "es": "Tecla #%d", "fr": "Touche #%d"},
    "Código %d": {"en": "Code %d", "es": "Código %d", "fr": "Code %d"},
    "Pressione uma tecla…": {"en": "Press a key…", "es": "Pulsa una tecla…", "fr": "Appuyez sur une touche…"},
    "\n(sem entrada neste modo)": {
        "en": "\n(no input in this mode)",
        "es": "\n(sin entrada en este modo)",
        "fr": "\n(aucune entrée dans ce mode)",
    },
    "%s\nPrincipal: %s\nSecundária: %s": {
        "en": "%s\nPrimary: %s\nSecondary: %s",
        "es": "%s\nPrincipal: %s\nSecundaria: %s",
        "fr": "%s\nPrincipale : %s\nSecondaire : %s",
    },
    "a tecla": {"en": "a key", "es": "una tecla", "fr": "une touche"},
    "um botão (ou mova um analógico) no controle": {
        "en": "a button (or move a stick) on the controller",
        "es": "un botón (o mueve un stick) en el mando",
        "fr": "un bouton (ou bougez un stick) sur la manette",
    },
    "Pressione %s para «%s» (%s). Esc cancela%s.": {
        "en": "Press %s for “%s” (%s). Esc cancels%s.",
        "es": "Pulsa %s para «%s» (%s). Esc cancela%s.",
        "fr": "Appuyez sur %s pour « %s » (%s). Échap annule%s.",
    },
    "principal": {"en": "primary", "es": "principal", "fr": "principale"},
    "secundária": {"en": "secondary", "es": "secundaria", "fr": "secondaire"},
    ", Delete limpa": {"en": ", Delete clears", "es": ", Supr limpia", "fr": ", Suppr efface"},
    "Atenção: %s usado em mais de uma ação (em vermelho).": {
        "en": "Warning: %s is bound to more than one action (in red).",
        "es": "Atención: %s se usa en más de una acción (en rojo).",
        "fr": "Attention : %s est utilisé dans plusieurs actions (en rouge).",
    },
    "Selecionado: %s. Clique numa célula da tabela, ou use DEFINIR.": {
        "en": "Selected: %s. Click a table cell, or use BIND.",
        "es": "Seleccionado: %s. Haz clic en una celda de la tabla o usa ASIGNAR.",
        "fr": "Sélectionné : %s. Cliquez sur une cellule du tableau ou utilisez DÉFINIR.",
    },
    "Sem ações de mapeamento no .ini.": {
        "en": "No mapping actions found in .ini.",
        "es": "No hay acciones de mapeo en el .ini.",
        "fr": "Aucune action de mappage dans le .ini.",
    },
    " Escolha na lista.": {"en": " Choose from the list.", "es": " Elige de la lista.", "fr": " Choisissez dans la liste."},
    "Controle: ": {"en": "Controller: ", "es": "Mando: ", "fr": "Manette : "},
    "Nenhum controle reconhecido. Conecte um ou use LISTA…": {
        "en": "No controller detected. Connect one or use LIST…",
        "es": "Ningún mando reconocido. Conecta uno o usa LISTA…",
        "fr": "Aucune manette détectée. Connectez-en une ou utilisez LISTE…",
    },
    "Tempo esgotado.": {"en": "Timed out.", "es": "Tiempo agotado.", "fr": "Délai expiré."},
    "A lista serve só para o controle; no teclado, aperte a tecla.": {
        "en": "The list is only for controllers; on keyboard, press the key.",
        "es": "La lista es solo para el mando; en el teclado, pulsa la tecla.",
        "fr": "La liste ne sert que pour la manette ; au clavier, appuyez sur la touche.",
    },
    "— Nenhum —": {"en": "— None —", "es": "— Ninguno —", "fr": "— Aucun —"},
    "Mapear controle": {"en": "Map controller", "es": "Mapear mando", "fr": "Configurer la manette"},
    "Tecla não reconhecida, tente outra (Esc cancela).": {
        "en": "Unrecognized key, try another (Esc cancels).",
        "es": "Tecla no reconocida, prueba otra (Esc cancela).",
        "fr": "Touche non reconnue, essayez une autre (Échap annule).",
    },
    "01  JOGO": {"en": "01  GAME", "es": "01  JUEGO", "fr": "01  JEU"},
    "02  GRÁFICOS": {"en": "02  GRAPHICS", "es": "02  GRÁFICOS", "fr": "02  GRAPHISMES"},
    "02 // VÍDEO": {"en": "02 // VIDEO", "es": "02 // VÍDEO", "fr": "02 // VIDÉO"},
    "Gráficos": {"en": "Graphics", "es": "Gráficos", "fr": "Graphismes"},
    "03  TELA": {"en": "03  DISPLAY", "es": "03  PANTALLA", "fr": "03  AFFICHAGE"},
    "03 // EXIBIÇÃO": {"en": "03 // DISPLAY", "es": "03 // PANTALLA", "fr": "03 // AFFICHAGE"},
    "04  CONTROLES": {"en": "04  CONTROLS", "es": "04  CONTROLES", "fr": "04  CONTRÔLES"},
    "04 // ENTRADA": {"en": "04 // INPUT", "es": "04 // ENTRADA", "fr": "04 // ENTRÉES"},
    "Controles": {"en": "Controls", "es": "Controles", "fr": "Contrôles"},
    "05  MAPEAMENTO": {"en": "05  MAPPING", "es": "05  MAPEO", "fr": "05  MAPPAGE"},
    "05 // ENTRADA": {"en": "05 // INPUT", "es": "05 // ENTRADA", "fr": "05 // ENTRÉES"},
    "Mapeamento": {"en": "Mapping", "es": "Mapeo", "fr": "Mappage"},
    "06  AVANÇADO": {"en": "06  ADVANCED", "es": "06  AVANZADO", "fr": "06  AVANCÉ"},
    "06 // SISTEMA": {"en": "06 // SYSTEM", "es": "06 // SISTEMA", "fr": "06 // SYSTÈME"},
    "Avançado": {"en": "Advanced", "es": "Avanzado", "fr": "Avancé"},
    "07  CONSOLE": {"en": "07  CONSOLE", "es": "07  CONSOLA", "fr": "07  CONSOLE"},
    "ARRASTE A ISO PARA\nA JANELA  ·  %s": {
        "en": "DROP THE ISO ONTO\nTHE WINDOW  ·  %s",
        "es": "ARRASTRA LA ISO A\nLA VENTANA  ·  %s",
        "fr": "GLISSEZ L’ISO DANS\nLA FENÊTRE  ·  %s",
    },
    "Pronto para decolar?": {
        "en": "Ready for takeoff?",
        "es": "¿Listo para despegar?",
        "fr": "Prêt au décollage ?",
    },
    "Disco": {"en": "Disc", "es": "Disco", "fr": "Disque"},
    "Escolha ou arraste a ISO do jogo…": {
        "en": "Choose or drop the game ISO…",
        "es": "Elige o arrastra la ISO del juego…",
        "fr": "Choisissez ou glissez l’ISO du jeu…",
    },
    "PROCURAR": {"en": "BROWSE", "es": "EXAMINAR", "fr": "PARCOURIR"},
    "Inicialização": {"en": "Launch", "es": "Inicio", "fr": "Lancement"},
    "Executável do jogo": {"en": "Game executable", "es": "Ejecutable del juego", "fr": "Exécutable du jeu"},
    "Pasta de dados (--data)": {"en": "Data folder (--data)", "es": "Carpeta de datos (--data)", "fr": "Dossier de données (--data)"},
    "Desligar watchdog (--watchdog 0)": {
        "en": "Disable watchdog (--watchdog 0)",
        "es": "Desactivar watchdog (--watchdog 0)",
        "fr": "Désactiver le watchdog (--watchdog 0)",
    },
    "Driver de vídeo SDL": {"en": "SDL video driver", "es": "Controlador de vídeo SDL", "fr": "Pilote vidéo SDL"},
    "DECOLAR": {"en": "LAUNCH", "es": "DESPEGAR", "fr": "DÉCOLLER"},
    "PRESET DE HARDWARE:": {"en": "HARDWARE PRESET:", "es": "PREAJUSTE DE HARDWARE:", "fr": "PRÉRÉGLAGE MATÉRIEL :"},
    "BAIXO": {"en": "LOW", "es": "BAJO", "fr": "BAS"},
    "MÉDIO": {"en": "MEDIUM", "es": "MEDIO", "fr": "MOYEN"},
    "ALTO": {"en": "HIGH", "es": "ALTO", "fr": "ÉLEVÉ"},
    "PRESET RÁPIDO:": {"en": "QUICK PRESET:", "es": "PREAJUSTE RÁPIDO:", "fr": "PRÉRÉGLAGE RAPIDE :"},
    "Cinematográfico": {"en": "Cinematic", "es": "Cinematográfico", "fr": "Cinématographique"},
    "Nitidez Máxima": {"en": "Maximum Sharpness", "es": "Nitidez Máxima", "fr": "Netteté Maximale"},
    "Dados e pastas": {"en": "Data and folders", "es": "Datos y carpetas", "fr": "Données et dossiers"},
    "Backup e restauração dos cartões de memória (saves/*.ps2mc) e atalhos para as pastas.": {
        "en": "Backup and restore memory cards (saves/*.ps2mc) and folder shortcuts.",
        "es": "Copia de seguridad y restauración de tarjetas de memoria (saves/*.ps2mc) y accesos directos a las carpetas.",
        "fr": "Sauvegarde et restauration des cartes mémoire (saves/*.ps2mc) et raccourcis vers les dossiers.",
    },
    "FAZER BACKUP DOS SAVES": {"en": "BACKUP SAVES", "es": "RESPALDAR PARTIDAS", "fr": "SAUVEGARDER LES PARTIES"},
    "RESTAURAR BACKUP": {"en": "RESTORE BACKUP", "es": "RESTAURAR COPIA", "fr": "RESTAURER UNE SAUVEGARDE"},
    "ABRIR SAVES": {"en": "OPEN SAVES", "es": "ABRIR PARTIDAS", "fr": "OUVRIR LES SAUVEGARDES"},
    "ABRIR CAPTURAS (OUT)": {"en": "OPEN CAPTURES (OUT)", "es": "ABRIR CAPTURAS (OUT)", "fr": "OUVRIR LES CAPTURES (OUT)"},
    "ABRIR PASTA DO JOGO": {"en": "OPEN GAME FOLDER", "es": "ABRIR CARPETA DEL JUEGO", "fr": "OUVRIR LE DOSSIER DU JEU"},
    "DESCARTAR": {"en": "DISCARD", "es": "DESCARTAR", "fr": "ANNULER"},
    "PADRÕES": {"en": "DEFAULTS", "es": "PREDETERMINADOS", "fr": "PAR DÉFAUT"},
    "SALVAR": {"en": "SAVE", "es": "GUARDAR", "fr": "ENREGISTRER"},
    "07 // TELEMETRIA": {"en": "07 // TELEMETRY", "es": "07 // TELEMETRÍA", "fr": "07 // TÉLÉMÉTRIE"},
    "Console": {"en": "Console", "es": "Consola", "fr": "Console"},
    "COPIAR TUDO": {"en": "COPY ALL", "es": "COPIAR TODO", "fr": "TOUT COPIER"},
    "Escolher ISO do Ace Combat 5": {
        "en": "Choose Ace Combat 5 ISO",
        "es": "Elegir ISO de Ace Combat 5",
        "fr": "Choisir l’ISO d’Ace Combat 5",
    },
    "Imagens de disco (*.iso *.ISO);;Todos (*)": {
        "en": "Disc images (*.iso *.ISO);;All (*)",
        "es": "Imágenes de disco (*.iso *.ISO);;Todos (*)",
        "fr": "Images disque (*.iso *.ISO);;Tous (*)",
    },
    "AGUARDANDO ISO": {"en": "WAITING FOR ISO", "es": "ESPERANDO ISO", "fr": "EN ATTENTE D’ISO"},
    "ARQUIVO NÃO ENCONTRADO": {"en": "FILE NOT FOUND", "es": "ARCHIVO NO ENCONTRADO", "fr": "FICHIER INTROUVABLE"},
    "ISO VERIFICADA // %s": {"en": "ISO VERIFIED // %s", "es": "ISO VERIFICADA // %s", "fr": "ISO VÉRIFIÉE // %s"},
    "Aviso": {"en": "Warning", "es": "Aviso", "fr": "Avertissement"},
    "Feche o jogo antes de fazer backup dos saves.": {
        "en": "Close the game before backing up saves.",
        "es": "Cierra el juego antes de hacer copia de seguridad de las partidas.",
        "fr": "Fermez le jeu avant de sauvegarder les parties.",
    },
    "Nenhum cartão (*.ps2mc) encontrado na pasta saves/ do jogo.": {
        "en": "No memory card (*.ps2mc) found in the game saves/ folder.",
        "es": "No se encontró ninguna tarjeta (*.ps2mc) en la carpeta saves/ del juego.",
        "fr": "Aucune carte mémoire (*.ps2mc) trouvée dans le dossier saves/ du jeu.",
    },
    "[save] Backup criado: %s": {
        "en": "[save] Backup created: %s",
        "es": "[save] Copia creada: %s",
        "fr": "[save] Sauvegarde créée : %s",
    },
    "Erro": {"en": "Error", "es": "Error", "fr": "Erreur"},
    "Falha no backup:\n%s": {"en": "Backup failed:\n%s", "es": "Error en la copia de seguridad:\n%s", "fr": "Échec de la sauvegarde :\n%s"},
    "Sucesso": {"en": "Success", "es": "Éxito", "fr": "Succès"},
    "%d cartão(ões) copiado(s) para:\n%s": {
        "en": "%d card(s) copied to:\n%s",
        "es": "%d tarjeta(s) copiada(s) a:\n%s",
        "fr": "%d carte(s) copiée(s) vers :\n%s",
    },
    "Feche o jogo antes de restaurar saves.": {
        "en": "Close the game before restoring saves.",
        "es": "Cierra el juego antes de restaurar partidas.",
        "fr": "Fermez le jeu avant de restaurer des sauvegardes.",
    },
    "Escolher backup para restaurar": {
        "en": "Choose backup to restore",
        "es": "Elegir copia de seguridad para restaurar",
        "fr": "Choisir une sauvegarde à restaurer",
    },
    "Cartão de memória (*.ps2mc)": {
        "en": "Memory card (*.ps2mc)",
        "es": "Tarjeta de memoria (*.ps2mc)",
        "fr": "Carte mémoire (*.ps2mc)",
    },
    "Restaurar backup": {"en": "Restore backup", "es": "Restaurar copia", "fr": "Restaurer la sauvegarde"},
    "Substituir %s por %s?\n\nO arquivo atual será salvo antes.": {
        "en": "Replace %s with %s?\n\nThe current file will be backed up first.",
        "es": "¿Reemplazar %s por %s?\n\nEl archivo actual se guardará antes.",
        "fr": "Remplacer %s par %s ?\n\nLe fichier actuel sera sauvegardé au préalable.",
    },
    "Falha ao restaurar:\n%s": {"en": "Restore failed:\n%s", "es": "Error al restaurar:\n%s", "fr": "Échec de la restauration :\n%s"},
    "[save] Restaurado %s -> %s": {
        "en": "[save] Restored %s -> %s",
        "es": "[save] Restaurado %s -> %s",
        "fr": "[save] Restauré %s -> %s",
    },
    "SAVE RESTAURADO: %s": {"en": "SAVE RESTORED: %s", "es": "PARTIDA RESTAURADA: %s", "fr": "SAUVEGARDE RESTAURÉE : %s"},
    "Pasta do jogo não encontrada:\n%s": {
        "en": "Game folder not found:\n%s",
        "es": "Carpeta del juego no encontrada:\n%s",
        "fr": "Dossier du jeu introuvable :\n%s",
    },
    "ALTERAÇÕES PENDENTES // CLIQUE EM SALVAR": {
        "en": "UNSAVED CHANGES // CLICK SAVE",
        "es": "CAMBIOS PENDIENTES // HAZ CLIC EN GUARDAR",
        "fr": "MODIFICATIONS EN ATTENTE // CLIQUEZ SUR ENREGISTRER",
    },
    "PRESET '%s' CARREGADO // CLIQUE EM SALVAR PARA APLICAR": {
        "en": "PRESET '%s' LOADED // CLICK SAVE TO APPLY",
        "es": "PREAJUSTE '%s' CARGADO // HAZ CLIC EN GUARDAR PARA APLICAR",
        "fr": "PRÉRÉGLAGE '%s' CHARGÉ // CLIQUEZ SUR ENREGISTRER POUR APPLIQUER",
    },
    "SEM OPÇÕES [postfx] NO .INI (rode o jogo uma vez)": {
        "en": "NO [postfx] OPTIONS IN .INI (run the game once)",
        "es": "SIN OPCIONES [postfx] EN .INI (ejecuta el juego una vez)",
        "fr": "AUCUNE OPTION [postfx] DANS .INI (lancez le jeu une fois)",
    },
    "PRESET DE HARDWARE '%s' CARREGADO // CLIQUE EM SALVAR PARA APLICAR": {
        "en": "HARDWARE PRESET '%s' LOADED // CLICK SAVE TO APPLY",
        "es": "PREAJUSTE DE HARDWARE '%s' CARGADO // HAZ CLIC EN GUARDAR PARA APLICAR",
        "fr": "PRÉRÉGLAGE MATÉRIEL '%s' CHARGÉ // CLIQUEZ SUR ENREGISTRER POUR APPLIQUER",
    },
    "SEM CHAVES CORRESPONDENTES NO .INI (rode o jogo uma vez)": {
        "en": "NO MATCHING KEYS IN .INI (run the game once)",
        "es": "SIN CLAVES COINCIDENTES EN .INI (ejecuta el juego una vez)",
        "fr": "AUCUNE CLÉ CORRESPONDANTE DANS .INI (lancez le jeu une fois)",
    },
    "ARQUIVO DE PADRÕES NÃO ENCONTRADO": {
        "en": "DEFAULTS FILE NOT FOUND",
        "es": "ARCHIVO DE PREDETERMINADOS NO ENCONTRADO",
        "fr": "FICHIER PAR DÉFAUT INTROUVABLE",
    },
    "Erro ao ler os padrões: %s": {
        "en": "Error reading defaults: %s",
        "es": "Error al leer los predeterminados: %s",
        "fr": "Erreur lors de la lecture des valeurs par défaut : %s",
    },
    "%d PADRÕES CARREGADOS // CLIQUE EM SALVAR PARA APLICAR": {
        "en": "%d DEFAULTS LOADED // CLICK SAVE TO APPLY",
        "es": "%d PREDETERMINADOS CARGADOS // HAZ CLIC EN GUARDAR PARA APLICAR",
        "fr": "%d VALEURS PAR DÉFAUT CHARGÉES // CLIQUEZ SUR ENREGISTRER POUR APPLIQUER",
    },
    "SEM ac5_settings.ini EM %s (rode o jogo uma vez)": {
        "en": "NO ac5_settings.ini AT %s (run the game once)",
        "es": "SIN ac5_settings.ini EN %s (ejecuta el juego una vez)",
        "fr": "AUCUN ac5_settings.ini DANS %s (lancez le jeu une fois)",
    },
    "Erro ao ler o .ini: %s": {"en": "Error reading .ini: %s", "es": "Error al leer el .ini: %s", "fr": "Erreur lors de la lecture du .ini : %s"},
    "%d OPÇÕES CARREGADAS": {"en": "%d OPTIONS LOADED", "es": "%d OPCIONES CARGADAS", "fr": "%d OPTIONS CHARGÉES"},
    "Mapeamento de entrada": {"en": "Input mapping", "es": "Mapeo de entrada", "fr": "Mappage des entrées"},
    "Sem seções [keyboard] ou [controller] no .ini.": {
        "en": "No [keyboard] or [controller] sections in .ini.",
        "es": "Sin secciones [keyboard] o [controller] en el .ini.",
        "fr": "Aucune section [keyboard] ou [controller] dans le .ini.",
    },
    "Personalizado (%s)": {"en": "Custom (%s)", "es": "Personalizado (%s)", "fr": "Personnalisé (%s)"},
    "Não foi possível salvar o .ini:\n%s": {
        "en": "Could not save .ini:\n%s",
        "es": "No se pudo guardar el .ini:\n%s",
        "fr": "Impossible d’enregistrer le .ini :\n%s",
    },
    "%d ALTERAÇÃO(ÕES) SALVA(S)": {
        "en": "%d CHANGE(S) SAVED",
        "es": "%d CAMBIO(S) GUARDADO(S)",
        "fr": "%d MODIFICATION(S) ENREGISTRÉE(S)",
    },
    "Gerando ps2_image.bin a partir da ISO...": {
        "en": "Generating ps2_image.bin from ISO...",
        "es": "Generando ps2_image.bin desde la ISO...",
        "fr": "Génération de ps2_image.bin depuis l’ISO...",
    },
    "ps2_image.bin criado: %s (%d bytes)": {
        "en": "ps2_image.bin created: %s (%d bytes)",
        "es": "ps2_image.bin creado: %s (%d bytes)",
        "fr": "ps2_image.bin créé : %s (%d octets)",
    },
    "Executável não encontrado:\n%s": {
        "en": "Executable not found:\n%s",
        "es": "Ejecutable no encontrado:\n%s",
        "fr": "Exécutable introuvable :\n%s",
    },
    "Não foi possível gerar o ps2_image.bin:\n%s": {
        "en": "Could not generate ps2_image.bin:\n%s",
        "es": "No se pudo generar ps2_image.bin:\n%s",
        "fr": "Impossible de générer ps2_image.bin :\n%s",
    },
    "ABORTAR": {"en": "ABORT", "es": "ABORTAR", "fr": "ARRÊTER"},
    "[erro do processo: %s]": {"en": "[process error: %s]", "es": "[error del proceso: %s]", "fr": "[erreur du processus : %s]"},
    "[jogo terminou, código %s%s]": {
        "en": "[game exited, code %s%s]",
        "es": "[el juego terminó, código %s%s]",
        "fr": "[jeu terminé, code %s%s]",
    },
    "Jogo em execução": {"en": "Game running", "es": "Juego en ejecución", "fr": "Jeu en cours d’exécution"},
    "O jogo ainda está em execução. Encerrar e sair?": {
        "en": "The game is still running. Terminate and quit?",
        "es": "El juego sigue en ejecución. ¿Terminar y salir?",
        "fr": "Le jeu est toujours en cours d’exécution. Fermer et quitter ?",
    },
    "Falta o Qt6 para Python. Instale com:\n  Linux (Arch): sudo pacman -S pyside6\n  Windows/macOS: pip install PySide6": {
        "en": "Qt6 for Python is missing. Install with:\n  Linux (Arch): sudo pacman -S pyside6\n  Windows/macOS: pip install PySide6",
        "es": "Falta Qt6 para Python. Instala con:\n  Linux (Arch): sudo pacman -S pyside6\n  Windows/macOS: pip install PySide6",
        "fr": "Qt6 pour Python est manquant. Installez-le avec :\n  Linux (Arch) : sudo pacman -S pyside6\n  Windows/macOS : pip install PySide6",
    },
    "Uso: ac5_launcher.py --selftest caminho/para/jogo.iso": {
        "en": "Usage: ac5_launcher.py --selftest path/to/game.iso",
        "es": "Uso: ac5_launcher.py --selftest ruta/al/juego.iso",
        "fr": "Utilisation : ac5_launcher.py --selftest chemin/vers/jeu.iso",
    },
}


def tr(text):
    if LANG == "pt":
        return text
    entry = TRANSLATIONS.get(text)
    return entry.get(LANG, entry.get("en", text)) if entry else text

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
        raise ValueError(tr("Não é uma ISO9660 válida (sem descritor CD001)."))
    root = pvd[156:190]
    lba = int.from_bytes(root[2:6], "little")
    size = int.from_bytes(root[10:14], "little")
    if not 0 < size <= 1 << 20:
        raise ValueError(tr("Diretório raiz da ISO inválido."))
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
    raise ValueError(tr("%s não encontrado na raiz da ISO.") % name_wanted)


BOOT2 = re.compile(r"BOOT2\s*=\s*cdrom0:\\?([A-Z]{4})[_-](\d{3})[._]?(\d{2})", re.I)


def verify_iso(path):
    try:
        with open(path, "rb") as f:
            cnf = _read_root_file(f, "SYSTEM.CNF").decode("ascii", "replace")
    except (OSError, ValueError, IndexError) as e:
        return "invalid", None, str(e) or tr("Falha ao ler a ISO.")
    m = BOOT2.search(cnf)
    if not m:
        return "invalid", None, tr("SYSTEM.CNF sem linha BOOT2 reconhecível.")
    serial = "%s_%s.%s" % tuple(g.upper() for g in m.groups())
    if serial == EXPECTED_SERIAL:
        return "ok", serial, tr("ISO correta: Ace Combat 5 (USA) [%s]") % serial
    return "wrong", serial, (tr("ISO de outro jogo ou região: %s "
                             "(esperado %s)") % (serial, EXPECTED_SERIAL))


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

SECTION_TITLES = {"graphics": tr("Imagem"), "postfx": tr("Pós-processamento"),
                  "display": tr("Janela e tela"), "input": tr("Entrada"),
                  "analog": tr("Analógicos"), "keyboard": tr("Teclado"),
                  "controller": tr("Controle")}
# Aba que mostra cada seção do .ini; seções desconhecidas vão para "adv".
PAGE_SECTIONS = {"graphics": "gfx", "postfx": "gfx", "display": "disp",
                 "input": "ctl", "analog": "ctl", "keyboard": "map",
                 "controller": "map"}
BIND_SECTIONS = ("keyboard", "controller")
BIND_NAMES = {
    "select": "Select", "start": "Start", "l1": "L1", "l2": "L2", "l3": "L3",
    "r1": "R1", "r2": "R2", "r3": "R3",
    "up": tr("Direcional ↑"), "right": tr("Direcional →"), "down": tr("Direcional ↓"),
    "left": tr("Direcional ←"), "triangle": tr("Triângulo"), "circle": tr("Círculo"),
    "cross": tr("X (cruz)"), "square": tr("Quadrado"),
    "lstick_up": tr("Analógico esq. ↑"), "lstick_down": tr("Analógico esq. ↓"),
    "lstick_left": tr("Analógico esq. ←"), "lstick_right": tr("Analógico esq. →"),
    "rstick_up": tr("Analógico dir. ↑"), "rstick_down": tr("Analógico dir. ↓"),
    "rstick_left": tr("Analógico dir. ←"), "rstick_right": tr("Analógico dir. →"),
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
    (29, 224, tr("Ctrl esq.")), (30, 4, "A"), (31, 22, "S"), (32, 7, "D"),
    (33, 9, "F"), (34, 10, "G"), (35, 11, "H"), (36, 13, "J"), (37, 14, "K"),
    (38, 15, "L"), (39, 51, ";"), (40, 52, "'"), (41, 53, "`"),
    (42, 225, tr("Shift esq.")), (43, 49, "\\"), (44, 29, "Z"), (45, 27, "X"),
    (46, 6, "C"), (47, 25, "V"), (48, 5, "B"), (49, 17, "N"), (50, 16, "M"),
    (51, 54, ","), (52, 55, "."), (53, 56, "/"), (54, 229, tr("Shift dir.")),
    (55, 85, "Num *"), (56, 226, tr("Alt esq.")), (57, 44, tr("Espaço")),
    (58, 57, "Caps Lock"), (59, 58, "F1"), (60, 59, "F2"), (61, 60, "F3"),
    (62, 61, "F4"), (63, 62, "F5"), (64, 63, "F6"), (65, 64, "F7"),
    (66, 65, "F8"), (67, 66, "F9"), (68, 67, "F10"), (69, 83, "Num Lock"),
    (70, 71, "Scroll Lock"), (71, 95, "Num 7"), (72, 96, "Num 8"),
    (73, 97, "Num 9"), (74, 86, "Num -"), (75, 92, "Num 4"), (76, 93, "Num 5"),
    (77, 94, "Num 6"), (78, 87, "Num +"), (79, 89, "Num 1"), (80, 90, "Num 2"),
    (81, 91, "Num 3"), (82, 98, "Num 0"), (83, 99, "Num ."), (86, 100, "< >"),
    (87, 68, "F11"), (88, 69, "F12"), (96, 88, "Num Enter"),
    (97, 228, tr("Ctrl dir.")), (98, 84, "Num /"), (99, 70, "Print Screen"),
    (100, 230, tr("Alt dir.")), (102, 74, "Home"), (103, 82, tr("Seta ↑")),
    (104, 75, "Page Up"), (105, 80, tr("Seta ←")), (106, 79, tr("Seta →")),
    (107, 77, "End"), (108, 81, tr("Seta ↓")), (109, 78, "Page Down"),
    (110, 73, "Insert"), (111, 76, "Delete"), (119, 72, "Pause"),
    (125, 227, tr("Meta esq.")), (126, 231, tr("Meta dir.")),
]
EVDEV_TO_SDL = {e: s for e, s, _n in _KEYS}
KEY_NAME = {s: n for _e, s, n in _KEYS}
# Controle (SDL3): botão = 1 + SDL_GAMEPAD_BUTTON; eixo = 256 | eixo << 1 | positivo
# (código, nome completo, nome curto)
PAD_INPUTS = [
    (1, tr("A (Cruz)"), "A"), (2, tr("B (Bola)"), "B"), (3, tr("X (Quadrado)"), "X"),
    (4, tr("Y (Triângulo)"), "Y"), (5, "Back / Select", "Back"),
    (6, tr("Guide / Home"), "Guide"), (7, "Start", "Start"),
    (8, tr("Clique do analógico esquerdo (L3)"), "L3"),
    (9, tr("Clique do analógico direito (R3)"), "R3"),
    (10, "LB / L1", "LB"), (11, "RB / R1", "RB"),
    (12, tr("Direcional ↑"), "↑"), (13, tr("Direcional ↓"), "↓"),
    (14, tr("Direcional ←"), "←"), (15, tr("Direcional →"), "→"),
    (256, tr("Analógico esquerdo ←"), "LS ←"), (257, tr("Analógico esquerdo →"), "LS →"),
    (258, tr("Analógico esquerdo ↑"), "LS ↑"), (259, tr("Analógico esquerdo ↓"), "LS ↓"),
    (260, tr("Analógico direito ←"), "RS ←"), (261, tr("Analógico direito →"), "RS →"),
    (262, tr("Analógico direito ↑"), "RS ↑"), (263, tr("Analógico direito ↓"), "RS ↓"),
    (265, tr("Gatilho esquerdo (LT / L2)"), "LT"), (267, tr("Gatilho direito (RT / R2)"), "RT"),
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


ANISO = [(tr("Desligado"), "1"), ("2x", "2"), ("4x", "4"), ("8x", "8"), ("16x", "16")]
BOOL_STYLES = [("1", "0"), ("true", "false"), ("yes", "no"), ("on", "off")]
# Resolução interna: 0 = automática, N = N x 640x448 (nativa do PS2)
INTERNAL_RES = [(tr("Automática (cobre a janela)"), "0")] + [
    ("%dx  ·  %d×%d%s" % (n, 640 * n, 448 * n, tr(" (nativa)") if n == 1 else ""), str(n))
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
    ("graphics", "preset"): ("combo", tr("Qualidade (preset)"), [
        (tr("Baixa"), "0"), (tr("Média"), "1"), (tr("Alta"), "2"), ("Ultra", "3"),
        (tr("Personalizada"), "4")]),
    ("graphics", "internal_resolution"): ("combo", tr("Resolução interna"), INTERNAL_RES),
    ("graphics", "texture_filter"): ("combo", tr("Filtro de textura"), [
        (tr("Como o jogo pede"), "0"), (tr("Forçar pixelado (nearest)"), "1"),
        (tr("Forçar bilinear"), "2")]),
    ("graphics", "anisotropy"): ("combo", tr("Filtragem anisotrópica"), ANISO),
    ("graphics", "deinterlace"): ("check", tr("Desentrelaçamento (junta os campos)")),
    ("graphics", "scale_filter"): ("combo", tr("Filtro de escala"), [
        (tr("Pixelado (nearest)"), "0"), (tr("Bilinear"), "1"), (tr("Bilinear nítido"), "2")]),
    ("postfx", "fxaa"): ("check", tr("Anti-aliasing (FXAA)")),
    ("postfx", "sharpen"): ("slider", tr("Nitidez"), 0.0, 1.0),
    ("postfx", "brightness"): ("slider", tr("Brilho"), -0.5, 0.5),
    ("postfx", "contrast"): ("slider", tr("Contraste"), 0.5, 1.5),
    ("postfx", "gamma"): ("slider", tr("Gama"), 0.5, 2.0),
    ("postfx", "saturation"): ("slider", tr("Saturação"), 0.0, 2.0),
    ("display", "window_mode"): ("combo", tr("Modo de tela"), [
        (tr("Janela"), "0"), (tr("Tela cheia sem bordas"), "1"),
        (tr("Tela cheia exclusiva"), "2")]),
    ("display", "fullscreen_type"): ("combo", tr("Tela cheia ao apertar F11"), [
        (tr("Sem bordas"), "1"), (tr("Exclusiva"), "2")]),
    ("display", "window_width"): ("spin", tr("Largura da janela"), 320, 7680, " px", None),
    ("display", "window_height"): ("spin", tr("Altura da janela"), 240, 4320, " px", None),
    ("display", "fullscreen_width"): ("spin", tr("Largura em tela cheia exclusiva"),
                                      0, 7680, " px", tr("Resolução da área de trabalho")),
    ("display", "fullscreen_height"): ("spin", tr("Altura em tela cheia exclusiva"),
                                       0, 4320, " px", tr("Resolução da área de trabalho")),
    ("display", "fullscreen_refresh"): ("dspin", tr("Taxa de atualização (tela cheia)"),
                                        0.0, 1000.0, 2, " Hz", tr("Taxa da área de trabalho")),
    ("display", "aspect"): ("combo", tr("Proporção da imagem"), [
        (tr("Esticar para a janela"), "0"), (tr("Automática"), "1"), ("4:3", "2"),
        ("16:9", "3"), (tr("Personalizada"), "4")]),
    ("display", "aspect_custom"): ("dspin", tr("Proporção personalizada (larg./alt.)"),
                                   0.5, 4.0, 3, "", None),
    ("display", "integer_scale"): ("check", tr("Escala apenas em números inteiros")),
    ("display", "widescreen"): ("check", tr("Patch widescreen 16:9")),
    ("display", "hud_layout"): ("combo", tr("HUD no modo widescreen"), [
        (tr("Esticar"), "0"), (tr("Manter 4:3 centralizado"), "1")]),
    ("display", "present_mode"): ("combo", tr("Sincronização (VSync)"), [
        (tr("Mailbox (baixa latência)"), "0"), ("VSync (FIFO)", "1"),
        (tr("Imediato (sem VSync)"), "2"), (tr("Adaptativo"), "3")]),
    ("display", "fps_limit"): ("spin", tr("Limite de FPS"), 0, 1000, " FPS", tr("Sem limite")),
    ("display", "show_fps"): ("check", tr("Mostrar FPS na tela")),
    ("display", "menu_scale"): ("slider", tr("Escala do menu"), 0.5, 3.0),
    ("input", "block_game_input_in_menu"): ("check", tr("Bloquear entrada do jogo nos menus")),
    ("analog", "deadzone"): ("slider", tr("Zona morta do analógico"), 0.0, 1.0),
    ("analog", "axis_scale"): ("slider", tr("Sensibilidade do analógico"), 0.01, 2.0),
    ("analog", "button_deadzone"): ("slider", tr("Zona morta de botões e gatilhos"), 0.0, 1.0),
    ("analog", "invert_left"): ("combo", tr("Inverter analógico esquerdo"), [
        (tr("Nenhum"), "0"), (tr("Esquerda/direita"), "1"), (tr("Cima/baixo"), "2"), (tr("Ambos"), "3")]),
    ("analog", "invert_right"): ("combo", tr("Inverter analógico direito"), [
        (tr("Nenhum"), "0"), (tr("Esquerda/direita"), "1"), (tr("Cima/baixo"), "2"), (tr("Ambos"), "3")]),
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
            return tr("SDL3 não encontrada neste sistema.")
        self.lib.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if not self.lib.SDL_Init(self.GAMEPAD):
            err = self.lib.SDL_GetError()
            return "SDL3: " + (err.decode("utf-8", "replace") if err else tr("falha ao iniciar"))
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
        top.addWidget(lbl(tr("MAPEAR:"), "tag"))
        self.mode_btns = {}
        for m, text in (("keyboard", tr("TECLADO")), ("controller", tr("CONTROLE"))):
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
        t.setHorizontalHeaderLabels([tr("Ação"), tr("Principal"), tr("Secundária")])
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
        br.addWidget(lbl(tr("DEFINIR:"), "tag"))
        br.addWidget(ghost(tr("PRINCIPAL"), lambda: self.begin(self.sel, 0)))
        br.addWidget(ghost(tr("SECUNDÁRIA"), lambda: self.begin(self.sel, 1)))
        br.addStretch()
        right.addLayout(br)
        br2 = W.QHBoxLayout()
        br2.addWidget(ghost(tr("LIMPAR"), self.clear_sel))
        br2.addWidget(ghost(tr("LISTA…"), self.list_sel))
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
            return KEY_NAME.get(code, tr("Tecla #%d") % code)
        n = PAD_NAME.get(code)
        return (n[1] if short else n[0]) if n else tr("Código %d") % code

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
                    text = tr("Pressione uma tecla…")
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
                tips[a] = name + tr("\n(sem entrada neste modo)")
                continue
            short = [self.code_name(c, True) for c in e["vals"] if c]
            caps[a] = " · ".join(short) if short else "—"
            tips[a] = tr("%s\nPrincipal: %s\nSecundária: %s") % (
                name, self.code_name(e["vals"][0]), self.code_name(e["vals"][1]))
        self.pad.caps, self.pad.tips, self.pad.sel = caps, tips, self.sel
        self.pad.update()
        for m, b in self.mode_btns.items():
            b.setChecked(m == self.mode)
        if self.sel in self.actions:
            t.selectRow(self.actions.index(self.sel))
        if self.cap:
            a, slot = self.cap
            what = tr("a tecla") if self.mode == "keyboard" else tr("um botão (ou mova um analógico) no controle")
            msg = (tr("Pressione %s para «%s» (%s). Esc cancela%s.")
                   % (what, BIND_NAMES.get(a, a), tr("principal") if slot == 0 else tr("secundária"),
                      tr(", Delete limpa") if self.mode == "keyboard" else ""))
            if self.hint:
                msg += "  " + self.hint
        elif dup:
            msg = tr("Atenção: %s usado em mais de uma ação (em vermelho).") % ", ".join(
                self.code_name(c) for c in dup)
        elif self.sel:
            msg = (tr("Selecionado: %s. Clique numa célula da tabela, ou use DEFINIR.")
                   % BIND_NAMES.get(self.sel, self.sel))
            if self.hint:
                msg += "  " + self.hint
        else:
            msg = tr("Sem ações de mapeamento no .ini.")
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
            self.hint = err + tr(" Escolha na lista.")
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
            self.hint = tr("Controle: ") + ", ".join(rd.names())
            self.refresh()
        elif self.ticks == 90 and not rd.pads:
            self.hint = tr("Nenhum controle reconhecido. Conecte um ou use LISTA…")
            self.refresh()
        elif self.ticks > 900:
            self.hint = tr("Tempo esgotado.")
            self.cancel()

    def list_sel(self):
        if self.mode != "controller":
            self.hint = tr("A lista serve só para o controle; no teclado, aperte a tecla.")
            self.refresh()
            return
        self.begin_list(self.sel, self.cap[1] if self.cap else 0)

    def begin_list(self, action, slot):
        e = self.data[self.mode].get(action) if action else None
        if e is None:
            return
        self.cancel(False)
        items = [tr("— Nenhum —")] + [n for _c, n, _s in PAD_INPUTS]
        cur = PAD_NAME.get(e["vals"][slot])
        name, ok = W.QInputDialog.getItem(
            self, tr("Mapear controle"),
            "%s (%s):" % (BIND_NAMES.get(action, action),
                          tr("principal") if slot == 0 else tr("secundária")),
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
            self.status.setText(tr("Tecla não reconhecida, tente outra (Esc cancela)."))
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






def _resolve_lang_choice(raw):
    """Aceita data ('pt') ou texto ('Português') do combo e devolve código válido."""
    if raw is None:
        return "auto"
    s = str(raw).strip()
    if not s:
        return "auto"
    low = s.lower()
    if low in SUPPORTED_LANGS or low == "auto":
        return low
    for code, disp in LANG_CHOICES:
        if s == disp or low == disp.lower():
            return code
    prefix = low.split(".")[0].split("@")[0].replace("-", "_").split("_")[0]
    if prefix in SUPPORTED_LANGS:
        return prefix
    return "auto"

def relaunch_with_lang(new_lang):
    """Troca de idioma confiável: persiste preferência e re-executa o processo."""
    code = _resolve_lang_choice(new_lang)
    try:
        save_lang_pref(code)
    except Exception:
        pass
    if code == "auto":
        os.environ.pop("AC5_LAUNCHER_LANG", None)
    else:
        os.environ["AC5_LAUNCHER_LANG"] = code
    os.execv(sys.executable, [sys.executable] + sys.argv)

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
        pages = [(tr("01  JOGO"), self.page_game()),
                 (tr("02  GRÁFICOS"), self.page_settings(tr("02 // VÍDEO"), tr("Gráficos"), "gfx")),
                 (tr("03  TELA"), self.page_settings(tr("03 // EXIBIÇÃO"), tr("Janela e tela"), "disp")),
                 (tr("04  CONTROLES"), self.page_settings(tr("04 // ENTRADA"), tr("Controles"), "ctl")),
                 (tr("05  MAPEAMENTO"), self.page_settings(tr("05 // ENTRADA"), tr("Mapeamento"), "map")),
                 (tr("06  AVANÇADO"), self.page_settings(tr("06 // SISTEMA"), tr("Avançado"), "adv")),
                 (tr("07  CONSOLE"), self.page_console())]
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
        foot = lbl(tr("ARRASTE A ISO PARA\nA JANELA  ·  %s") % PLAT_DIR.upper(), "muted", 1)
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

    def _switch_lang(self):
        try:
            self.persist_cfg()
        except Exception:
            pass
        raw = self.lang_combo.currentData()
        if raw is None:
            raw = self.lang_combo.currentText()
        relaunch_with_lang(_resolve_lang_choice(raw))


    def page_game(self):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 26)
        v.setSpacing(18)
        self.lang_combo = W.QComboBox()
        self.lang_combo.setFixedWidth(160)
        _pref = load_lang_pref()
        _sel = 0
        for _i, (_code, _label) in enumerate(LANG_CHOICES):
            self.lang_combo.addItem(tr("Automática") if _label == "Auto (System)" else tr(_label))
            if _code == _pref:
                _sel = _i
        self.lang_combo.setCurrentIndex(_sel)
        self.lang_combo.currentIndexChanged.connect(lambda _i: self._switch_lang())
        _lang_row = W.QHBoxLayout()
        _lang_row.addStretch(1)
        _lang_row.addWidget(self.lang_combo)
        v.addLayout(_lang_row)
        v.addLayout(header("01 // BRIEFING", tr("Pronto para decolar?")))

        c, cl = card(tr("Disco"))
        r = W.QHBoxLayout()
        self.iso = W.QLineEdit(self.cfg.get("iso", ""))
        self.iso.setPlaceholderText(tr("Escolha ou arraste a ISO do jogo…"))
        # debounce: não abre a ISO a cada tecla digitada
        self.iso_timer = QtCore.QTimer(self)
        self.iso_timer.setSingleShot(True)
        self.iso_timer.setInterval(250)
        self.iso_timer.timeout.connect(self.check_iso)
        self.iso.textChanged.connect(lambda _t: self.iso_timer.start())
        r.addWidget(self.iso, 1)
        r.addWidget(ghost(tr("PROCURAR"), self.browse))
        cl.addLayout(r)
        self.st_title = lbl("", "readout")
        self.st_detail = lbl("", "muted")
        cl.addWidget(self.st_title)
        cl.addWidget(self.st_detail)
        v.addWidget(c)

        c2, c2l = card(tr("Inicialização"))
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
        rows = [(tr("Executável do jogo"), self.exe_edit),
                (tr("Pasta de dados (--data)"), self.data),
                (tr("Desligar watchdog (--watchdog 0)"), self.wd)]
        if IS_LINUX:
            rows += [("MangoHud", self.mango), (tr("Driver de vídeo SDL"), self.drv)]
        for lab, w in rows:
            c2l.addLayout(row(lab, w))
        for w, sig in ((self.mango, "toggled"), (self.wd, "toggled"),
                       (self.drv, "currentTextChanged"), (self.data, "textChanged")):
            getattr(w, sig).connect(lambda *_: self.refresh_cmd())
        v.addWidget(c2)

        self.play_btn = HudButton(tr("DECOLAR"))
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
            hbar.addWidget(lbl(tr("PRESET DE HARDWARE:"), "tag"))
            hbar.addWidget(ghost(tr("BAIXO"), lambda: self.apply_hw_preset("low")))
            hbar.addWidget(ghost(tr("MÉDIO"), lambda: self.apply_hw_preset("medium")))
            hbar.addWidget(ghost(tr("ALTO"), lambda: self.apply_hw_preset("high")))
            hbar.addStretch()
            v.addLayout(hbar)

            pbar = W.QHBoxLayout()
            pbar.addWidget(lbl(tr("PRESET RÁPIDO:"), "tag"))
            pbar.addWidget(ghost("Original", lambda: self.apply_preset("original")))
            pbar.addWidget(ghost(tr("Cinematográfico"), lambda: self.apply_preset("cinematic")))
            pbar.addWidget(ghost(tr("Nitidez Máxima"), lambda: self.apply_preset("sharp")))
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
            sc, scl = card(tr("Dados e pastas"))
            scl.addWidget(lbl(tr("Backup e restauração dos cartões de memória "
                              "(saves/*.ps2mc) e atalhos para as pastas."), "muted"))
            r1 = W.QHBoxLayout()
            r1.addWidget(ghost(tr("FAZER BACKUP DOS SAVES"), self.backup_save))
            r1.addWidget(ghost(tr("RESTAURAR BACKUP"), self.restore_save))
            r1.addStretch()
            r2 = W.QHBoxLayout()
            r2.addWidget(ghost(tr("ABRIR SAVES"), lambda: self.open_folder("saves")))
            r2.addWidget(ghost(tr("ABRIR CAPTURAS (OUT)"), lambda: self.open_folder("out")))
            r2.addWidget(ghost(tr("ABRIR PASTA DO JOGO"), lambda: self.open_folder("")))
            r2.addStretch()
            scl.addLayout(r1)
            scl.addLayout(r2)
            lay.addWidget(sc)

        bar = W.QHBoxLayout()
        info = lbl("", "muted")
        self.infos.append(info)
        bar.addWidget(info)
        bar.addStretch()
        bar.addWidget(ghost(tr("DESCARTAR"), self.build_settings))
        bar.addWidget(ghost(tr("PADRÕES"), lambda _=False, k=key: self.restore_defaults(k)))
        bar.addWidget(ghost(tr("SALVAR"), lambda: self.save_settings()))
        v.addLayout(bar)
        return page

    def page_console(self):
        page = W.QWidget()
        v = W.QVBoxLayout(page)
        v.setContentsMargins(36, 30, 36, 22)
        v.addLayout(header(tr("07 // TELEMETRIA"), tr("Console")))
        self.log = W.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        v.addWidget(self.log, 1)
        bar = W.QHBoxLayout()
        bar.addStretch()
        bar.addWidget(ghost(tr("LIMPAR"), self.log.clear))
        bar.addWidget(ghost(tr("COPIAR TUDO"), lambda: W.QApplication.clipboard()
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
            self, tr("Escolher ISO do Ace Combat 5"), start,
            tr("Imagens de disco (*.iso *.ISO);;Todos (*)"))
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
            self.set_status(PAL["@MUTED"], tr("AGUARDANDO ISO"))
        elif not os.path.isfile(p):
            self.ok = False
            self.set_status(PAL["@RED"], tr("ARQUIVO NÃO ENCONTRADO"))
        else:
            st, serial, msg = verify_iso(p)
            self.ok = st == "ok"
            self.set_status(PAL["@GREEN"] if self.ok else PAL["@RED"],
                            (tr("ISO VERIFICADA // %s") % serial) if self.ok else msg)
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
            W.QMessageBox.warning(self, tr("Aviso"), tr("Feche o jogo antes de fazer backup dos saves."))
            return
        cards = sorted(self.saves_dir().glob("*.ps2mc"))
        if not cards:
            W.QMessageBox.warning(self, tr("Aviso"), tr("Nenhum cartão (*.ps2mc) encontrado na pasta saves/ do jogo."))
            return
        backup_dir = backup_root()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            for c in cards:
                dest = backup_dir / ("%s_%s.ps2mc" % (c.stem, ts))
                shutil.copy2(c, dest)
                self.log.appendPlainText(tr("[save] Backup criado: %s") % dest)
        except OSError as e:
            W.QMessageBox.critical(self, tr("Erro"), tr("Falha no backup:\n%s") % e)
            return
        W.QMessageBox.information(self, tr("Sucesso"), tr("%d cartão(ões) copiado(s) para:\n%s")
                                  % (len(cards), backup_dir))

    def restore_save(self):
        if self.proc:
            W.QMessageBox.warning(self, tr("Aviso"), tr("Feche o jogo antes de restaurar saves."))
            return
        backup_dir = backup_root()
        src, _ = W.QFileDialog.getOpenFileName(
            self, tr("Escolher backup para restaurar"), str(backup_dir),
            tr("Cartão de memória (*.ps2mc)"))
        if not src:
            return
        src = Path(src)
        m = re.match(r"^(.*)_\d{8}_\d{6}$", src.stem)
        target = self.saves_dir() / ((m.group(1) if m else "card0") + ".ps2mc")
        if W.QMessageBox.question(
                self, tr("Restaurar backup"),
                tr("Substituir %s por %s?\n\nO arquivo atual será salvo antes.")
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
            W.QMessageBox.critical(self, tr("Erro"), tr("Falha ao restaurar:\n%s") % e)
            return
        self.log.appendPlainText(tr("[save] Restaurado %s -> %s") % (src.name, target))
        self.notify(tr("SAVE RESTAURADO: %s") % target.name)

    def open_folder(self, rel_path):
        base = GAME_DIR or self.exe().parent
        if not base.is_dir():
            W.QMessageBox.warning(self, tr("Aviso"), tr("Pasta do jogo não encontrada:\n%s") % base)
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
            self.notify(tr("ALTERAÇÕES PENDENTES // CLIQUE EM SALVAR"))

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
        self.notify((tr("PRESET '%s' CARREGADO // CLIQUE EM SALVAR PARA APLICAR") % name.upper())
                    if n else tr("SEM OPÇÕES [postfx] NO .INI (rode o jogo uma vez)"))

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
        self.notify((tr("PRESET DE HARDWARE '%s' CARREGADO // CLIQUE EM SALVAR PARA APLICAR")
                     % name.upper()) if n
                    else tr("SEM CHAVES CORRESPONDENTES NO .INI (rode o jogo uma vez)"))

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
        self.notify(tr("ALTERAÇÕES PENDENTES // CLIQUE EM SALVAR"))

    def restore_defaults(self, page):
        path = next((p for p in DEFAULT_INIS if p.is_file()), None)
        if not path:
            self.notify(tr("ARQUIVO DE PADRÕES NÃO ENCONTRADO"))
            return
        try:
            _lines, entries = load_ini(path)
        except OSError as e:
            self.notify(tr("Erro ao ler os padrões: %s") % e)
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
        self.notify(tr("%d PADRÕES CARREGADOS // CLIQUE EM SALVAR PARA APLICAR") % n)

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
            self.notify(tr("SEM ac5_settings.ini EM %s (rode o jogo uma vez)") % ini)
            return
        try:
            self.lines, entries = load_ini(ini)
        except OSError as e:
            self.notify(tr("Erro ao ler o .ini: %s") % e)
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
        self.notify(tr("%d OPÇÕES CARREGADAS") % len(self.fields))

    def add_mapping_editor(self, binds):
        c, cl = card(tr("Mapeamento de entrada"))
        if binds:
            self.map_editor = MappingEditor(binds, self.on_map_changed)
            cl.addWidget(self.map_editor)
        else:
            cl.addWidget(lbl(tr("Sem seções [keyboard] ou [controller] no .ini."), "muted"))
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
                w.addItem(tr("Personalizado (%s)") % raw, raw)
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
                W.QMessageBox.critical(self, tr("Erro"), tr("Não foi possível salvar o .ini:\n%s") % e)
                return False
        if not quiet:
            self.build_settings()
            self.notify(tr("%d ALTERAÇÃO(ÕES) SALVA(S)") % len(changes))
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
        self.log.appendPlainText(tr("Gerando ps2_image.bin a partir da ISO..."))
        out, _base, size = make_image.build_image(self.iso.text().strip(), data)
        self.log.appendPlainText(tr("ps2_image.bin criado: %s (%d bytes)") % (out, size))

    def play(self):
        if self.proc:
            self.stop_game()
            return
        if not self.ok:
            return
        if not self.exe().is_file():
            W.QMessageBox.critical(self, tr("Erro"), tr("Executável não encontrado:\n%s")
                                   % self.exe())
            return
        if not self.save_settings(quiet=True):
            return
        try:
            self.ensure_image()
        except Exception as e:
            W.QMessageBox.critical(self, tr("Erro"), tr("Não foi possível gerar o ps2_image.bin:\n%s") % e)
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
        self.play_btn.setText(tr("ABORTAR"))
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
        self.log.appendPlainText(tr("[erro do processo: %s]") % err)
        # se nem arrancou, 'finished' nunca é emitido: repõe a interface aqui
        if err == QtCore.QProcess.ProcessError.FailedToStart and p is self.proc:
            self.on_finished(-1, None)

    def on_finished(self, code, status):
        crashed = status == QtCore.QProcess.ExitStatus.CrashExit
        self.log.appendPlainText(tr("[jogo terminou, código %s%s]")
                                 % (code, " — CRASH" if crashed else ""))
        if self.proc:
            self.proc.deleteLater()
        self.proc = None
        self.play_btn.running = False
        self.play_btn.setText(tr("DECOLAR"))
        self.check_iso()

    def closeEvent(self, e):
        if self.proc:
            if W.QMessageBox.question(
                    self, tr("Jogo em execução"),
                    tr("O jogo ainda está em execução. Encerrar e sair?")
            ) != W.QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.proc.terminate()
            if not self.proc.waitForFinished(3000):
                self.proc.kill()
                self.proc.waitForFinished(1000)
        self.persist_cfg()
        e.accept()

    def _on_lang_changed(self, idx):
        # In-place retranslation path removed: _switch_lang() re-execs
        # via os.execv, so this method is unreachable. Kept as a
        # no-op shim that only persists the preference.
        try:
            save_lang_pref(choice)
        except Exception:
            pass
def main():
    if QtCore is None:
        print(tr("Falta o Qt6 para Python. Instale com:\n"
              "  Linux (Arch): sudo pacman -S pyside6\n"
              "  Windows/macOS: pip install PySide6"))
        sys.exit(1)
    app = W.QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = Launcher()
    win.show()
    sys.exit(app.exec())




# --- Sincroniza o QComboBox de idioma com LANG efetivo na abertura --------
def _eagle_showEvent(self, ev):
    try:
        W.QMainWindow.showEvent(self, ev)
    except Exception:
        pass
    if getattr(self, "_lang_synced", False):
        return
    self._lang_synced = True
    try:
        self.lang_combo.blockSignals(True)
        target = LANG
        for i in range(self.lang_combo.count()):
            d = self.lang_combo.itemData(i)
            t = self.lang_combo.itemText(i)
            code = _resolve_lang_choice(d if d is not None else t)
            if code == target:
                self.lang_combo.setCurrentIndex(i)
                break
    except Exception:
        pass
    finally:
        try:
            self.lang_combo.blockSignals(False)
        except Exception:
            pass

try:
    Launcher.showEvent = _eagle_showEvent
except NameError:
    pass

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        if i + 1 >= len(sys.argv):
            sys.exit(tr("Uso: ac5_launcher.py --selftest caminho/para/jogo.iso"))
        print(verify_iso(sys.argv[i + 1]))
    else:
        main()
