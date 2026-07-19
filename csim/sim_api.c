/* sim_api.c — 调试 API 的仿真侧实现：把绘图指令写入 draw.txt */
#include "sim_api.h"
#include <stdio.h>
#include <stdarg.h>

/* 由 sim_main.c 设置 */
FILE *g_draw_fp = NULL;
int g_frame_idx = 0;

int sim_frame_index(void) { return g_frame_idx; }

void sim_draw_point(int x, int y, uint32_t color)
{
    if (!g_draw_fp) return;
    if (x < 0 || x >= IMG_W || y < 0 || y >= IMG_H) return;
    fprintf(g_draw_fp, "P %d %d %06x\n", x, y, (unsigned)(color & 0xFFFFFFu));
}

void sim_draw_line(int x0, int y0, int x1, int y1, uint32_t color)
{
    if (!g_draw_fp) return;
    fprintf(g_draw_fp, "L %d %d %d %d %06x\n", x0, y0, x1, y1,
            (unsigned)(color & 0xFFFFFFu));
}

void sim_draw_rect(int x, int y, int w, int h, uint32_t color)
{
    if (!g_draw_fp) return;
    fprintf(g_draw_fp, "R %d %d %d %d %06x\n", x, y, w, h,
            (unsigned)(color & 0xFFFFFFu));
}

void sim_draw_circle(int cx, int cy, int r, uint32_t color)
{
    if (!g_draw_fp) return;
    fprintf(g_draw_fp, "C %d %d %d %06x\n", cx, cy, r,
            (unsigned)(color & 0xFFFFFFu));
}

void sim_draw_cross(int x, int y, int size, uint32_t color)
{
    if (!g_draw_fp) return;
    fprintf(g_draw_fp, "X %d %d %d %06x\n", x, y, size,
            (unsigned)(color & 0xFFFFFFu));
}

/* 文本经 %xx 转义（空格/换行/百分号/非 ASCII），保证协议一行一条 */
static void write_escaped(FILE *fp, const char *s)
{
    const unsigned char *p = (const unsigned char *)s;
    for (; *p; p++) {
        if (*p <= 0x20 || *p == '%' || *p >= 0x7F)
            fprintf(fp, "%%%02x", *p);
        else
            fputc(*p, fp);
    }
}

void sim_draw_text(int x, int y, uint32_t color, const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    if (!g_draw_fp) return;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    fprintf(g_draw_fp, "T %d %d %06x ", x, y, (unsigned)(color & 0xFFFFFFu));
    write_escaped(g_draw_fp, buf);
    fputc('\n', g_draw_fp);
}

void sim_log(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    /* stdout 只承载日志与进度；G 行前缀便于 GUI 区分裸 printf */
    printf("G %d ", g_frame_idx);
    fputs(buf, stdout);
    fputc('\n', stdout);
    fflush(stdout);
}

void sim_plot(const char *name, float value)
{
    if (!g_draw_fp) return;
    fprintf(g_draw_fp, "V ");
    write_escaped(g_draw_fp, name);
    fprintf(g_draw_fp, " %g\n", (double)value);
}

void sim_tag(int x, int y, const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    if (!g_draw_fp) return;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    /* 坐标不裁剪：越界 tag 出现在列表里反而帮用户发现 bug */
    fprintf(g_draw_fp, "A %d %d ", x, y);
    write_escaped(g_draw_fp, buf);
    fputc('\n', g_draw_fp);
}
