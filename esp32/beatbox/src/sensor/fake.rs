use embassy_time::{Duration, Instant, Timer};

use crate::sensor::{SAMPLES, encode};

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
