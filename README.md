# beatbox

Sleep apnea detector for natHacks 2026

## ESP32

### Build

```
cargo build --release
```

### Run

This command builds, flashes, and monitors the firmware running on the ESP32

```
cargo run
```

For **flash only** use `espflash`

```
espflash flash target/xtensa-esp32s3-none-elf/release/beatbox
```
