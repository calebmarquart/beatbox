//! UART input buffering for forwarding controller data over BLE.

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use esp_hal::Async;
use esp_hal::uart::UartRx;
use log::warn;

/// UART baud rate must match the connected controller.
pub const BAUDRATE: u32 = 115_200;

/// The default ATT MTU is 23 bytes, leaving 20 bytes for a notification value.
pub const CHUNK_SIZE: usize = 20;
const QUEUE_DEPTH: usize = 16;

/// Each queued notification contains only the bytes received for that chunk.
pub type UartPacket = heapless::Vec<u8, CHUNK_SIZE>;

/// UART task hands received chunks to the BLE task through this bounded buffer.
pub static UART_DATA: Channel<CriticalSectionRawMutex, UartPacket, QUEUE_DEPTH> = Channel::new();

/// Reads UART data and queues it for BLE notifications.
#[embassy_executor::task]
pub async fn receive_task(mut rx: UartRx<'static, Async>) {
    let mut read_buf = [0; CHUNK_SIZE];

    loop {
        match rx.read_async(&mut read_buf).await {
            Ok(0) => {}
            Ok(len) => {
                let mut packet = UartPacket::new();
                // Capacity is CHUNK_SIZE and len cannot exceed the read buffer.
                packet.extend_from_slice(&read_buf[..len]).unwrap();

                if UART_DATA.try_send(packet).is_err() {
                    warn!("UART buffer full, dropping received chunk");
                }
            }
            Err(error) => warn!("UART receive error: {:?}", error),
        }
    }
}
