# X11 Management IMS (Integrated Management System)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-lightgrey.svg)](https://www.microsoft.com/windows)
[![Tests](https://img.shields.io/badge/Tests-15%2F15%20Passing-brightgreen.svg)]()

> **IMS** stands for **Integrated Management System**.

---

## English

### Overview

**X11 Management IMS (Integrated Management System)** is a comprehensive hardware management and control suite for the **X11 Mouse**. It provides full hardware communication and configuration integration across **2.4GHz Wireless (FA60 receiver)**, **Wired**, and **Bluetooth Low Energy (BLE)** modes.

### Key Features

- **Direct Hardware Communication (Zero External Driver Dependencies)**:
  - **2.4GHz Wireless / Wired**: Native Win32 HID APIs (`hid.dll`, `setupapi.dll`, `kernel32.dll`) via `ctypes`. Configuration writes via Feature Report 134 (`col04`), and real-time ACKs/events via Input Report 5 (`col03`).
  - **Bluetooth Low Energy (BLE)**: Native GATT connection to proprietary service `0xFEE0`, write characteristic `0xFEE3`, and notifications/ACKs on `0xFEE4` via `BluetoothAPIs.dll`.
- **Full Hardware Report Generation & Integrity**:
  - `0x0C`: Sequence initialization packet (`FE 01 FE`).
  - `0x04`: 8-stage independent DPI block, X/Y axes, and RGB color table.
  - `0x05`: LED lighting mode, brightness, speed, sleep timer, and debounce.
  - `0x06`: Polling rate (`125Hz`, `250Hz`, `500Hz`, `1000Hz`).
  - `0x08`: 18-slot physical button mapping and keyboard shortcuts.
  - `0x09`: Millisecond-accurate macro sequences with 3-part wireless fragmentation.
  - `0x03`: Real-time status decoding (battery percentage 0–100%, charging status, and command ACKs `55 50 00 <cmd>`).
- **Binary Profile Management (`pro.data`)**:
  - Full binary parser and serializer preserving the 164,964-byte (`0x28464`) firmware header.
  - Multi-profile support (`0x80E0` bytes each).
  - JSON import and export for backup, version control, and automation.
- **Modern Graphical User Interface (GUI)**:
  - Visual editor for 8 DPI stages, RGB color pickers, and decoupled X/Y axes.
  - Lighting controls with live preview and color chooser.
  - Polling rate selection.
  - Remapping for 18 physical button slots, shortcut modifiers (Ctrl, Shift, Alt, Win), and full macro editor.
  - Real-time battery meter and link diagnostics.
- **Command-Line Interface (CLI)**:
  - Complete terminal automation with `--dry-run`, retries, status inspection, and scripting capabilities.

### Project Structure

```
D:\Projetos\x11-management-ims/
├── assets/                       # Hardware configuration tables and icons
│   ├── icon.ico                  # Device application icon
│   ├── tables.json               # Hardware action rows and lookup tables
│   └── example-packets.json      # Hardware validation packet specifications
├── data/                         # Working profile data
│   ├── default_pro.data          # Default profile template
│   └── default_macro.data
├── src/
│   └── x11_management/           # Core Python package
│       ├── __init__.py
│       ├── __main__.py
│       ├── protocol.py           # Hardware report encoders/decoders
│       ├── profile.py            # Binary pro.data codec and model
│       ├── transport.py          # Native Win32 HID transport (ctypes)
│       ├── ble.py                # Native Win32 BLE GATT transport (ctypes)
│       ├── engine.py             # Apply orchestrator, retry logic and ACKs
│       ├── cli.py                # Command-line interface
│       └── gui.py                # Modern Tkinter GUI
├── tests/                        # Automated unit test suite
│   ├── test_protocol.py          # Packet validation tests
│   ├── test_profile.py           # Binary integrity and roundtrip tests
│   ├── test_engine.py            # Command sequence and BLE exclusion tests
│   └── test_cli.py               # CLI and parser tests
├── run_gui.bat                   # Quick launcher for Graphical Interface
├── x11_cli.bat                   # Quick launcher for Command-Line Interface
├── ARCHITECTURE.md               # Hardware architecture and protocol specification
├── pyproject.toml                # Project packaging metadata
└── README.md                     # Documentation
```

### Quick Start

#### Graphical Interface (GUI)
Double-click `run_gui.bat` or run:
```powershell
python -m x11_management gui
```

#### Command-Line Interface (CLI)
Use `x11_cli.bat` or the Python module:
```powershell
# List connected HID interfaces (FA60 receiver)
.\x11_cli.bat list

# List connected BLE GATT interfaces
.\x11_cli.bat list --ble

# Read live battery level and charging status
.\x11_cli.bat status

# Display profile configuration
.\x11_cli.bat show data\default_pro.data

# Test profile transmission without writing to device (Dry-Run)
.\x11_cli.bat apply data\default_pro.data --dry-run

# Apply profile to hardware (verifies ACK for each step)
.\x11_cli.bat apply data\default_pro.data

# Apply via Bluetooth Low Energy (BLE)
.\x11_cli.bat apply data\default_pro.data --ble
```

### CLI Command Reference

| Command | Description |
|---|---|
| `list [--ble]` | Enumerate connected HID interfaces or BLE GATT services |
| `status [--seconds N]` | Read battery level and charging status via monitor report |
| `show <pro.data> [--json]` | Display formatted profile data (DPI, lighting, buttons) |
| `new <pro.data> [--name N]` | Create a new configuration file with default profile |
| `export <pro.data> <out.json>` | Export binary configuration to editable JSON |
| `import <pro.data> <in.json>` | Import JSON configuration back to binary format |
| `apply <pro.data>` | Transmit configuration to hardware with ACK verification |
| `set <pro.data> [options]` | Edit DPI, lighting, polling rate, or button parameters |
| `monitor [--seconds N]` | Live stream incoming hardware events (DPI, power, ACK) |
| `gui` | Launch the graphical user interface |

### Running Automated Tests

```powershell
python -m unittest discover -s tests -v
```
All **15/15 tests** pass verifying packet encoders, checksum calculations, binary roundtrips, and BLE rules.

---

## Português (Brasil)

### Visão Geral

O **X11 Management IMS (Integrated Management System)** é uma suite completa de controle e gerenciamento de hardware desenvolvida para o **Mouse X11**. O sistema implementa comunicação direta com o dispositivo para os modos **2.4GHz Wireless (receptor FA60)**, **com fio** e **Bluetooth Low Energy (BLE)**.

> **Nota:** A sigla **IMS** significa **Integrated Management System** (Sistema Integrado de Gerenciamento).

### Principais Recursos

- **Comunicação Direta de Hardware (Sem Dependência de Drivers Externos)**:
  - **HID 2.4GHz / Com Fio**: Utiliza as APIs nativas do Windows (`hid.dll`, `setupapi.dll`, `kernel32.dll`) via `ctypes`. Configurações são enviadas pelo Feature Report 134 (`col04`), e ACKs/eventos chegam pelo Input Report 5 (`col03`).
  - **Bluetooth Low Energy (BLE)**: Comunicação nativa com o serviço proprietário `0xFEE0`, escrita com resposta em `0xFEE3` e escuta de notificações/ACKs em `0xFEE4` via `BluetoothAPIs.dll`.
- **Geração e Integridade de Pacotes de Hardware**:
  - `0x0C`: Inicialização da sequência de aplicação (`FE 01 FE`).
  - `0x04`: Bloco de DPI de 8 estágios independentes, eixos X/Y e tabela de cores RGB.
  - `0x05`: Modo de iluminação LED, brilho, velocidade, sleep timer e debounce.
  - `0x06`: Taxa de amostragem (`125Hz`, `250Hz`, `500Hz`, `1000Hz`).
  - `0x08`: Mapeamento de 18 botões físicos e atalhos de teclado.
  - `0x09`: Sequências de macros com precisão em milissegundos e fragmentação wireless em 3 partes.
  - `0x03`: Decodificação de telemetria em tempo real (bateria de 0–100%, status de carregamento e confirmação de ACK `55 50 00 <cmd>`).
- **Gerenciador de Perfis Binários (`pro.data`)**:
  - Leitura e gravação preservando o cabeçalho de 164.964 bytes (`0x28464`).
  - Suporte a múltiplos perfis de 32.992 bytes (`0x80E0`).
  - Exportação e importação em JSON para backup, versionamento e automação.
- **Interface Gráfica Intuitiva (GUI)**:
  - Editor visual para 8 estágios de DPI, seletor de cores RGB e eixos X/Y desacoplados.
  - Controle completo de iluminação com pré-visualização.
  - Ajuste de polling rate.
  - Remapeamento dos 18 botões, modificadores de atalho (Ctrl, Shift, Alt, Win) e editor de macros.
  - Medidor de nível de bateria e diagnóstico de conexão em tempo real.
- **Interface de Linha de Comando (CLI)**:
  - Automação via scripts com suporte a `--dry-run`, retentativas e comandos individuais.

### Estrutura do Projeto

```
D:\Projetos\x11-management-ims/
├── assets/                       # Tabelas de hardware e ícones
│   ├── icon.ico                  # Ícone da aplicação
│   ├── tables.json               # Tabelas de ações e lookup do dispositivo
│   └── example-packets.json      # Especificação de pacotes para validação
├── data/                         # Arquivos de trabalho
│   ├── default_pro.data          # Modelo padrão de configuração
│   └── default_macro.data
├── src/
│   └── x11_management/           # Pacote Python principal
│       ├── __init__.py
│       ├── __main__.py
│       ├── protocol.py           # Codificadores/decodificadores de relatórios
│       ├── profile.py            # Parser e serializador de pro.data
│       ├── transport.py          # Driver HID Win32 nativo (ctypes)
│       ├── ble.py                # Driver BLE GATT Win32 nativo (ctypes)
│       ├── engine.py             # Orquestrador de aplicação e ACKs
│       ├── cli.py                # Interface de linha de comando
│       └── gui.py                # Interface gráfica moderna em Tkinter
├── tests/                        # Suite de testes automatizados
│   ├── test_protocol.py          # Testes dos codificadores de pacotes
│   ├── test_profile.py           # Testes de integridade binária e JSON
│   ├── test_engine.py            # Testes da sequência de comandos e BLE
│   └── test_cli.py               # Testes de argumentos e parsing
├── run_gui.bat                   # Atalho para iniciar a Interface Gráfica
├── x11_cli.bat                   # Atalho para executar comandos no terminal
├── ARCHITECTURE.md               # Especificação técnica da arquitetura de hardware
├── pyproject.toml                # Metadados de empacotamento
└── README.md                     # Documentação
```

### Início Rápido

#### Interface Gráfica (GUI)
Dê dois cliques no arquivo `run_gui.bat` ou execute:
```powershell
python -m x11_management gui
```

#### Linha de Comando (CLI)
Utilize `x11_cli.bat` ou o módulo Python:
```powershell
# Listar interfaces HID conectadas (Receptor FA60)
.\x11_cli.bat list

# Listar interfaces BLE conectadas via Bluetooth
.\x11_cli.bat list --ble

# Ler nível de bateria e status de carregamento
.\x11_cli.bat status

# Exibir configurações do perfil atual
.\x11_cli.bat show data\default_pro.data

# Testar transmissão sem gravar no mouse (Dry-Run)
.\x11_cli.bat apply data\default_pro.data --dry-run

# Aplicar perfil no hardware (aguarda ACK para cada passo)
.\x11_cli.bat apply data\default_pro.data

# Aplicar via Bluetooth Low Energy (BLE)
.\x11_cli.bat apply data\default_pro.data --ble
```

### Referência de Comandos da CLI

| Comando | Descrição |
|---|---|
| `list [--ble]` | Enumera interfaces HID ou serviços GATT BLE conectados |
| `status [--seconds N]` | Lê bateria e status de carga via relatório de monitor |
| `show <pro.data> [--json]` | Exibe o conteúdo formatado do perfil (DPI, iluminação, botões) |
| `new <pro.data> [--name N]` | Gera um novo arquivo de configuração com perfil padrão |
| `export <pro.data> <out.json>` | Exporta a configuração binária para JSON editável |
| `import <pro.data> <in.json>` | Importa a configuração JSON de volta para o binário |
| `apply <pro.data>` | Transmite os pacotes ao dispositivo com verificação de ACK |
| `set <pro.data> [opções]` | Altera parâmetros de DPI, iluminação, polling ou botões |
| `monitor [--seconds N]` | Monitora eventos de telemetria em tempo real |
| `gui` | Abre a interface gráfica |

### Testes Automatizados

```powershell
python -m unittest discover -s tests -v
```
Todos os **15/15 testes** aprovados com validação de pacotes, cálculo de checksums, integridade binária e exclusões BLE.
