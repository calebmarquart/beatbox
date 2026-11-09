# VespriX by Beatbox

VexpriX is a hardware and software prototype for detecting possible sleep apnea events from pulse oximetry data. It was developed for natHacks 2026. A MAX30102 optical sensor captures red and infrared measurements; an STM32 runs the signal-processing and apnea-inference pipeline; an ESP32 forwards the resulting data over Bluetooth Low Energy (BLE); and a Python app displays and saves the stream.

> **Prototype:** VespriX is a student project and is not a medical device. Its readings and apnea probability are experimental and must not be used for diagnosis or treatment.

## Project components

| Component                       | Location                                         | Role                                                                                                                            |
| ------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| Sensor and signal processing    | [`stm32/beatbox-sensors`](stm32/beatbox-sensors) | Reads the MAX30102 over I²C, processes pulse-oximeter samples, estimates heart rate and SpO₂, and calculates apnea probability. |
| BLE bridge firmware             | [`esp32/beatbox`](esp32/beatbox)                 | Receives newline-delimited data over UART and advertises a BLE GATT characteristic named `Beatbox`.                             |
| Live dashboard and BLE listener | [`server`](server)                               | Connects to the BLE peripheral, plots incoming data, records local history and events, and can export samples as CSV.           |
| DSP and model experiments       | [`dsp`](dsp)                                     | Python tooling for signal-processing and apnea-model data preparation and experimentation.                                      |

For setup and run instructions, see [Getting Started](#getting-started). It includes a demo mode that works without the hardware.

## Hardware Requirements

- ESP32 development board with USB programming and BLE support.
- STM32 NUCLEO-F446RE development board.
- MAX30102 optical pulse-oximeter module connected to the STM32 I²C bus (PB8/SCL, PB9/SDA).
- Jumper wires and USB cables for both development boards; a computer with BLE support.
- UART link from STM32 UART4 TX (PA0) to ESP32 UART2 RX (GPIO26), plus a shared ground. Firmware uses 115200 baud, 8 data bits, no parity, and 1 stop bit. Connect 3.3 V logic only; do not connect the boards' TX pins together for this one-way stream.

## Quick demo

To preview the dashboard without any hardware, install [uv](https://docs.astral.sh/uv/), then run:

```sh
cd server
uv sync --locked
uv run dashboard.py --demo
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Getting Started

### Preview the dashboard without hardware

Install [uv](https://docs.astral.sh/uv/), then from the repository root run:

```sh
cd server
uv sync --locked
uv run dashboard.py --demo
```

Open **http://127.0.0.1:8000** in a browser. Demo mode generates sample readings locally, so no boards or Bluetooth connection are needed. Press `Ctrl+C` to stop it.

### Hardware for a live run

- ESP32 development board with USB serial programming and BLE.
- ST NUCLEO-F446RE board.
- MAX30102 optical sensor module.
- USB cables, jumper wires, and a computer with Bluetooth Low Energy support.

Connect the MAX30102 to the STM32 I²C1 bus:

| MAX30102 | STM32 NUCLEO-F446RE                      |
| -------- | ---------------------------------------- |
| SCL      | PB8 / I2C1_SCL                           |
| SDA      | PB9 / I2C1_SDA                           |
| GND      | GND                                      |
| VIN      | Sensor-compatible supply for your module |

Connect the STM32 UART stream to the ESP32:

| STM32 NUCLEO-F446RE | ESP32             |
| ------------------- | ----------------- |
| PA0 / UART4_TX      | GPIO26 / UART2_RX |
| GND                 | GND               |

The UART link is one-way; do not connect the two boards' TX pins together. Both firmware images use 115200 baud, 8 data bits, no parity, and 1 stop bit. Use 3.3 V UART logic and check your MAX30102 breakout's voltage requirements before connecting power.

### Build and flash the STM32

Install CMake, Ninja, and the GNU Arm Embedded compiler (`arm-none-eabi-gcc`). Connect the NUCLEO-F446RE by USB so its onboard ST-LINK can program it. The first CMake build may need internet access to fetch CMSIS-DSP.

```sh
cd stm32/beatbox-sensors
cmake --preset Release
cmake --build --preset Release
```

The resulting ELF is under `build/Release/beatbox-sensors.elf` (or `build/Release/beatbox-sensors`, depending on output naming). Program that artifact using STM32CubeProgrammer or STM32CubeIDE with the ST-LINK probe, then reset the board. The STM32 reads the sensor, runs the signal-processing and inference pipeline, and emits CSV records on PA0.

### Build and flash the ESP32

Install Rust via [rustup](https://rustup.rs/), then install the Espressif Xtensa toolchain and flash utility. The `esp32/beatbox/rust-toolchain.toml` selects the `esp` toolchain; the firmware target is `xtensa-esp32s3-none-elf`.

```sh
cargo install espup --locked
espup install --targets esp32
source ~/export-esp.sh
cargo install espflash --locked
```

Source `~/export-esp.sh` in the shell that will build, then:

```sh
cd esp32/beatbox
cargo build --release --target xtensa-esp32s3-none-elf
espflash flash --monitor target/xtensa-esp32s3-none-elf/release/beatbox
```

Connect the ESP32 by USB before flashing. If multiple serial devices are connected, use the port option listed by `espflash flash --help`. The serial monitor shows startup and UART receive logs. The ESP32 advertises over BLE as **Beatbox**.

### Run the live dashboard

Leave the STM32 and ESP32 powered and connected. In another terminal, from the repository root:

```sh
cd server
uv sync --locked
uv run dashboard.py
```

Open **http://127.0.0.1:8000**. The dashboard scans for the BLE peripheral named `Beatbox`, subscribes to its data characteristic, and reconnects if the connection drops. The computer running the dashboard must have Bluetooth enabled and allow Python to use it. See the [Bleak documentation](https://bleak.readthedocs.io/en/latest/) for platform-specific BLE setup.

To inspect raw BLE notification bytes in a terminal instead, run:

```sh
cd server
uv run ble_listener.py
```

Stop the dashboard or listener with `Ctrl+C`.

### Saved history

The dashboard stores sample history and threshold-crossing events in `server/beatbox_history.sqlite3` on the computer running the dashboard. Use the dashboard's **History** and **Events** tabs to browse saved records; CSV export is available in the interface.

## Team

Beatbox team members:

1. **Alexander Williams-Letondre** — Team Leader, Data Science
2. **Jessica Lopushinsky** — Bioscientist
3. **Rasheed Othman** — Engineer, Hardware
4. **Caleb Marquart** — Engineer, UI

See [CONTRIBUTERS.md](CONTRIBUTERS.md) for the project contributor list.

## Dependencies, sources, and credits

Project-owned code and documentation are provided under the [MIT License](LICENSE). Third-party components retain their own licenses; see the license files in their respective directories.

- ESP32 firmware: Rust (the repository's `esp` toolchain), `esp-hal`, `esp-radio`, `trouble-host`, and the Rust-on-ESP build tools. See the [Rust on ESP Book](https://docs.espressif.com/projects/rust/book/) and [`espflash` guide](https://docs.espressif.com/projects/rust/book/getting-started/tooling/espflash.html).
- Dashboard: Python 3.10 or newer, [uv](https://docs.astral.sh/uv/), and [Bleak](https://bleak.readthedocs.io/). Exact Python dependencies are managed in [`server/pyproject.toml`](server/pyproject.toml) and [`server/uv.lock`](server/uv.lock).
- STM32 firmware: CMake, Ninja, the GNU Arm Embedded toolchain, and ST-LINK-compatible programming tools. CMake fetches [CMSIS-DSP](https://github.com/ARM-software/CMSIS-DSP). The configured board is the [ST NUCLEO-F446RE](https://www.st.com/en/evaluation-tools/nucleo-f446re.html).
- Sensor reference: [MAX30102 product page and data sheet](https://www.analog.com/en/products/max30102.html).
- The DSP data-preparation code expects the OSASUD dataset as a local file under `dsp/assets/`; the dataset itself is not included in this repository. See the [OSASUD paper and dataset description](https://www.nature.com/articles/s41597-022-01272-y) for provenance and access information.
- Introduction to photoplethysmography, Panicos A Kyriacou
