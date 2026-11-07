#include "app/app.hpp"

#include "main.h"

void appInit(void) {
}

void appRun(void) {
  HAL_GPIO_TogglePin(LED2_GPIO_PORT, LED2_PIN);
  HAL_Delay(1000);
}
