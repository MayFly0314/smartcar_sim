/*
 * image_demo.c — 示例：大津法二值化 + 双边线扫线 + 简易状态机
 *
 * 这份代码演示了仿真器的典型用法，也可直接作为你自己算法的起点。
 * 移植到单片机：把本文件 + port/sim_api.h 拷入 MCU 工程即可。
 */
#include "sim_api.h"

/* ---------- 大津法求阈值 ---------- */
static uint8_t otsu_threshold(uint8_t img[IMG_H][IMG_W])
{
    int hist[256] = {0};
    int total = IMG_W * IMG_H;
    int i, j, t;
    long sum = 0;
    long sum_b = 0;
    int w_b = 0, w_f;
    double max_var = 0.0;
    int best_t = 128;

    for (i = 0; i < IMG_H; i++)
        for (j = 0; j < IMG_W; j++)
            hist[img[i][j]]++;

    for (t = 0; t < 256; t++) sum += (long)t * hist[t];

    for (t = 0; t < 256; t++) {
        w_b += hist[t];
        if (w_b == 0) continue;
        w_f = total - w_b;
        if (w_f == 0) break;
        sum_b += (long)t * hist[t];
        {
            double m_b = (double)sum_b / w_b;
            double m_f = (double)(sum - sum_b) / w_f;
            double var = (double)w_b * w_f * (m_b - m_f) * (m_b - m_f);
            if (var > max_var) { max_var = var; best_t = t; }
        }
    }
    return (uint8_t)best_t;
}

/* ---------- 边线数组（想在别的文件用就去掉 static） ---------- */
static int left_line[IMG_H];   /* 每行左边线 x；-1 表示丢线 */
static int right_line[IMG_H];  /* 每行右边线 x；-1 表示丢线 */

/* ---------- 简易状态机演示 ---------- */
enum { ST_NORMAL = 0, ST_LOST = 1 };
static int state = ST_NORMAL;
static int lost_cnt = 0;   /* static：跨帧保持，重新运行时归零 */

void image_process(uint8_t img[IMG_H][IMG_W])
{
    int x, y;
    uint8_t th = otsu_threshold(img);
    int lost_rows = 0;

    sim_log("otsu threshold = %d", th);

    /* 二值化（写回 img，可在“处理后”视图查看） */
    for (y = 0; y < IMG_H; y++)
        for (x = 0; x < IMG_W; x++)
            img[y][x] = (img[y][x] > th) ? 255 : 0;

    /* 从底行向上，中点向两侧扫线 */
    for (y = IMG_H - 1; y >= 0; y--) {
        int mid = IMG_W / 2;
        left_line[y] = -1;
        right_line[y] = -1;

        if (img[y][mid] == 0) { lost_rows++; continue; }  /* 中点压黑：本行不扫 */

        for (x = mid; x >= 0; x--)
            if (img[y][x] == 0) { left_line[y] = x; break; }
        for (x = mid; x < IMG_W; x++)
            if (img[y][x] == 0) { right_line[y] = x; break; }

        if (left_line[y] >= 0)
            sim_draw_point(left_line[y], y, SIM_RED);
        if (right_line[y] >= 0)
            sim_draw_point(right_line[y], y, SIM_BLUE);
        if (left_line[y] >= 0 && right_line[y] >= 0)
            sim_draw_point((left_line[y] + right_line[y]) / 2, y, SIM_GREEN);
    }

    /* 状态机：连续多行丢线 -> LOST 状态 */
    if (lost_rows > IMG_H / 2) {
        lost_cnt++;
        if (lost_cnt >= 3) state = ST_LOST;
    } else {
        lost_cnt = 0;
        state = ST_NORMAL;
    }

    sim_plot("threshold", (float)th);
    sim_plot("lost_rows", (float)lost_rows);
    sim_draw_text(4, 4, SIM_YELLOW, "F%d th=%d %s",
                  sim_frame_index(), th,
                  state == ST_LOST ? "LOST" : "OK");
    sim_draw_cross(IMG_W / 2, IMG_H / 2, 5, SIM_ORANGE);
}
