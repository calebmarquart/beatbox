#include "app/app.hpp"
#include "app/interrupts.hpp"
#include "i2c.h"
#include "main.h"
#include "max30102/max30102.hpp"
#include "pipeline/pipeline.hpp"
#include "uart/dma_writer.hpp"
#include "units/absorbance.hpp"
#include "usart.h"
#include <array>
#include <cstddef>
#include <cstdio>
#include <span>

using namespace max30102;

constexpr Config cfg{};

static Sensor sensor{hi2c1};
static pipeline::Pipeline ppgPipeline;
static std::array<pipeline::Processed, Sensor::fifoDepth> processed;
static uart::DmaWriter *waveform_writer = nullptr;

// Latest HR/SpO2 result (new every 1 s) and apnea probability (new every
// window), repeated on every sample line. -1 = none yet / invalid
static RfOximeter<pipeline::kPipelineFsHz>::Result latestVitals{};
static float latestApnea = -1.0f;

static void send(UART_HandleTypeDef &uart, const char *buf, int len) {
  if (len <= 0) {
    return;
  }

  HAL_UART_Transmit(&uart, reinterpret_cast<const uint8_t *>(buf), len, 10);
}

static void report(const pipeline::Processed &o) {
  if (o.vitals) {
    latestVitals = *o.vitals;
  }
  if (o.apnea_likelihood) {
    latestApnea = *o.apnea_likelihood;
  }

  // red_ppm,ir_ppm,hr,spo2,correl,apnea  (hr/spo2/apnea = -1 when invalid)
  char buf[80];
  const int len = snprintf(
      buf, sizeof buf, "%ld,%ld,%.1f,%.1f,%.2f,%.3f\r\n", long(o.y_red * 1e6f),
      long(o.y_ir * 1e6f), latestVitals.hrBpm.value_or(-1.0f),
      latestVitals.spo2.value_or(-1.0f), latestVitals.correl, latestApnea);
  if (len <= 0 || std::size_t(len) >= sizeof buf) {
    return;
  }

  waveform_writer->write({buf, static_cast<std::size_t>(len)});
  send(huart2, buf, len);
}

void appInit(void) {
  waveform_writer = &interrupts::init(huart4);

  if (sensor.init(cfg) != HAL_OK) {
    Error_Handler();
  }

  interrupts::registerSensor(sensor);
  sensor.beginFifoReception();
}

void appRun() {
  if (sensor.busy()) {
    waveform_writer->flush();
    return;
  }

  // Take the finished batch, start the next one, then process while it
  // transfers
  std::array<Sample, Sensor::fifoDepth> fifo{};
  const std::size_t n = sensor.takeFifo(fifo);
  sensor.beginFifoReception();

  std::array<pipeline::Sample, Sensor::fifoDepth> absorbance{};
  for (std::size_t i = 0; i < n; ++i) {
    absorbance[i] = pipeline::Sample(Absorbance::try_from_counts(fifo[i].red),
                                     Absorbance::try_from_counts(fifo[i].ir));
  }

  if (!ppgPipeline.run(std::span{absorbance}.first(n), processed)) {
    Error_Handler();
  }

  for (const auto &o : std::span{processed}.first(n)) {
    report(o);
  }

  waveform_writer->flush();
}
