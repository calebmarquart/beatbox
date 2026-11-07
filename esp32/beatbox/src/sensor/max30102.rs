use embassy_time::{Instant, Timer};
use esp_hal::Async;
use esp_hal::i2c::master::I2c;
use max30102::{Max30102Async, PulseWidth, SampleRate, SlaveAddr};

use crate::sensor::SAMPLES;

#[embassy_executor::task]
pub async fn sensor_task(i2c: I2c<'static, Async>) {
    let mut sensor = Max30102Async::new(i2c, SlaveAddr::Default);

    if !sensor.verify_part_id().await.unwrap() {
        log::error!("Max30102 not found, check wiring and I2C address");
        return;
    }

    log::info!("Max30102 found, part ID verified");
    sensor.reset().await.unwrap();
    // sensor.set_sample_rate(SampleRate::Rate100).await.unwrap();
    // sensor.set_pulse_width(PulseWidth::Pw411).await.unwrap();
    // sensor.start_spo2_mode().await.unwrap();
    // sensor.clear_fifo().await.unwrap();
    let temp = sensor.read_temperature().await.unwrap();
    log::info!("Max30102 temperature: {:.2} °C", temp);

    log::info!("Reset and configured Max30102, starting sample loop");

    loop {
        if sensor.get_fifo_samples_available().await.unwrap() > 0 {
            let (_red, _ir) = sensor.read_fifo_sample().await.unwrap();
            // TODO: Process sample...
            let hr = 100; // TODO: temporary test value
            let pct = 100; // TODO: temporary test value
            let sample = crate::sensor::encode(Instant::now().as_millis() as u32, hr, pct, 1);

            // Send the sample
            match SAMPLES.try_send(sample) {
                Ok(_) => {
                    log::info!("Sample sent: hr={}, pct={}", hr, pct);
                }
                Err(_) => {
                    // Channel is full, drop the sample
                    log::warn!("SAMPLES channel full, dropping sample");
                }
            }
        }
        Timer::after_millis(10).await;
    }
}
