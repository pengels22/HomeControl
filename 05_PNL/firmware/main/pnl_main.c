/* Pass 4 contract scaffold. Board drivers remain bench-gated until the
 * manufacturer schematic and ESP-IDF component versions are verified. */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void) {
    /* The production implementation will start independent HCM, sensor,
     * LVGL, audio, and heartbeat tasks. No GPIO is touched by this scaffold. */
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}
