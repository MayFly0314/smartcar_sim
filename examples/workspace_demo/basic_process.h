#ifndef __BASIC_PROCESS_H
#define __BASIC_PROCESS_H
#include "sim_api.h"
#define BLACK 0
#define WHITE 255
#define MAX_CORNERS 4   //4种拐点类型各占一个固定位置
typedef enum {
    //定义拐点类型的enum，四种类型对应有
    //如1对应右边边界向右边拐形成的拐点
    CORNER_NONE=0,
    CORNER_L_DOWN=1,
    CORNER_L_UP=2,
    CORNER_R_DOWN=3,
    CORNER_R_UP=4,
}corner_type_t;//拐点类型enum的名称

typedef struct{
    //定义拐点结构体，包含拐点的横纵坐标和拐点的类型
    int x;
    int y;
    corner_type_t type;
}corner_t;

extern  int left_boundary[IMG_H]; //左边界数组
extern  int right_boundary[IMG_H];//右边界数组
extern  int road_width[IMG_H];//原始左右边界之间的宽度
extern  uint8_t left_boundary_valid[IMG_H];
extern  uint8_t right_boundary_valid[IMG_H];
extern  int center[IMG_H]; //静态全局变量，全局可以拿到中线的数据
extern  corner_t corner_list[MAX_CORNERS];
extern  int max_length;//最长白列的长度
extern  int max_white_x;//最长白列横坐标
extern  int left_lost_rows;
extern  int right_lost_rows;
extern  int both_lost_rows;//最长白列范围内左右边界同时丢失的行数
extern  int center_var;//中线方差，衡量中线离散程度

//3x3滤波
void filter_3x3(uint8_t img[IMG_H][IMG_W]);

void find_longest_whiteline(uint8_t img[IMG_H][IMG_W]);
//在指定横坐标范围内查找最长白列，结果仍写入max_white_x和max_length
void find_longest_whiteline_range(uint8_t img[IMG_H][IMG_W],int start_x,int end_x);
//扫线：查找左右边界数组和初步中线数组，结果存入模块内全局变量
void scan_lines(uint8_t img[IMG_H][IMG_W]);

//在指定行范围内查找下拐点（左下、右下），结果存入拐点结构体数组
void find_corner_down(int start_line,int end_line);

//在指定行范围内查找上拐点（左上、右上），结果存入拐点结构体数组
void find_corner_up(int start_line,int end_line);


#endif
