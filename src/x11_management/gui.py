"""Modern Graphical User Interface for X11 Management IMS.

Provides full hardware control:
- Multi-profile management (pro.data)
- Independent X/Y DPI configuration (stages 1-8) with RGB colors
- Lighting configuration (modes, speed, brightness, sleep, RGB colors)
- Polling rate selection (125Hz, 250Hz, 500Hz, 1000Hz)
- Button mapping (18 configurable slots) with shortcuts and macros
- Real-time battery and link monitor
- Dual hardware transport support: 2.4GHz FA60 HID and BLE GATT (FEE0/FEE3/FEE4)
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk

from .ble import BleDeviceNotFound, BleError, BleTransport, find_ble_paths
from .engine import ApplyStep, apply_profile, build_steps
from .profile import (
    CONFIGURABLE_BUTTONS,
    LIGHT_MODE_LABELS,
    POLLING_LABELS,
    MacroEvent,
    Profile,
    ProFile,
)
from . import protocol
from .transport import DeviceNotFound, HidError, Monitor, X11Transport, find_hid_paths

ACTION_NAMES = {
    0x00: "Desativado",
    0x01: "Clique esquerdo",
    0x02: "Clique direito",
    0x03: "Clique do scroll",
    0x04: "Avançar",
    0x05: "Voltar",
    0x06: "Ciclo de DPI",
    0x07: "DPI +",
    0x08: "DPI -",
    0x09: "Duplo clique",
    0x0A: "Fire",
    0x0B: "Scroll para cima",
    0x0C: "Scroll para baixo",
    0x0D: "Tilt esquerdo",
    0x0E: "Tilt direito",
    0x10: "Atalho de teclado",
    0x11: "Macro",
    0x16: "Easy aim",
    0x17: "LED loop",
    0x20: "Cortar",
    0x21: "Copiar",
    0x22: "Colar",
    0x23: "Abrir",
    0x24: "Salvar",
    0x25: "Localizar",
    0x26: "Refazer",
    0x27: "Desfazer",
    0x28: "Selecionar tudo",
    0x29: "Imprimir",
    0x2A: "Fechar janela",
    0x2B: "Alternar janelas",
    0x2C: "Mostrar desktop",
    0x2D: "Executar",
    0x2E: "Bloquear PC",
    0x2F: "New (Ctrl+N)",
    0x30: "Zoom In (Ctrl+=)",
    0x31: "Zoom Out (Ctrl+-)",
    0x32: "Captura de tela",
    0x36: "Ciclo de perfil",
    0x37: "Perfil anterior",
    0x38: "Próximo perfil",
    0x40: "Player de mídia",
    0x41: "Play/pause",
    0x42: "Parar",
    0x43: "Faixa anterior",
    0x44: "Próxima faixa",
    0x45: "Volume +",
    0x46: "Volume -",
    0x47: "Mudo",
    0x50: "Página inicial",
    0x51: "Favoritos",
    0x52: "Avançar navegador",
    0x53: "Voltar navegador",
    0x54: "Parar navegador",
    0x55: "Atualizar",
    0x56: "Pesquisar",
    0x57: "E-mail",
    0x58: "Calculadora",
    0x59: "Meu computador",
}
ACTION_CHOICES = [f"0x{code:02X} — {name}" for code, name in sorted(ACTION_NAMES.items())]


def _parse_action(text: str) -> int:
    text = text.strip()
    match = re.match(r"0[xX][0-9a-fA-F]+", text)
    if match:
        return int(match.group(0), 16)
    if "—" in text:
        text = text.split("—", 1)[0].strip()
    if text.isdigit():
        return int(text)
    for code, name in ACTION_NAMES.items():
        if text.lower() == name.lower():
            return code
    raise ValueError(f"ação inválida: {text!r}")


def _parse_hex_byte(text: str, field: str) -> int:
    raw = str(text).strip()
    if not raw:
        return 0
    try:
        value = int(raw, 16)
    except ValueError as exc:
        raise ValueError(f"{field} deve ser hexadecimal (ex.: 02), não {raw!r}") from exc
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{field} deve ser 0..255")
    return value


def _parse_color(text: str) -> int:
    text = text.strip()
    if text.startswith("#"):
        text = text[1:]
        if len(text) != 6:
            raise ValueError("cor deve ser #RRGGBB")
        rr, gg, bb = (int(text[i:i + 2], 16) for i in (0, 2, 4))
        return rr | (gg << 8) | (bb << 16)
    return int(text, 0) & 0xFFFFFF


def _format_color(value: int) -> str:
    return f"#{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}{(value >> 16) & 0xFF:02X}"


class MacroEventDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, event: MacroEvent | None = None):
        super().__init__(parent)
        self.title("Evento de Macro")
        self.resizable(False, False)
        self.result: MacroEvent | None = None
        self.transient(parent)
        self.grab_set()

        self.code_var = tk.StringVar(value=f"{event.code:02X}" if event else "04")
        self.state_var = tk.StringVar(value="up" if event and event.state == 1 else "down")
        self.delay_var = tk.StringVar(value=str(event.delay) if event else "10")

        body = ttk.Frame(self, padding=12)
        body.grid(row=0, column=0, sticky="nsew")
        ttk.Label(body, text="Código HID (hex)").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=self.code_var, width=12).grid(row=0, column=1, pady=2)
        ttk.Label(body, text="Estado").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Combobox(body, textvariable=self.state_var, values=("down", "up"), state="readonly", width=10).grid(row=1, column=1, pady=2)
        ttk.Label(body, text="Atraso (ms)").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=self.delay_var, width=12).grid(row=2, column=1, pady=2)
        ttk.Label(body, text="down = pressionar; up = soltar", foreground="#555").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancelar", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right", padx=6)
        self.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.wait_visibility()
        self.focus_set()

    def _ok(self) -> None:
        try:
            code = int(self.code_var.get().strip(), 16)
            state = 1 if self.state_var.get() == "up" else 0
            delay = int(self.delay_var.get().strip(), 10)
            self.result = MacroEvent(code, state, delay)
        except ValueError as exc:
            messagebox.showerror("Evento inválido", str(exc), parent=self)
            return
        self.destroy()


class X11ManagementApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("X11 Management IMS (Integrated Management System)")
        self.geometry("1120x780")
        self.minsize(980, 680)

        # Set application icon if found
        icon_path = Path(__file__).resolve().parents[2] / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        try:
            ttk.Style(self).theme_use("vista")
        except tk.TclError:
            pass

        self.pro: ProFile | None = None
        self.path: Path | None = None
        self.profile_index = 0
        self._loading = False
        self._busy = False
        self._queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop = threading.Event()
        self._monitor_active = False
        self._macro_events: list[MacroEvent] = []

        self.vid_var = tk.StringVar(value="0x1D57")
        self.pid_var = tk.StringVar(value="0xFA60")
        self.wireless_var = tk.BooleanVar(value=True)
        self.ble_transport_var = tk.BooleanVar(value=False)
        self.profile_var = tk.StringVar()
        self.profile_name_var = tk.StringVar()
        self.selected_dpi_var = tk.IntVar(value=1)
        self.link_xy_var = tk.BooleanVar(value=True)
        self.dpi_rows: list[dict[str, tk.Variable]] = []
        self.light_mode_var = tk.StringVar(value=LIGHT_MODE_LABELS[0])
        self.ble_light_mode_var = tk.StringVar(value=LIGHT_MODE_LABELS[3])
        self.brightness_var = tk.IntVar(value=8)
        self.effect_speed_var = tk.IntVar(value=6)
        self.sleep_var = tk.IntVar(value=10)
        self.light_off_var = tk.IntVar(value=1)
        self.debounce_var = tk.IntVar(value=4)
        self.light_color_var = tk.StringVar(value="#0000FF")
        self.lift_off_var = tk.IntVar(value=0)
        self.move_wake_var = tk.BooleanVar(value=False)
        self.ripple_var = tk.BooleanVar(value=False)
        self.angle_snap_var = tk.BooleanVar(value=False)
        self.polling_var = tk.IntVar(value=3)
        self.button_slot_var = tk.StringVar(value="—")
        self.action_var = tk.StringVar(value=ACTION_CHOICES[1])
        self.param_var = tk.StringVar(value="0")
        self.shortcut_modifier_var = tk.StringVar(value="0")
        self.shortcut_key_var = tk.StringVar(value="0")
        self.macro_name_var = tk.StringVar()
        self.macro_reps_var = tk.StringVar(value="1")

        self._build_menu()
        self._build_ui()
        self.after(100, self._drain_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Try to load default sample profile if available
        default_sample = Path(__file__).resolve().parents[2] / "data" / "default_pro.data"
        if default_sample.exists():
            try:
                self.pro = ProFile.load(default_sample)
                self.path = default_sample
                self.profile_index = 0
                self._refresh_path()
                self._refresh_profile_combo()
                self._load_profile_into_ui()
                self._log(f"carregado perfil padrão ({default_sample.name})")
            except Exception:
                self.new_file(confirm=False)
        else:
            self.new_file(confirm=False)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Novo", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Abrir…", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Salvar", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Salvar como…", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exportar JSON…", command=self.export_json)
        file_menu.add_command(label="Importar JSON…", command=self.import_json)
        file_menu.add_separator()
        file_menu.add_command(label="Sair", command=self._on_close)
        menu.add_cascade(label="Arquivo", menu=file_menu)

        device_menu = tk.Menu(menu, tearoff=False)
        device_menu.add_command(label="Listar interfaces HID", command=self.list_hid)
        device_menu.add_command(label="Listar interfaces BLE", command=self.list_ble)
        device_menu.add_command(label="Ler nível de bateria", command=self.read_battery)
        device_menu.add_separator()
        device_menu.add_command(label="Aplicar perfil", command=self.apply_current)
        device_menu.add_command(label="Dry-run (inspecionar pacotes)", command=self.dry_run)
        device_menu.add_separator()
        device_menu.add_command(label="Iniciar monitor de eventos", command=self.start_monitor)
        device_menu.add_command(label="Parar monitor", command=self.stop_monitor)
        menu.add_cascade(label="Dispositivo", menu=device_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Sobre o X11 Management IMS", command=self._about)
        menu.add_cascade(label="Ajuda", menu=help_menu)
        self.config(menu=menu)
        self.bind_all("<Control-n>", lambda _e: self.new_file())
        self.bind_all("<Control-o>", lambda _e: self.open_file())
        self.bind_all("<Control-s>", lambda _e: self.save_file())

    def _build_ui(self) -> None:
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Arquivo:").pack(side="left")
        self.path_label = ttk.Label(top, text="(novo)", foreground="#555")
        self.path_label.pack(side="left", padx=(4, 16))
        ttk.Label(top, text="Perfil:").pack(side="left")
        self.profile_combo = ttk.Combobox(top, textvariable=self.profile_var, state="readonly", width=28)
        self.profile_combo.pack(side="left", padx=4)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        ttk.Button(top, text="Adicionar", command=self.add_profile).pack(side="left", padx=2)
        ttk.Button(top, text="Remover", command=self.remove_profile).pack(side="left", padx=2)
        ttk.Button(top, text="Renomear", command=self.rename_profile).pack(side="left", padx=2)
        ttk.Button(top, text="Aplicar ao Mouse", command=self.apply_current).pack(side="right", padx=2)
        ttk.Button(top, text="Dry-run", command=self.dry_run).pack(side="right", padx=2)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._build_dpi_tab()
        self._build_lighting_tab()
        self._build_polling_tab()
        self._build_buttons_tab()
        self._build_device_tab()

        self.status_var = tk.StringVar(value="Pronto")
        status = ttk.Label(self, textvariable=self.status_var, anchor="w", relief="sunken", padding=(8, 4))
        status.pack(fill="x", side="bottom")

    def _build_dpi_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="DPI")
        header = ttk.Frame(tab)
        header.pack(fill="x")
        ttk.Label(header, text="Estágio de DPI selecionado:").pack(side="left")
        ttk.Spinbox(header, from_=1, to=8, textvariable=self.selected_dpi_var, width=4).pack(side="left", padx=4)
        ttk.Checkbutton(header, text="Sincronizar Y = X", variable=self.link_xy_var).pack(side="left", padx=12)
        ttk.Label(header, text="Valores em DPI (múltiplos de 100 até 22.000)", foreground="#555").pack(side="left", padx=12)

        grid = ttk.Frame(tab)
        grid.pack(fill="x", pady=(12, 0))
        for col, text in enumerate(("Ativo", "Estágio", "DPI X", "DPI Y", "Cor do LED")):
            ttk.Label(grid, text=text, font=("Segoe UI", 9, "bold")).grid(row=0, column=col, padx=6, pady=4, sticky="w")
        for i in range(8):
            enabled = tk.BooleanVar(value=False)
            x = tk.StringVar()
            y = tk.StringVar()
            color = tk.StringVar()
            ttk.Checkbutton(grid, variable=enabled).grid(row=i + 1, column=0, padx=6)
            ttk.Label(grid, text=f"Estágio {i + 1}").grid(row=i + 1, column=1, padx=6, sticky="w")
            ttk.Entry(grid, textvariable=x, width=12).grid(row=i + 1, column=2, padx=6, pady=3)
            ttk.Entry(grid, textvariable=y, width=12).grid(row=i + 1, column=3, padx=6, pady=3)
            ttk.Entry(grid, textvariable=color, width=12).grid(row=i + 1, column=4, padx=6, pady=3)
            ttk.Button(grid, text="Escolher cor", width=12, command=lambda idx=i: self._choose_dpi_color(idx)).grid(row=i + 1, column=5, padx=4)
            self.dpi_rows.append({"enabled": enabled, "x": x, "y": y, "color": color})

    def _build_lighting_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Iluminação (RGB)")
        left = ttk.Frame(tab)
        left.grid(row=0, column=0, sticky="nw", padx=(0, 30))
        right = ttk.Frame(tab)
        right.grid(row=0, column=1, sticky="nw")

        ttk.Label(left, text="Modo de LED:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Combobox(left, textvariable=self.light_mode_var, values=LIGHT_MODE_LABELS, state="readonly", width=22).grid(row=0, column=1, pady=4, sticky="w")
        ttk.Label(left, text="Modo BLE:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(left, textvariable=self.ble_light_mode_var, values=LIGHT_MODE_LABELS, state="readonly", width=22).grid(row=1, column=1, pady=4, sticky="w")
        ttk.Label(left, text="Brilho (1..8):").grid(row=2, column=0, sticky="w", pady=4)
        tk.Scale(left, from_=1, to=8, orient="horizontal", variable=self.brightness_var, showvalue=True, length=220).grid(row=2, column=1, sticky="w")
        ttk.Label(left, text="Velocidade (4..8):").grid(row=3, column=0, sticky="w", pady=4)
        tk.Scale(left, from_=4, to=8, orient="horizontal", variable=self.effect_speed_var, showvalue=True, length=220).grid(row=3, column=1, sticky="w")
        ttk.Label(left, text="Sleep Timer (min):").grid(row=4, column=0, sticky="w", pady=4)
        tk.Scale(left, from_=1, to=60, orient="horizontal", variable=self.sleep_var, showvalue=True, length=220).grid(row=4, column=1, sticky="w")
        ttk.Label(left, text="Desligar LED (min):").grid(row=5, column=0, sticky="w", pady=4)
        tk.Scale(left, from_=1, to=60, orient="horizontal", variable=self.light_off_var, showvalue=True, length=220).grid(row=5, column=1, sticky="w")
        ttk.Label(left, text="Debounce (ms):").grid(row=6, column=0, sticky="w", pady=4)
        tk.Scale(left, from_=2, to=25, orient="horizontal", variable=self.debounce_var, showvalue=True, length=220).grid(row=6, column=1, sticky="w")

        ttk.Label(right, text="Cor do LED:").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(right, textvariable=self.light_color_var, width=12).grid(row=0, column=1, pady=4)
        ttk.Button(right, text="Escolher…", command=self._choose_light_color).grid(row=0, column=2, padx=4)
        ttk.Label(right, text="Lift-Off Distance:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(right, textvariable=self.lift_off_var, values=(0, 1), state="readonly", width=8).grid(row=1, column=1, pady=4, sticky="w")
        ttk.Checkbutton(right, text="Move Wake", variable=self.move_wake_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(right, text="Ripple Control", variable=self.ripple_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Checkbutton(right, text="Angle Snapping", variable=self.angle_snap_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=4)

    def _build_polling_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Polling Rate")
        ttk.Label(tab, text="Taxa de Amostragem (Polling Rate):", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        for index, label in enumerate(POLLING_LABELS):
            ttk.Radiobutton(tab, text=f"{label} (resposta {(1000 // int(label.split()[0]))}ms)", value=index, variable=self.polling_var).pack(anchor="w", pady=4)
        ttk.Label(tab, text="* No modo BLE, o polling rate é gerenciado pelo controlador Bluetooth do Windows.", foreground="#555").pack(anchor="w", pady=(16, 0))

    def _build_buttons_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Botões e Macros")
        top = ttk.Frame(tab)
        top.pack(fill="both", expand=True)
        columns = ("slot", "action", "param", "shortcut", "macro", "events")
        self.button_tree = ttk.Treeview(top, columns=columns, show="headings", height=14)
        for column, text, width in (
            ("slot", "Slot", 50),
            ("action", "Ação Atribuída", 230),
            ("param", "Parâmetro", 80),
            ("shortcut", "Atalho", 110),
            ("macro", "Nome da Macro", 160),
            ("events", "Eventos", 70),
        ):
            self.button_tree.heading(column, text=text)
            self.button_tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(top, orient="vertical", command=self.button_tree.yview)
        self.button_tree.configure(yscrollcommand=scroll.set)
        self.button_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.button_tree.bind("<<TreeviewSelect>>", self._on_button_selected)

        editor = ttk.LabelFrame(tab, text="Configuração do Botão Selecionado", padding=10)
        editor.pack(fill="x", pady=(10, 0))
        row = ttk.Frame(editor)
        row.pack(fill="x")
        ttk.Label(row, text="Slot:").pack(side="left")
        ttk.Label(row, textvariable=self.button_slot_var, width=4, font=("Segoe UI", 9, "bold")).pack(side="left", padx=(2, 10))
        ttk.Label(row, text="Ação:").pack(side="left")
        self.action_combo = ttk.Combobox(row, textvariable=self.action_var, values=ACTION_CHOICES, width=32)
        self.action_combo.pack(side="left", padx=4)
        self.action_combo.bind("<<ComboboxSelected>>", self._on_action_changed)
        ttk.Label(row, text="Parâmetro:").pack(side="left", padx=(10, 2))
        ttk.Entry(row, textvariable=self.param_var, width=6).pack(side="left", padx=4)

        self.shortcut_frame = ttk.Frame(editor)
        self.shortcut_frame.pack(fill="x", pady=(6, 0))
        ttk.Label(self.shortcut_frame, text="Atalho Teclado: Modificador (hex)").pack(side="left")
        ttk.Entry(self.shortcut_frame, textvariable=self.shortcut_modifier_var, width=6).pack(side="left", padx=4)
        ttk.Label(self.shortcut_frame, text="Tecla (hex)").pack(side="left")
        ttk.Entry(self.shortcut_frame, textvariable=self.shortcut_key_var, width=6).pack(side="left", padx=4)
        ttk.Label(self.shortcut_frame, text="(ex.: Modificador 02 = Ctrl; Tecla 04 = A)", foreground="#555").pack(side="left", padx=6)

        self.macro_frame = ttk.LabelFrame(editor, text="Editor de Macro", padding=8)
        self.macro_frame.pack(fill="both", expand=True, pady=(6, 0))
        macro_top = ttk.Frame(self.macro_frame)
        macro_top.pack(fill="x")
        ttk.Label(macro_top, text="Nome:").pack(side="left")
        ttk.Entry(macro_top, textvariable=self.macro_name_var, width=20).pack(side="left", padx=4)
        ttk.Label(macro_top, text="Repetições:").pack(side="left")
        ttk.Entry(macro_top, textvariable=self.macro_reps_var, width=6).pack(side="left", padx=4)
        ttk.Button(macro_top, text="+ Adicionar Evento", command=self._add_macro_event).pack(side="left", padx=4)
        ttk.Button(macro_top, text="Editar", command=self._edit_macro_event).pack(side="left", padx=2)
        ttk.Button(macro_top, text="Remover", command=self._remove_macro_event).pack(side="left", padx=2)

        self.macro_tree = ttk.Treeview(self.macro_frame, columns=("code", "state", "delay"), show="headings", height=4)
        for column, text, width in (("code", "Código HID", 100), ("state", "Estado", 100), ("delay", "Atraso", 100)):
            self.macro_tree.heading(column, text=text)
            self.macro_tree.column(column, width=width, anchor="w")
        self.macro_tree.pack(fill="both", expand=True, pady=(4, 0))

        bottom = ttk.Frame(editor)
        bottom.pack(fill="x", pady=(8, 0))
        self.editor_bottom = bottom
        ttk.Button(bottom, text="Salvar Alterações no Botão", command=self.apply_button_editor).pack(side="left")
        ttk.Button(bottom, text="Limpar Macro", command=self.clear_button_macro).pack(side="left", padx=6)
        ttk.Label(bottom, text="Os slots 1..18 são transmitidos ao hardware via pacote 0x08.", foreground="#555").pack(side="left", padx=12)
        self._on_action_changed()

    def _build_device_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="Hardware / Diagnóstico")
        device = ttk.LabelFrame(tab, text="Comunicação com Hardware", padding=10)
        device.pack(fill="x")
        ttk.Label(device, text="VID:").pack(side="left")
        ttk.Entry(device, textvariable=self.vid_var, width=8).pack(side="left", padx=4)
        ttk.Label(device, text="PID:").pack(side="left")
        ttk.Entry(device, textvariable=self.pid_var, width=8).pack(side="left", padx=4)
        ttk.Checkbutton(device, text="Wireless 2.4G", variable=self.wireless_var).pack(side="left", padx=8)
        ttk.Checkbutton(device, text="Bluetooth (BLE)", variable=self.ble_transport_var).pack(side="left", padx=4)
        ttk.Button(device, text="Detectar HID", command=self.list_hid).pack(side="left", padx=2)
        ttk.Button(device, text="Detectar BLE", command=self.list_ble).pack(side="left", padx=2)
        ttk.Button(device, text="Bateria", command=self.read_battery).pack(side="left", padx=2)
        ttk.Button(device, text="Iniciar Monitor", command=self.start_monitor).pack(side="left", padx=2)
        ttk.Button(device, text="Parar Monitor", command=self.stop_monitor).pack(side="left", padx=2)

        log_frame = ttk.LabelFrame(tab, text="Log de Transmissão e Eventos", padding=8)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=18, wrap="none", font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="left", fill="y")
        self.log_text.configure(state="disabled")

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _log_json(self, value: dict) -> None:
        self._log(json.dumps(value, ensure_ascii=False))

    def _current_profile(self) -> Profile | None:
        if self.pro is None or not self.pro.profiles:
            return None
        return self.pro.profile(self.profile_index)

    def _profile_labels(self) -> list[str]:
        if self.pro is None:
            return []
        return [f"{i + 1}: {p.name}" for i, p in enumerate(self.pro.profiles)]

    def _refresh_profile_combo(self) -> None:
        labels = self._profile_labels()
        self.profile_combo["values"] = labels
        if labels:
            self.profile_index = min(self.profile_index, len(labels) - 1)
            self.profile_var.set(labels[self.profile_index])
        else:
            self.profile_var.set("")

    def _refresh_path(self) -> None:
        self.path_label.configure(text=str(self.path) if self.path else "(novo)")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.status_var.set("Aplicando no hardware…" if busy else "Pronto")

    def _about(self) -> None:
        messagebox.showinfo(
            "Sobre",
            "X11 Management IMS v1.0.0\n\n"
            "IMS: Integrated Management System\n"
            "Suite de Gerenciamento e Controle de Hardware para o Mouse X11.\n"
            "Comunicação direta com o receptor 2.4GHz FA60 e enlace BLE (FEE0/FEE3/FEE4).",
            parent=self,
        )

    def _choose_dpi_color(self, index: int) -> None:
        current = self.dpi_rows[index]["color"].get()
        try:
            initial = _format_color(_parse_color(current))
        except ValueError:
            initial = "#FFFFFF"
        color = colorchooser.askcolor(color=initial, parent=self)
        if color and color[1]:
            self.dpi_rows[index]["color"].set(color[1].upper())

    def _choose_light_color(self) -> None:
        try:
            initial = _format_color(_parse_color(self.light_color_var.get()))
        except ValueError:
            initial = "#FF0000"
        color = colorchooser.askcolor(color=initial, parent=self)
        if color and color[1]:
            self.light_color_var.set(color[1].upper())

    def new_file(self, confirm: bool = True) -> None:
        if confirm and not messagebox.askyesno("Novo", "Descartar o perfil atual?", parent=self):
            return
        self.pro = ProFile.default("Profile1")
        self.path = None
        self.profile_index = 0
        self._refresh_path()
        self._refresh_profile_combo()
        self._load_profile_into_ui()
        self._log("novo perfil criado em memória")

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self, title="Abrir pro.data", filetypes=[("pro.data", "*.data"), ("Todos os arquivos", "*.*")]
        )
        if not filename:
            return
        try:
            pro = ProFile.load(filename)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erro ao abrir", str(exc), parent=self)
            return
        self.pro = pro
        self.path = Path(filename)
        self.profile_index = 0
        self._refresh_path()
        self._refresh_profile_combo()
        self._load_profile_into_ui()
        self._log(f"aberto {filename} ({pro.profile_count} perfil(is))")

    def save_file(self) -> bool:
        if self.path is None:
            return self.save_file_as()
        return self._save_to(self.path)

    def save_file_as(self) -> bool:
        filename = filedialog.asksaveasfilename(
            parent=self, title="Salvar pro.data", defaultextension=".data", filetypes=[("pro.data", "*.data"), ("Todos os arquivos", "*.*")]
        )
        if not filename:
            return False
        return self._save_to(Path(filename))

    def _save_to(self, path: Path) -> bool:
        if not self._collect_current(validate=True):
            return False
        try:
            assert self.pro is not None
            self.pro.save(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erro ao salvar", str(exc), parent=self)
            return False
        self.path = path
        self._refresh_path()
        self._log(f"salvo {path}")
        return True

    def export_json(self) -> None:
        if not self._collect_current(validate=True):
            return
        filename = filedialog.asksaveasfilename(
            parent=self, title="Exportar JSON", defaultextension=".json", filetypes=[("JSON", "*.json"), ("Todos os arquivos", "*.*")]
        )
        if not filename:
            return
        try:
            assert self.pro is not None
            self.pro.save_json(filename)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erro ao exportar", str(exc), parent=self)
            return
        self._log(f"exportado {filename}")

    def import_json(self) -> None:
        filename = filedialog.askopenfilename(
            parent=self, title="Importar JSON", filetypes=[("JSON", "*.json"), ("Todos os arquivos", "*.*")]
        )
        if not filename:
            return
        try:
            pro = ProFile.load_json(filename)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Erro ao importar", str(exc), parent=self)
            return
        self.pro = pro
        self.path = None
        self.profile_index = 0
        self._refresh_path()
        self._refresh_profile_combo()
        self._load_profile_into_ui()
        self._log(f"importado {filename} ({pro.profile_count} perfil(is))")

    def _on_profile_selected(self, _event=None) -> None:
        if self._loading or self.pro is None:
            return
        labels = self._profile_labels()
        try:
            selected = labels.index(self.profile_var.get())
        except ValueError:
            return
        if selected == self.profile_index:
            return
        if not self._collect_current(validate=False):
            self._refresh_profile_combo()
            return
        self.profile_index = selected
        self._load_profile_into_ui()

    def add_profile(self) -> None:
        if self.pro is None:
            return
        if not self._collect_current(validate=False):
            return
        name = f"Profile{len(self.pro.profiles) + 1}"
        self.pro.add(Profile.default(name))
        self.profile_index = len(self.pro.profiles) - 1
        self._refresh_profile_combo()
        self._load_profile_into_ui()
        self._log(f"adicionado perfil '{name}'")

    def remove_profile(self) -> None:
        if self.pro is None or len(self.pro.profiles) <= 1:
            messagebox.showinfo("Remover", "O arquivo precisa ter pelo menos um perfil.", parent=self)
            return
        profile = self._current_profile()
        if profile is None:
            return
        if not messagebox.askyesno("Remover", f"Remover o perfil '{profile.name}'?", parent=self):
            return
        self.pro.remove(self.profile_index)
        self.profile_index = min(self.profile_index, len(self.pro.profiles) - 1)
        self._refresh_profile_combo()
        self._load_profile_into_ui()
        self._log("perfil removido")

    def rename_profile(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        name = simpledialog.askstring("Renomear", "Nome do perfil:", initialvalue=profile.name, parent=self)
        if not name:
            return
        profile.name = name
        self._refresh_profile_combo()
        self._log(f"perfil renomeado para '{name}'")

    def _load_profile_into_ui(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        self._loading = True
        try:
            self.profile_name_var.set(profile.name)
            self.selected_dpi_var.set(profile.selected_dpi_index + 1)
            for i, row in enumerate(self.dpi_rows):
                row["enabled"].set(bool(profile.dpi_enabled[i]))
                row["x"].set(str(profile.dpi_x[i] * 100))
                row["y"].set(str(profile.dpi_y[i] * 100))
                row["color"].set(_format_color(profile.dpi_colors[i]))
            light = profile.light_mode
            self.light_mode_var.set(LIGHT_MODE_LABELS[light] if 0 <= light < len(LIGHT_MODE_LABELS) else LIGHT_MODE_LABELS[0])
            ble = profile.ble_light_mode
            self.ble_light_mode_var.set(LIGHT_MODE_LABELS[ble] if 0 <= ble < len(LIGHT_MODE_LABELS) else LIGHT_MODE_LABELS[0])
            self.brightness_var.set(profile.brightness)
            self.effect_speed_var.set(profile.effect_speed)
            self.sleep_var.set(profile.sleep_timer_minutes)
            self.light_off_var.set(profile.light_off_minutes)
            self.debounce_var.set(profile.key_response_time)
            self.light_color_var.set(_format_color(profile.light_color))
            self.lift_off_var.set(profile.lift_off_distance)
            self.move_wake_var.set(bool(profile.move_wake))
            self.ripple_var.set(bool(profile.ripple_control))
            self.angle_snap_var.set(bool(profile.angle_snap))
            self.polling_var.set(profile.polling_index)
            self._refresh_button_tree()
            self.button_tree.selection_remove(*self.button_tree.selection())
            self.button_slot_var.set("—")
            self._macro_events = []
            self._refresh_macro_tree()
            self.status_var.set(f"Perfil {self.profile_index + 1}: {profile.name}")
        finally:
            self._loading = False

    def _collect_current(self, validate: bool) -> bool:
        profile = self._current_profile()
        if profile is None:
            return False
        try:
            profile.name = self.profile_name_var.get().strip() or profile.name
            profile.selected_dpi_index = max(0, min(7, int(self.selected_dpi_var.get()) - 1))
            enabled = []
            xs = []
            ys = []
            colors = []
            for i, row in enumerate(self.dpi_rows):
                on = bool(row["enabled"].get())
                x = int(str(row["x"].get()).strip() or "0")
                y = int(str(row["y"].get()).strip() or "0")
                if self.link_xy_var.get():
                    y = x
                if x < 0 or y < 0 or x > 22000 or y > 22000:
                    raise ValueError(f"DPI do estágio {i + 1} fora de 0..22000")
                if x % 100 or y % 100:
                    raise ValueError(f"DPI do estágio {i + 1} deve ser múltiplo de 100")
                if on and (x == 0 or y == 0):
                    raise ValueError(f"estágio {i + 1} habilitado com DPI zero")
                enabled.append(1 if on else 0)
                xs.append(x // 100)
                ys.append(y // 100)
                colors.append(_parse_color(row["color"].get()) & 0xFFFFFF)
            profile.dpi_enabled = enabled
            profile.dpi_x = xs
            profile.dpi_y = ys
            profile.dpi_colors = colors
            mode_index = LIGHT_MODE_LABELS.index(self.light_mode_var.get())
            ble_index = LIGHT_MODE_LABELS.index(self.ble_light_mode_var.get())
            profile.light_mode = mode_index
            profile.ble_light_mode = ble_index
            profile.brightness = int(self.brightness_var.get())
            profile.effect_speed = int(self.effect_speed_var.get())
            profile.sleep_timer_minutes = int(self.sleep_var.get())
            profile.light_off_minutes = int(self.light_off_var.get())
            profile.key_response_time = int(self.debounce_var.get())
            profile.light_color = _parse_color(self.light_color_var.get())
            profile.lift_off_distance = int(self.lift_off_var.get())
            profile.move_wake = 1 if self.move_wake_var.get() else 0
            profile.ripple_control = 1 if self.ripple_var.get() else 0
            profile.angle_snap = 1 if self.angle_snap_var.get() else 0
            profile.polling_index = int(self.polling_var.get())
            if not self._apply_button_editor(silent=True):
                return False
            if validate:
                profile.validate()
        except (ValueError, tk.TclError) as exc:
            if not validate:
                messagebox.showerror("Valor inválido", str(exc), parent=self)
            else:
                messagebox.showerror("Perfil inválido", str(exc), parent=self)
            return False
        return True

    def _refresh_button_tree(self) -> None:
        profile = self._current_profile()
        if profile is None:
            return
        self.button_tree.delete(*self.button_tree.get_children())
        for button in profile.configurable_buttons:
            action = ACTION_NAMES.get(button.action, f"0x{button.action:02X}")
            shortcut = ""
            if button.action == 0x10:
                shortcut = f"{button.shortcut_modifier:02X}/{button.shortcut_key:02X}"
            macro = button.macro_name or ("(macro)" if button.action == 0x11 else "")
            self.button_tree.insert(
                "", "end", iid=str(button.slot),
                values=(button.slot, f"0x{button.action:02X} {action}", button.parameter, shortcut, macro, button.macro_count)
            )

    def _on_button_selected(self, _event=None) -> None:
        if self._loading:
            return
        selection = self.button_tree.selection()
        if not selection:
            return
        slot = int(selection[0])
        profile = self._current_profile()
        if profile is None:
            return
        button = profile.buttons[slot - 1]
        self.button_slot_var.set(str(slot))
        self.action_var.set(f"0x{button.action:02X} — {ACTION_NAMES.get(button.action, '—')}")
        self.param_var.set(str(button.parameter))
        self.shortcut_modifier_var.set(f"{button.shortcut_modifier:02X}")
        self.shortcut_key_var.set(f"{button.shortcut_key:02X}")
        self.macro_name_var.set(button.macro_name)
        self.macro_reps_var.set(str(button.repetitions))
        self._macro_events = button.events
        self._refresh_macro_tree()
        self._on_action_changed()

    def _on_action_changed(self, _event=None) -> None:
        try:
            action = _parse_action(self.action_var.get())
        except ValueError:
            action = -1
        if action == 0x10:
            self.shortcut_frame.pack(fill="x", pady=(4, 0), before=self.editor_bottom)
        else:
            self.shortcut_frame.pack_forget()
        if action == 0x11:
            self.macro_frame.pack(fill="both", expand=True, pady=(6, 0), before=self.editor_bottom)
        else:
            self.macro_frame.pack_forget()

    def _refresh_macro_tree(self) -> None:
        self.macro_tree.delete(*self.macro_tree.get_children())
        for i, event in enumerate(self._macro_events):
            self.macro_tree.insert(
                "", "end", iid=str(i),
                values=(f"{event.code:02X}", "down" if event.state == 0 else "up", f"{event.delay} ms")
            )

    def _selected_macro_index(self) -> int | None:
        selection = self.macro_tree.selection()
        return int(selection[0]) if selection else None

    def _add_macro_event(self) -> None:
        dialog = MacroEventDialog(self)
        self.wait_window(dialog)
        if dialog.result is not None:
            self._macro_events.append(dialog.result)
            self._refresh_macro_tree()

    def _edit_macro_event(self) -> None:
        index = self._selected_macro_index()
        if index is None:
            return
        dialog = MacroEventDialog(self, self._macro_events[index])
        self.wait_window(dialog)
        if dialog.result is not None:
            self._macro_events[index] = dialog.result
            self._refresh_macro_tree()

    def _remove_macro_event(self) -> None:
        index = self._selected_macro_index()
        if index is None:
            return
        del self._macro_events[index]
        self._refresh_macro_tree()

    def apply_button_editor(self) -> None:
        selection = self.button_tree.selection()
        slot = selection[0] if selection else None
        if self._apply_button_editor(silent=False):
            self._refresh_button_tree()
            if slot is not None and self.button_tree.exists(slot):
                self.button_tree.selection_set(slot)
                self.button_tree.see(slot)
            self._log("botão atualizado")

    def _apply_button_editor(self, silent: bool) -> bool:
        profile = self._current_profile()
        selection = self.button_tree.selection()
        if profile is None or not selection:
            return True
        slot = int(selection[0])
        button = profile.buttons[slot - 1]
        try:
            action = _parse_action(self.action_var.get())
            param = int(str(self.param_var.get()).strip() or "0", 0)
            reps = int(str(self.macro_reps_var.get()).strip() or "1", 0)
            if not 0 <= action <= 0xFF or not 0 <= param <= 0xFF:
                raise ValueError("ação/param devem ser 0..255")
            button.action = action
            button.parameter = param
            if action == 0x10:
                modifier = _parse_hex_byte(self.shortcut_modifier_var.get(), "modificador do atalho")
                key = _parse_hex_byte(self.shortcut_key_var.get(), "tecla do atalho")
                button.shortcut_modifier = modifier
                button.shortcut_key = key
            button.macro_name = self.macro_name_var.get()
            button.set_events(list(self._macro_events), repetitions=max(0, reps))
        except ValueError as exc:
            if not silent:
                messagebox.showerror("Botão inválido", str(exc), parent=self)
            return False
        return True

    def clear_button_macro(self) -> None:
        profile = self._current_profile()
        selection = self.button_tree.selection()
        if profile is None or not selection:
            return
        button = profile.buttons[int(selection[0]) - 1]
        button.clear_macro()
        self.macro_name_var.set("")
        self.macro_reps_var.set("0")
        self._macro_events = []
        self._refresh_macro_tree()
        self._refresh_button_tree()
        self._log(f"macro do slot {button.slot} limpa")

    def _device_args(self) -> tuple[int, int]:
        try:
            vid = int(self.vid_var.get(), 0)
            pid = int(self.pid_var.get(), 0)
        except ValueError as exc:
            raise ValueError("VID/PID inválidos") from exc
        return vid, pid

    def list_hid(self) -> None:
        try:
            vid, pid = self._device_args()
            paths = find_hid_paths(vid, pid)
        except (ValueError, DeviceNotFound, HidError, OSError) as exc:
            messagebox.showerror("HID", str(exc), parent=self)
            return
        self._log(f"Receptor HID detectado: VID_{paths.vid:04X}&PID_{paths.pid:04X}")
        for number in sorted(paths.paths):
            self._log(f"  col{number:02d}: {paths.paths[number]}")

    def list_ble(self) -> None:
        try:
            paths = find_ble_paths()
        except (BleError, BleDeviceNotFound, OSError) as exc:
            messagebox.showerror("BLE", str(exc), parent=self)
            return
        if not paths:
            self._log("nenhuma interface GATT do X11 encontrada")
            return
        self._log(f"Interfaces GATT X11 (VID_045E&PID_0055): {len(paths)}")
        for path in paths:
            self._log(f"  {path}")

    def read_battery(self) -> None:
        try:
            vid, pid = self._device_args()
        except ValueError as exc:
            messagebox.showerror("Bateria", str(exc), parent=self)
            return

        def worker() -> None:
            monitor = None
            try:
                monitor = Monitor(find_hid_paths(vid, pid).monitor)
                seen = []
                monitor.read_for(3.0, seen.append)
                battery = [e for e in seen if e.get("kind") == "power"]
                if battery:
                    self._queue.put(("log", f"Bateria: {battery[-1].get('percent')}% (status {battery[-1].get('status')})"))
                else:
                    self._queue.put(("log", "nenhum relatório de bateria retornado em 3s"))
            except Exception as exc:
                self._queue.put(("error", f"bateria: {exc}"))
            finally:
                if monitor is not None:
                    monitor.close()

        threading.Thread(target=worker, daemon=True).start()

    def dry_run(self) -> None:
        if not self._collect_current(validate=True):
            return
        profile = self._current_profile()
        assert profile is not None
        ble = bool(self.ble_transport_var.get())
        try:
            steps = build_steps(profile, full=True, include_macros=True, ble=ble)
        except ValueError as exc:
            messagebox.showerror("Perfil inválido", str(exc), parent=self)
            return
        self._log(f"dry-run: {len(steps)} passo(s) gerados para '{profile.name}' ({'BLE' if ble else 'HID'})")
        for step in steps:
            self._log(f"{step.name} — {len(step.packet)} bytes")
            self._log(f"  {step.packet.hex(' ').upper()}")
            for i, fragment in enumerate(step.fragments):
                self._log(f"  frag {i}: {fragment.hex(' ').upper()}")

    def apply_current(self) -> None:
        if self._busy:
            return
        if not self._collect_current(validate=True):
            return
        profile = self._current_profile()
        assert profile is not None
        ble = bool(self.ble_transport_var.get())
        try:
            steps = build_steps(profile, full=True, include_macros=True, ble=ble)
            vid, pid = self._device_args()
        except ValueError as exc:
            messagebox.showerror("Aplicar", str(exc), parent=self)
            return
        if not messagebox.askyesno(
            "Aplicar Perfil",
            f"Aplicar perfil '{profile.name}' no mouse?\n\n"
            f"{len(steps)} comandos via {'BLE' if ble else 'HID FA60'}.\n"
            "Cada comando aguardará ACK de hardware.",
            parent=self,
        ):
            return
        self._set_busy(True)
        self._log(f"aplicando '{profile.name}' ({len(steps)} passos, {'BLE' if ble else 'HID'})")
        wireless = bool(self.wireless_var.get()) and not ble

        def worker() -> None:
            transport = None
            try:
                transport = BleTransport() if ble else X11Transport(vid, pid, wireless=wireless)
                for index, step in enumerate(steps, 1):
                    if step.macro:
                        ack = transport.send_macro(step.packet, wireless=wireless, retries=10)
                    else:
                        ack = transport.send(step.packet, command=step.command, retries=10)
                    step.ack = ack
                    self._queue.put(("step", step, index, len(steps)))
                self._queue.put(("done", f"perfil '{profile.name}' aplicado com sucesso!"))
            except Exception as exc:
                self._queue.put(("error", f"falha ao aplicar: {exc}"))
            finally:
                if transport is not None:
                    transport.close()

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def start_monitor(self) -> None:
        if self._monitor_active:
            return
        try:
            vid, pid = self._device_args()
        except ValueError as exc:
            messagebox.showerror("Monitor", str(exc), parent=self)
            return
        self._monitor_stop.clear()
        self._monitor_active = True
        self.status_var.set("Monitorando...")

        def worker() -> None:
            monitor = None
            try:
                monitor = Monitor(find_hid_paths(vid, pid).monitor)
                self._queue.put(("log", "monitor iniciado"))
                while not self._monitor_stop.is_set():
                    report = monitor.device.read(0.5)
                    if report is None:
                        continue
                    try:
                        event = protocol.decode_input(report)
                    except ValueError:
                        event = {"kind": "unknown", "raw": report.hex(" ").upper()}
                    self._queue.put(("event", event))
            except Exception as exc:
                self._queue.put(("error", f"monitor: {exc}"))
            finally:
                if monitor is not None:
                    monitor.close()
                self._queue.put(("monitor_done",))

        self._monitor_thread = threading.Thread(target=worker, daemon=True)
        self._monitor_thread.start()

    def stop_monitor(self) -> None:
        if not self._monitor_active:
            return
        self._monitor_stop.set()
        self._monitor_active = False
        self.status_var.set("Parando monitor...")

    def _drain_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._log(item[1])
                elif kind == "step":
                    _, step, index, total = item
                    ack = step.ack
                    if ack is not None:
                        self._log(f"[{index}/{total}] {step.name}: ACK {ack.raw.hex(' ').upper()} ({'aceito' if ack.accepted else 'status ' + str(ack.status)})")
                    else:
                        self._log(f"[{index}/{total}] {step.name}")
                elif kind == "event":
                    event = dict(item[1])
                    if event.get("kind") == "polling":
                        raw = event.get("raw_index")
                        event["polling_index"] = {1: 0, 2: 1, 4: 2, 8: 3}.get(raw)
                        event["polling_hz"] = {1: 125, 2: 250, 4: 500, 8: 1000}.get(raw)
                    event["ts"] = datetime.now().isoformat(timespec="milliseconds")
                    self._log_json(event)
                elif kind == "done":
                    self._set_busy(False)
                    self._log(item[1])
                    self._worker = None
                elif kind == "error":
                    self._set_busy(False)
                    self._log(item[1])
                    messagebox.showerror("Erro", item[1], parent=self)
                    self._worker = None
                elif kind == "monitor_done":
                    self._monitor_active = False
                    self._monitor_thread = None
                    self.status_var.set("Pronto")
                    self._log("monitor parado")
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _on_close(self) -> None:
        self._monitor_stop.set()
        self.destroy()


def run() -> int:
    app = X11ManagementApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
