use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::channel::Channel;

pub mod fake;
pub mod max30102;

/// Wire format (little-endian, 8 bytes):
/// u32 timestamp_ms | u16 hr_bpm | u8 spo2_pct | u8 quality
pub type SamplePacket = [u8; 8];

/// Sensor side pushes encoded packets here, BLE side drains them.
pub static SAMPLES: Channel<CriticalSectionRawMutex, SamplePacket, 16> = Channel::new();

pub fn encode(timestamp_ms: u32, hr_bpm: u16, spo2_pct: u8, quality: u8) -> SamplePacket {
    let mut buf = [0u8; 8];
    buf[0..4].copy_from_slice(&timestamp_ms.to_le_bytes());
    buf[4..6].copy_from_slice(&hr_bpm.to_le_bytes());
    buf[6] = spo2_pct;
    buf[7] = quality;
    buf
}
