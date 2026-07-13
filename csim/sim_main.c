/*
 * sim_main.c — 仿真器 harness 主程序
 *
 * 用法： sim.exe <input.bin> <frame_count> <out_dir>
 *   input.bin    : frame_count 帧，每帧 IMG_H*IMG_W 字节 8 位灰度
 *   out_dir      : 输出目录，生成 draw.txt 与 frames_out.bin
 *
 * 每帧：读入 -> image_process() -> 处理后图像追加写 frames_out.bin
 *       绘图指令写 draw.txt（F 行分隔并记录耗时）
 *       进度行写 stdout： F <idx>
 */
#include "sim_api.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

extern FILE *g_draw_fp;
extern int g_frame_idx;

static uint8_t g_img[IMG_H][IMG_W];

int main(int argc, char **argv)
{
    const char *in_path, *out_dir;
    long frame_count;
    char path[1024];
    FILE *in_fp, *out_fp;
    LARGE_INTEGER freq, t0, t1;
    long i;

    if (argc < 4) {
        fprintf(stderr, "usage: sim.exe <input.bin> <frame_count> <out_dir>\n");
        return 2;
    }
    in_path = argv[1];
    frame_count = strtol(argv[2], NULL, 10);
    out_dir = argv[3];

    in_fp = fopen(in_path, "rb");
    if (!in_fp) { fprintf(stderr, "cannot open input: %s\n", in_path); return 3; }

    snprintf(path, sizeof(path), "%s/draw.txt", out_dir);
    g_draw_fp = fopen(path, "wb");
    if (!g_draw_fp) { fprintf(stderr, "cannot open draw.txt\n"); fclose(in_fp); return 3; }

    snprintf(path, sizeof(path), "%s/frames_out.bin", out_dir);
    out_fp = fopen(path, "wb");
    if (!out_fp) { fprintf(stderr, "cannot open frames_out.bin\n"); fclose(in_fp); fclose(g_draw_fp); return 3; }

    QueryPerformanceFrequency(&freq);

    for (i = 0; i < frame_count; i++) {
        size_t n = fread(g_img, 1, IMG_W * IMG_H, in_fp);
        if (n != (size_t)(IMG_W * IMG_H)) {
            fprintf(stderr, "short read at frame %ld\n", i);
            break;
        }
        g_frame_idx = (int)i;

        QueryPerformanceCounter(&t0);
        image_process(g_img);
        QueryPerformanceCounter(&t1);

        {
            double us = (double)(t1.QuadPart - t0.QuadPart) * 1e6 / (double)freq.QuadPart;
            /* 协议：处理期间用户指令已写入；F 行收尾本帧（含耗时） */
            fprintf(g_draw_fp, "F %ld %.1f\n", i, us);
        }

        /* 处理后图像落盘 */
        fwrite(g_img, 1, IMG_W * IMG_H, out_fp);

        /* 进度行 */
        printf("F %ld\n", i);
        fflush(stdout);
    }

    fclose(in_fp);
    fclose(out_fp);
    fclose(g_draw_fp);
    g_draw_fp = NULL;
    return 0;
}
