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
road_type identify_circle(void);
void identify_road_type(void);
extern int left_up_find;
extern int right_up_find;
extern int left_down_find;
extern int right_down_find;
void cross_process(uint8_t img[IMG_H][IMG_W]);
//两点之间画直线（Bresenham算法），将直线上的点设为BLACK


#endif
