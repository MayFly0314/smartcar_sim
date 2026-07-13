/*
 * sim_api.h — 智能车图像仿真器调试 API（仿真版）
 *
 * 用法：算法源文件 #include "sim_api.h" 后即可调用下列调试函数。
 * 移植到单片机：把 port/sim_api.h（同名空实现版）放进 MCU 工程替换本文件，
 * 算法代码一个字符都不用改。
 *
 * sim_log / sim_draw_text 为 printf 风格，安全格式符：%d %u %x %s %c %f
 * （不要用 %zu %hhu %lld，Windows msvcrt 不支持）
 */
#ifndef SIM_API_H
#define SIM_API_H

#include <stdint.h>

/* 图像尺寸：仿真器编译时用 -DIMG_W/-DIMG_H 注入；
 * 无 -D（如直接拷到 MCU 工程）时使用下方默认值 */
#ifndef IMG_W
#define IMG_W 188
#endif
#ifndef IMG_H
#define IMG_H 120
#endif

/* ===== 颜色常量 (0xRRGGBB) ===== */
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

#ifdef __cplusplus
extern "C" {
#endif

/* ===== 绘图（叠加在图像上显示；坐标越界自动裁剪，不会崩溃）===== */
void sim_draw_point(int x, int y, uint32_t color);
void sim_draw_line(int x0, int y0, int x1, int y1, uint32_t color);
void sim_draw_rect(int x, int y, int w, int h, uint32_t color);   /* 空心矩形 */
void sim_draw_circle(int cx, int cy, int r, uint32_t color);      /* 空心圆 */
void sim_draw_cross(int x, int y, int size, uint32_t color);      /* 十字标记 */

/* 文本锚定到图像坐标，按屏幕分辨率渲染（printf 风格） */
void sim_draw_text(int x, int y, uint32_t color, const char *fmt, ...);

/* ===== 日志（输出到仿真器控制台，自动带 [帧号] 前缀）===== */
void sim_log(const char *fmt, ...);

/* ===== 数值监视（跨帧曲线：误差/状态/打角等）===== */
void sim_plot(const char *name, float value);

/* 当前帧号（0 起）。仅调试用，勿参与算法逻辑！ */
int sim_frame_index(void);

/* ===== 用户必须实现的唯一入口 =====
 * 每帧调用一次。img 可读可写（写入的结果会显示在"处理后"视图）。
 * static/全局变量跨帧保持——状态机直接用。 */
void image_process(uint8_t img[IMG_H][IMG_W]);

#ifdef __cplusplus
}
#endif

#endif /* SIM_API_H */
