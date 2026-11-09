//! UART input buffering for forwarding controller data over BLE.

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use esp_hal::Async;
use esp_hal::uart::UartRx;

/// UART baud rate must match the connected controller.
pub const BAUDRATE: u32 = 115_200;

/// Maximum CSV record size, including CR/LF. Matches the server's 48-byte limit.
pub const UART_LINE_MAX: usize = 48;
/// Maximum ATT MTU supported by Trouble Host's default 251-byte packet pool.
pub const BLE_ATT_MTU_MAX: usize = 247;
/// A notification value uses three ATT bytes for its opcode and handle.
pub const BLE_PACKET_MAX: usize = BLE_ATT_MTU_MAX - 3;
const READ_BUFFER_SIZE: usize = 1028;
const QUEUE_DEPTH: usize = 512;
const LOG_EVERY_LINES: u32 = 100;
/// Forward one sample for every N complete UART samples; intervening samples are discarded.
pub const SEND_EVERY_N_SAMPLES: u32 = 1;
const _: () = assert!(SEND_EVERY_N_SAMPLES > 0);

/// Raw UART line, including CR/LF, forwarded unchanged to BLE.
pub type UartPacket = heapless::Vec<u8, UART_LINE_MAX>;
/// One BLE notification payload, up to the negotiated ATT MTU limit.
pub type BlePacket = heapless::Vec<u8, BLE_PACKET_MAX>;

/// UART task hands complete raw lines to the BLE task through this bounded buffer.
pub static UART_DATA: Channel<CriticalSectionRawMutex, UartPacket, QUEUE_DEPTH> = Channel::new();

/// Reads UART bytes through LF, prints each full line as hex, and forwards it unchanged.
#[embassy_executor::task]
pub async fn receive_task(mut rx: UartRx<'static, Async>) {
    let mut read_buf = [0; READ_BUFFER_SIZE];
    let mut line = UartPacket::new();
    let mut queue_full_reported = false;
    let mut discard_until_lf = false;
    let mut lines_seen = 0u32;

    loop {
        match rx.read_async(&mut read_buf).await {
            Ok(0) => {}
            Ok(len) => {
                for byte in &read_buf[..len] {
                    if discard_until_lf {
                        if *byte == b'\n' {
                            discard_until_lf = false;
                        }
                        continue;
                    }

                    if line.push(*byte).is_err() {
                        esp_println::println!(
                            "UART line exceeded {} bytes; discarding it",
                            UART_LINE_MAX
                        );
                        line.clear();
                        discard_until_lf = true;
                        continue;
                    }

                    if *byte == b'\n' {
                        if lines_seen % LOG_EVERY_LINES == 0 {
                            esp_println::println!(
                                "UART RX {} bytes: {:02x?}",
                                line.len(),
                                line.as_slice()
                            );
                        }
                        lines_seen = lines_seen.wrapping_add(1);

                        if lines_seen % SEND_EVERY_N_SAMPLES == 0 {
                            if UART_DATA.try_send(line.clone()).is_err() {
                                if !queue_full_reported {
                                    esp_println::println!("UART BLE queue full; dropping lines");
                                    queue_full_reported = true;
                                }
                            } else {
                                queue_full_reported = false;
                            }
                        }

                        line.clear();
                    }
                }
            }
            Err(error) => {
                esp_println::println!("UART receive error: {:?}; resyncing at LF", error);
                line.clear();
                discard_until_lf = true;
            }
        }
    }
}
