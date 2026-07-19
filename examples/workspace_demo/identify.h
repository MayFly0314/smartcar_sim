#ifndef __IDENTIFY_H_
#define __IDENTIFY_H_
typedef enum {
    DONT_KNOW=0,
    STRAIGHT ,
    SHARP_TURN, //急转弯
    SLIGHT_TURN, //轻微转弯
    CROSS,      //十字路口
    CIRCLE,     //环岛
} road_type;
extern road_type now_type;
//图像处理
void element_process(uint8_t img[IMG_H][IMG_W]);
road_type identify_straight(void);
void identify_road_type(void);
void cross_process(uint8_t img[IMG_H][IMG_W]);
//两点之间画直线（Bresenham算法），将直线上的点设为BLACK
void linktwo(uint8_t img[IMG_H][IMG_W],int x1,int y1,int x2,int y2);
//左侧单点向下延伸：以拐点及往上4行处边界点拟合直线，延伸至底部
void left_lengthen(uint8_t img[IMG_H][IMG_W],int x,int y);
//右侧单点向下延伸：以拐点及往上4行处边界点拟合直线，延伸至底部
void right_lengthen(uint8_t img[IMG_H][IMG_W],int x,int y);


#endif
