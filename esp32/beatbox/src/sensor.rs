//! Sensor side: produces encoded samples and pushes them into `SAMPLES`.

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;
use embassy_time::{Duration, Instant, Timer};

/// Wire format (little-endian, 8 bytes):
/// u32 timestamp_ms | u16 hr_bpm | u8 spo2_pct | u8 quality
pub type SamplePacket = [u8; 8];

/// Sensor side pushes encoded packets here, BLE side drains them.
pub static SAMPLES: Channel<CriticalSectionRawMutex, SamplePacket, 16> = Channel::new();

fn encode(timestamp_ms: u32, hr_bpm: u16, spo2_pct: u8, quality: u8) -> SamplePacket {
    let mut buf = [0u8; 8];
    buf[0..4].copy_from_slice(&timestamp_ms.to_le_bytes());
    buf[4..6].copy_from_slice(&hr_bpm.to_le_bytes());
    buf[6] = spo2_pct;
    buf[7] = quality;
    buf
}

/// Placeholder sensor: replace the body with real I2C reads later.
pub async fn run() {
    let mut tick: u32 = 0;
    loop {
        let hr: u16 = 62 + (tick % 7) as u16;
        let spo2: u8 = if tick % 60 < 8 { 90 } else { 97 }; // fake desaturation
        let ts = Instant::now().as_millis() as u32;

        // Never block the sensor if nobody is connected: just drop when full
        let _ = SAMPLES.try_send(encode(ts, hr, spo2, 1));

        tick += 1;
        Timer::after(Duration::from_secs(1)).await;
    }
}
