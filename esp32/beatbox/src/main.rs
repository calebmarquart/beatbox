#![no_std]
#![no_main]
#![deny(
    clippy::mem_forget,
    reason = "mem::forget is generally not safe to do with esp_hal types, especially those \
    holding buffers for the duration of a data transfer."
)]
#![deny(clippy::large_stack_frames)]

use embassy_executor::Spawner;
use esp_backtrace as _;
use esp_hal::clock::CpuClock;
use esp_hal::timer::timg::TimerGroup;
use esp_hal::uart::{Config as UartConfig, UartRx};
use log::info;

mod ble;
// mod sensor;
mod uart;

extern crate alloc;

esp_bootloader_esp_idf::esp_app_desc!();

#[allow(
    clippy::large_stack_frames,
    reason = "it's not unusual to allocate larger buffers etc. in main"
)]
#[esp_rtos::main]
async fn main(spawner: Spawner) -> ! {
    esp_println::logger::init_logger_from_env();
    info!("Starting ESP32 controller...");

    let config = esp_hal::Config::default().with_cpu_clock(CpuClock::max());
    let peripherals = esp_hal::init(config);

    esp_alloc::heap_allocator!(#[esp_hal::ram(reclaimed)] size: 73744);

    let timg0 = TimerGroup::new(peripherals.TIMG0);
    let sw_interrupt =
        esp_hal::interrupt::software::SoftwareInterruptControl::new(peripherals.SW_INTERRUPT);
    esp_rtos::start(timg0.timer0, sw_interrupt.software_interrupt0);
    info!("Embassy initialized!");

    // UART1 RX defaults; connect the other controller's TX to GPIO16 and share GND.
    let uart_rx = UartRx::new(
        peripherals.UART1,
        UartConfig::default().with_baudrate(uart::BAUDRATE),
    )
    .expect("Failed to initialize UART")
    .with_rx(peripherals.GPIO16)
    .into_async();

    info!("UART receiver initialized!");
    spawner.spawn(uart::receive_task(uart_rx).unwrap());
    info!("UART receive task spawned!");

    // Each module takes the peripherals it needs and runs forever.
    ble::run(peripherals.BT).await;
    unreachable!()
}
