/*
 * sim_api.h — 单片机移植版（空实现）
 *
 * 用法：把本文件放进单片机工程（替换仿真版 sim_api.h），
 * 在仿真器里调好的算法源文件直接拷入，无需任何修改。
 * 所有 sim_* 调用被宏展开为空操作，零代码体积、零运行开销。
 *
 * 注意：宏不求值参数——不要在 sim_* 的参数里写副作用
 * （如 sim_log("%d", cnt++)），否则仿真器里执行、车上不执行！
 */
#ifndef SIM_API_H
#define SIM_API_H

#include <stdint.h>

#ifndef IMG_W
#define IMG_W 188
#endif
#ifndef IMG_H
#define IMG_H 120
#endif

#define SIM_RED     0xFF0000u
#define SIM_GREEN   0x00CC44u
#define SIM_BLUE    0x3388FFu
#define SIM_YELLOW  0xFFD500u
#define SIM_CYAN    0x00CCCCu
#define SIM_MAGENTA 0xFF44CCu
#define SIM_ORANGE  0xFF8800u
#define SIM_PURPLE  0xAA66FFu
#define SIM_WHITE   0xFFFFFFu
#define SIM_BLACK   0x000000u

#define sim_draw_point(x, y, c)                ((void)0)
#define sim_draw_line(x0, y0, x1, y1, c)       ((void)0)
#define sim_draw_rect(x, y, w, h, c)           ((void)0)
#define sim_draw_circle(cx, cy, r, c)          ((void)0)
#define sim_draw_cross(x, y, size, c)          ((void)0)
#define sim_draw_text(x, y, c, ...)            ((void)0)
#define sim_log(...)                           ((void)0)
#define sim_plot(name, value)                  ((void)0)
#define sim_frame_index()                      (0)

void image_process(uint8_t img[IMG_H][IMG_W]);

#endif /* SIM_API_H */
