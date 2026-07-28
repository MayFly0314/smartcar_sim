#ifndef LANE_REPAIR_H
#define LANE_REPAIR_H
#include "image_config.h"

void linktwo(uint8_t img[IMG_H][IMG_W],int x1,int y1,int x2,int y2);
void left_lengthen(uint8_t img[IMG_H][IMG_W],int x,int y);
void right_lengthen(uint8_t img[IMG_H][IMG_W],int x,int y);
void cross_process(uint8_t img[IMG_H][IMG_W]);



#endif

