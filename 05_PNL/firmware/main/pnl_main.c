/* Software task architecture for the PNL display target. Board drivers remain
 * bench-gated until the manufacturer schematic and ESP-IDF component versions
 * are verified; these tasks deliberately do not touch GPIO. */
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static void lvgl_render_task(void *arg) { (void)arg; for (;;) vTaskDelay(pdMS_TO_TICKS(16)); }
static void hcm_client_task(void *arg) { (void)arg; for (;;) vTaskDelay(pdMS_TO_TICKS(250)); }
static void sensor_task(void *arg) { (void)arg; for (;;) vTaskDelay(pdMS_TO_TICKS(1000)); }
static void heartbeat_task(void *arg) { (void)arg; for (;;) vTaskDelay(pdMS_TO_TICKS(5000)); }
static void telemetry_task(void *arg) { (void)arg; for (;;) vTaskDelay(pdMS_TO_TICKS(5000)); }

void app_main(void) {
    /* Network, local acquisition, rendering, heartbeat, and telemetry have
     * independent timing. Validated board components will be inserted behind
     * these task boundaries during the hardware bring-up gate. */
    xTaskCreate(lvgl_render_task, "pnl_lvgl", 4096, NULL, 5, NULL);
    xTaskCreate(hcm_client_task, "pnl_hcm", 4096, NULL, 4, NULL);
    xTaskCreate(sensor_task, "pnl_sensor", 3072, NULL, 4, NULL);
    xTaskCreate(heartbeat_task, "pnl_heartbeat", 3072, NULL, 4, NULL);
    xTaskCreate(telemetry_task, "pnl_telemetry", 3072, NULL, 4, NULL);
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
}
