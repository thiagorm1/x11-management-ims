"""Command-line interface for X11 Management IMS."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
from typing import Iterable

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
ACTION_BY_NAME = {name.lower(): code for code, name in ACTION_NAMES.items()}


def _int(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        return int(value, 16)


def _color(value: str) -> int:
    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
        if len(text) != 6:
            raise argparse.ArgumentTypeError("use #RRGGBB")
        rr, gg, bb = (int(text[i:i + 2], 16) for i in (0, 2, 4))
        return rr | (gg << 8) | (bb << 16)
    return _int(text) & 0xFFFFFF


def _format_color(value: int) -> str:
    return f"#{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}{(value >> 16) & 0xFF:02X}"


def _action(value: str) -> int:
    text = value.strip()
    lowered = text.lower()
    if lowered in ACTION_BY_NAME:
        return ACTION_BY_NAME[lowered]
    match = re.match(r"0[xX][0-9a-fA-F]+", text)
    number = int(match.group(0), 16) if match else _int(text)
    if not 0 <= number <= 0xFF:
        raise argparse.ArgumentTypeError("action must be 0..255")
    return number


def _select_profile(pro: ProFile, one_based: int) -> Profile:
    if not 1 <= one_based <= pro.profile_count:
        raise SystemExit(f"perfil {one_based} inexistente; o arquivo tem {pro.profile_count} perfil(is)")
    return pro.profile(one_based - 1)


def _load(path: str) -> ProFile:
    try:
        return ProFile.load(path)
    except FileNotFoundError:
        raise SystemExit(f"arquivo não encontrado: {path}")
    except ValueError as exc:
        raise SystemExit(str(exc))


def _print_step(step: ApplyStep, index: int, total: int, *, show_hex: bool = False) -> None:
    print(f"[{index}/{total}] {step.name} — {len(step.packet)} bytes")
    if show_hex:
        print(f"  {step.packet.hex(' ').upper()}")
    if step.fragments:
        for i, fragment in enumerate(step.fragments):
            print(f"  fragmento {i}: {len(fragment)} bytes")
            if show_hex:
                print(f"    {fragment.hex(' ').upper()}")
    if step.ack is not None:
        ack = step.ack
        state = "aceito" if ack.accepted else f"status {ack.status}"
        print(f"  ACK {ack.raw.hex(' ').upper()} ({state})")


def cmd_list(args: argparse.Namespace) -> int:
    if getattr(args, "ble", False):
        try:
            ble_paths = find_ble_paths()
        except (BleError, BleDeviceNotFound, OSError) as exc:
            print(exc, file=sys.stderr)
            return 1
        if not ble_paths:
            print("nenhuma interface GATT do X11 encontrada (VID_045E&PID_0055)", file=sys.stderr)
            return 1
        print(f"interfaces GATT X11 (VID_045E&PID_0055): {len(ble_paths)}")
        for path in ble_paths:
            marker = "  (configuração)" if "0000fee0-" in path.lower() else ""
            print(f"  {path}{marker}")
        return 0
    try:
        paths = find_hid_paths(args.vid, args.pid)
    except (DeviceNotFound, HidError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"VID_{paths.vid:04X}&PID_{paths.pid:04X}")
    for number in sorted(paths.paths):
        marker = ""
        if number == 4:
            marker = "  (configuração)"
        elif number == 3:
            marker = "  (monitor)"
        print(f"  col{number:02d}{marker}: {paths.paths[number]}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    pro = _load(args.pro)
    if args.json:
        print(json.dumps(pro.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"{args.pro}: {pro.profile_count} perfil(is), header {len(pro.header)} bytes")
    for index, profile in enumerate(pro.profiles, 1):
        print(f"\n[{index}] {profile.name}")
        print(f"  DPI selecionado: {profile.selected_dpi_index + 1} (índice {profile.selected_dpi_index})")
        stages = profile.dpi_stages()
        print("  Estágios DPI:")
        for stage in stages:
            state = "on " if stage["enabled"] else "off"
            print(f"    {stage['index'] + 1}: {state} X={stage['x'] * 100:5d} Y={stage['y'] * 100:5d} cor={_format_color(stage['color'])}")
        polling = profile.polling_index
        polling_name = POLLING_LABELS[polling] if 0 <= polling < len(POLLING_LABELS) else "?"
        print(f"  Polling: {polling_name} (índice {polling})")
        light = profile.light_mode
        light_name = LIGHT_MODE_LABELS[light] if 0 <= light < len(LIGHT_MODE_LABELS) else "?"
        print(f"  Luz: {light_name} (modo {light}), brilho {profile.brightness}, velocidade {profile.effect_speed}, cor {_format_color(profile.light_color)}")
        print(f"  Sleep: {profile.sleep_timer_minutes} min; light-off: {profile.light_off_minutes} min; debounce: {profile.key_response_time}")
        print("  Botões:")
        for button in profile.configurable_buttons:
            name = ACTION_NAMES.get(button.action, "—")
            print(f"    {button.slot:2d}: 0x{button.action:02X} {name}")
            if button.action == 0x10:
                print(f"        atalho: modificador=0x{button.shortcut_modifier:02X} tecla=0x{button.shortcut_key:02X}")
            if button.action == 0x11 or button.macro_count:
                events = ", ".join(f"{e.code:02X}/{e.state}/{e.delay}ms" for e in button.events) or "(vazio)"
                print(f"        macro '{button.macro_name}' rep={button.repetitions}: {events}")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    path = Path(args.pro)
    if path.exists() and not args.force:
        print(f"{path} já existe; use --force para sobrescrever", file=sys.stderr)
        return 1
    pro = ProFile.default(args.name)
    pro.save(path)
    print(f"criado {path} com 1 perfil '{args.name}'")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    pro = _load(args.pro)
    Path(args.out).write_text(json.dumps(pro.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"exportado {args.pro} -> {args.out}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    destination = Path(args.pro)
    if destination.exists() and not args.force:
        print(f"{destination} já existe; use --force para sobrescrever", file=sys.stderr)
        return 1
    try:
        pro = ProFile.load_json(args.input)
    except (OSError, ValueError, KeyError) as exc:
        print(f"JSON inválido: {exc}", file=sys.stderr)
        return 1
    pro.save(destination)
    print(f"importado {args.input} -> {destination} ({pro.profile_count} perfil(is))")
    return 0


def _apply_steps(pro: ProFile, profile_index: int, args: argparse.Namespace) -> int:
    profile = _select_profile(pro, profile_index)
    ble = bool(getattr(args, "ble", False))
    if ble and getattr(args, "wired", False):
        print("--ble e --wired são mutuamente exclusivos", file=sys.stderr)
        return 2
    try:
        steps = build_steps(
            profile,
            full=not args.no_full,
            commands=getattr(args, "commands", None),
            include_macros=not args.no_macros,
            ble=ble,
        )
    except ValueError as exc:
        print(f"perfil inválido: {exc}", file=sys.stderr)
        return 2
    print(f"perfil {profile_index}/{pro.profile_count}: {profile.name}")
    print(f"transporte: {'BLE/GATT (FEE3/FEE4)' if ble else 'HID FA60'}")
    print(f"sequência: {len(steps)} passo(s)" + (" (dry-run)" if args.dry_run else ""))
    if args.dry_run:
        for index, step in enumerate(steps, 1):
            _print_step(step, index, len(steps), show_hex=True)
        return 0
    try:
        if ble:
            transport = BleTransport()
        else:
            transport = X11Transport(args.vid, args.pid, wireless=not args.wired)
    except (DeviceNotFound, HidError, BleError, BleDeviceNotFound, OSError) as exc:
        print(f"dispositivo indisponível: {exc}", file=sys.stderr)
        return 1
    try:
        for index, step in enumerate(steps, 1):
            if step.macro:
                step.ack = transport.send_macro(step.packet, wireless=not args.wired, retries=args.retries)
            else:
                step.ack = transport.send(step.packet, command=step.command, retries=args.retries)
            _print_step(step, index, len(steps))
    except (TimeoutError, HidError, BleError, OSError) as exc:
        print(f"falha na aplicação: {exc}", file=sys.stderr)
        return 1
    finally:
        transport.close()
    if getattr(args, "save", False):
        pro.save(args.pro)
        print(f"salvo {args.pro}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    pro = _load(args.pro)
    return _apply_steps(pro, args.profile, args)


def _parse_macro_events(value: str) -> list[MacroEvent]:
    text = value
    if value.startswith("@"):
        text = Path(value[1:]).read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON de macro inválido: {exc}")
    if not isinstance(raw, list):
        raise SystemExit("--macro-events deve ser uma lista")
    events = []
    for item in raw:
        if isinstance(item, dict):
            events.append(MacroEvent(int(item.get("code", 0)), int(item.get("state", 0)), int(item.get("delay", 0))))
        elif isinstance(item, (list, tuple)) and len(item) == 3:
            events.append(MacroEvent(int(item[0]), int(item[1]), int(item[2])))
        else:
            raise SystemExit("cada evento deve ser {code,state,delay} ou [code,state,delay]")
    return events


def cmd_set(args: argparse.Namespace) -> int:
    pro = _load(args.pro)
    profile = _select_profile(pro, args.profile)
    changed = False
    if args.name is not None:
        profile.name = args.name
        changed = True
    if args.selected_dpi is not None:
        profile.selected_dpi_index = args.selected_dpi
        changed = True
    if args.polling is not None:
        profile.polling_index = args.polling
        changed = True
    for key in (
        "brightness", "effect_speed", "sleep_timer_minutes", "light_off_minutes",
        "light_mode", "ble_light_mode", "key_response_time", "lift_off_distance"
    ):
        value = getattr(args, key)
        if value is not None:
            setattr(profile, key, value)
            changed = True
    if args.light_color is not None:
        profile.light_color = args.light_color
        changed = True
    if args.dpi_stage is not None:
        profile.set_dpi_stage(
            args.dpi_stage,
            x=args.dpi_x,
            y=args.dpi_y,
            enabled=None if args.dpi_enabled is None else bool(args.dpi_enabled),
            color=args.dpi_color,
        )
        changed = True
    if args.button is not None:
        if not 1 <= args.button <= 24:
            raise SystemExit("--button deve ser 1..24 (1..18 são configuráveis)")
        button = profile.buttons[args.button - 1]
        if args.action is not None:
            button.action = args.action
            changed = True
        if args.param is not None:
            button.parameter = args.param
            changed = True
        if args.shortcut_modifier is not None:
            button.shortcut_modifier = args.shortcut_modifier
            changed = True
        if args.shortcut_key is not None:
            button.shortcut_key = args.shortcut_key
            changed = True
        if args.clear_macro:
            button.clear_macro()
            changed = True
        if args.macro_name is not None:
            button.macro_name = args.macro_name
            changed = True
        if args.macro_events is not None:
            events = _parse_macro_events(args.macro_events)
            reps = args.macro_reps if args.macro_reps is not None else 1
            button.set_events(events, reps)
            if args.action is None:
                button.action = 0x11
            changed = True
        elif args.macro_reps is not None:
            button.repetitions = args.macro_reps
            changed = True
        if args.action is not None and args.action == 0x11 and button.macro_count == 0:
            print("aviso: ação macro sem eventos; o botão ficará inerte até gravar um macro", file=sys.stderr)
    if not changed:
        print("nada para alterar", file=sys.stderr)
        return 2
    try:
        profile.validate()
    except ValueError as exc:
        print(f"perfil inválido: {exc}", file=sys.stderr)
        return 2
    if not args.no_save:
        pro.save(args.pro)
        print(f"salvo {args.pro}")
    if args.apply:
        return _apply_steps(pro, args.profile, args)
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    try:
        paths = find_hid_paths(args.vid, args.pid)
        monitor = Monitor(paths.monitor)
    except (DeviceNotFound, HidError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1

    def emit(event: dict) -> None:
        event = dict(event)
        if event.get("kind") == "polling":
            raw = event.get("raw_index")
            event["polling_index"] = {1: 0, 2: 1, 4: 2, 8: 3}.get(raw)
            event["polling_hz"] = {1: 125, 2: 250, 4: 500, 8: 1000}.get(raw)
        event["ts"] = datetime.now().isoformat(timespec="milliseconds")
        print(json.dumps(event, ensure_ascii=False), flush=True)

    try:
        if args.seconds == 0:
            print("monitorando; Ctrl+C para sair", file=sys.stderr)
            monitor.read_for(10**9, emit)
        else:
            monitor.read_for(args.seconds, emit)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.close()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        paths = find_hid_paths(args.vid, args.pid)
        monitor = Monitor(paths.monitor)
    except (DeviceNotFound, HidError, OSError) as exc:
        print(exc, file=sys.stderr)
        return 1
    seen = []
    try:
        monitor.read_for(args.seconds, seen.append)
    finally:
        monitor.close()
    battery = [e for e in seen if e.get("kind") == "power"]
    if battery:
        for event in battery:
            print(f"bateria: {event.get('percent')}% (status {event.get('status')})")
    else:
        print(f"nenhum relatório de bateria em {args.seconds}s")
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    try:
        from .gui import run
    except ImportError as exc:
        print(f"Tkinter indisponível: {exc}", file=sys.stderr)
        return 1
    return run()


def _add_device_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--vid", type=lambda s: int(s, 0), default=0x1D57, help="VID (padrão 0x1D57)")
    parser.add_argument("--pid", type=lambda s: int(s, 0), default=0xFA60, help="PID (padrão 0xFA60)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="x11-management-ims",
        description="X11 Management IMS (Integrated Management System) — Suite de Controle de Hardware do Mouse X11.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="lista as coleções HID do receptor")
    p.add_argument("--ble", action="store_true", help="lista as interfaces GATT BLE (VID_045E&PID_0055)")
    _add_device_args(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="mostra perfis de um pro.data")
    p.add_argument("pro")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("new", help="cria um pro.data com um perfil padrão")
    p.add_argument("pro")
    p.add_argument("--name", default="Profile1")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("export", help="exporta pro.data para JSON")
    p.add_argument("pro")
    p.add_argument("out")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="importa JSON para pro.data")
    p.add_argument("pro")
    p.add_argument("input")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("apply", help="aplica um perfil no dispositivo")
    p.add_argument("pro")
    p.add_argument("--profile", type=int, default=1, help="perfil 1-based (padrão 1)")
    p.add_argument("--no-full", action="store_true", help="não envia 0x0C; envia só 0x04/0x05/0x06/0x08")
    p.add_argument("--commands", nargs="+", default=None, help="comandos específicos, ex.: --commands 0x04 0x05")
    p.add_argument("--no-macros", action="store_true")
    p.add_argument("--retries", type=int, default=10)
    p.add_argument("--wired", action="store_true", help="usa Sleep(200) na fragmentação 0x09")
    p.add_argument("--ble", action="store_true", help="usa BLE/GATT (FEE3/FEE4); não envia 0x06 e não fragmenta 0x09")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--save", action="store_true", help="salva o pro.data após aplicar")
    _add_device_args(p)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("set", help="edita campos de um perfil")
    p.add_argument("pro")
    p.add_argument("--profile", type=int, default=1)
    p.add_argument("--name")
    p.add_argument("--selected-dpi", type=int)
    p.add_argument("--polling", type=int, choices=range(4))
    p.add_argument("--brightness", type=int)
    p.add_argument("--effect-speed", type=int)
    p.add_argument("--sleep-timer-minutes", type=int)
    p.add_argument("--light-off-minutes", type=int)
    p.add_argument("--light-mode", type=int)
    p.add_argument("--ble-light-mode", type=int)
    p.add_argument("--key-response-time", type=int)
    p.add_argument("--lift-off-distance", type=int)
    p.add_argument("--light-color", type=_color)
    p.add_argument("--dpi-stage", type=int, choices=range(8))
    p.add_argument("--dpi-x", type=int)
    p.add_argument("--dpi-y", type=int)
    p.add_argument("--dpi-enabled", type=int, choices=(0, 1))
    p.add_argument("--dpi-color", type=_color)
    p.add_argument("--button", type=int)
    p.add_argument("--action", type=_action)
    p.add_argument("--param", type=_int)
    p.add_argument("--shortcut-modifier", type=_int)
    p.add_argument("--shortcut-key", type=_int)
    p.add_argument("--macro-name")
    p.add_argument("--macro-reps", type=int)
    p.add_argument("--macro-events", help="JSON ou @arquivo com eventos {code,state,delay}")
    p.add_argument("--clear-macro", action="store_true")
    p.add_argument("--no-save", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--no-full", action="store_true")
    p.add_argument("--no-macros", action="store_true")
    p.add_argument("--retries", type=int, default=10)
    p.add_argument("--wired", action="store_true")
    p.add_argument("--ble", action="store_true", help="aplica por BLE/GATT ao usar --apply")
    p.add_argument("--dry-run", action="store_true")
    _add_device_args(p)
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("monitor", help="lê eventos do monitor (somente leitura)")
    p.add_argument("--seconds", type=float, default=10.0, help="0 = até Ctrl+C")
    _add_device_args(p)
    p.set_defaults(func=cmd_monitor)

    p = sub.add_parser("gui", help="abre a interface gráfica Tkinter")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("status", help="lê a bateria pelo monitor")
    p.add_argument("--seconds", type=float, default=3.0)
    _add_device_args(p)
    p.set_defaults(func=cmd_status)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrompido", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
