#include "sim_api.h"
#include "basic_process.h"
#include "identify.h"
#include "circle.h"
#include <string.h>
void image_process(uint8_t img[IMG_H][IMG_W])
{
    int y,i;
    filter_3x3(img);

    find_longest_whiteline(img);//得到最长白列长度，最长白列横坐标
    scan_lines(img);//得到左右边界数组，中线数组，左右丢线数
    //初始化拐点数组（4种拐点类型各占一个固定位置）
    memset(corner_list,0,sizeof(corner_list));
    
    identify_road_type();//得到此帧赛道类型

    element_process(img);

    //下面是打印部分，在图上显示出来
    for(y=IMG_H-1;y>=IMG_H-max_length;y--)
    {
        if(left_boundary_valid[y])sim_draw_point(left_boundary[y],y,SIM_RED);
        else sim_draw_point(left_boundary[y],y,SIM_PURPLE);
        if(right_boundary_valid[y])sim_draw_point(right_boundary[y],y,SIM_GREEN);
        else sim_draw_point(right_boundary[y],y,SIM_PURPLE);
        if(center[y]>=0)sim_draw_point(center[y],y,SIM_BLUE);
    }
    for(i=0;i<MAX_CORNERS;i++)
    {
        if(corner_list[i].type!=CORNER_NONE)
        {
            sim_draw_cross(corner_list[i].x,corner_list[i].y,3,SIM_ORANGE);
            if(corner_list[i].type==CORNER_L_DOWN||
               corner_list[i].type==CORNER_L_UP)
                sim_tag(corner_list[i].x,corner_list[i].y,
                        "L角点 t=%d",corner_list[i].type);
            else
                sim_tag(corner_list[i].x,corner_list[i].y,
                        "R角点 t=%d",corner_list[i].type);
            switch(corner_list[i].type)
            {
                case 0: break;
                case 1: sim_plot("corner_l_down",corner_list[i].x);break;
                case 2: sim_plot("corner_l_up",corner_list[i].x);break;
                case 3: sim_plot("corner_r_down",corner_list[i].x);break;
                case 4: sim_plot("corner_r_up",corner_list[i].x);break;
            }
        }

    }
    /*for(i=0;i<IMG_H-1;i++)//画出最长白列
    {
        sim_draw_point(max_white_x,i,SIM_BLUE);
    }*/
    switch(now_type)
    {
        case 0:sim_draw_text(0,0,SIM_WHITE,"none");break;
        case 1:sim_draw_text(0,0,SIM_WHITE,"straighet");break;
        case 2:sim_draw_text(0,0,SIM_WHITE,"sharp_turn");break;
        case 3:sim_draw_text(0,0,SIM_WHITE,"slight_turn");break;
        case 4:sim_draw_text(0,0,SIM_WHITE,"cross");break;
        case 5:sim_draw_text(0,0,SIM_WHITE,"circle");break;

    }
    switch(circle_context.state)
    {
        case CIRCLE_IDLE:
            sim_tag(0,0,"circle state=IDLE");
            break;
        case CIRCLE_ENTRY_DOWN:
            sim_tag(0,0,"circle state=ENTRY_DOWN");
            break;
        case CIRCLE_ENTRY_UP_EXTEND:
            sim_tag(0,0,"circle state=ENTRY_UP_EXTEND");
            break;
        case CIRCLE_ENTRY_LINK:
            sim_tag(0,0,"circle state=ENTRY_LINK");
            break;
        case CIRCLE_ENTRY_SLOPE_EXTEND:
            sim_tag(0,0,"circle state=ENTRY_SLOPE_EXTEND");
            break;
        case CIRCLE_INSIDE:
            sim_tag(0,0,"circle state=INSIDE");
            break;
        case CIRCLE_EXIT_LINK:
            sim_tag(0,0,"circle state=EXIT_LINK");
            break;
        case CIRCLE_EXIT_SLOPE_EXTEND:
            sim_tag(0,0,"circle state=EXIT_SLOPE_EXTEND");
            break;
        case CIRCLE_EXIT_EXTEND:
            sim_tag(0,0,"circle state=EXIT_EXTEND");
            break;
        case CIRCLE_EXIT_COMPLETE:
            sim_tag(0,0,"circle state=EXIT_COMPLETE");
            break;
        default:
            sim_tag(0,0,"circle state=UNKNOWN");
            break;
    }
    if(max_length>=63)sim_draw_text(0,10,SIM_WHITE,"var=%d",center_var);//如果最长白列比较长就输出下中线方差
    sim_plot("left_lost_rows",left_lost_rows);
    sim_plot("right_lost_rows",right_lost_rows);
    sim_plot("max_white_x",max_white_x);

    sim_draw_text(0,4,SIM_WHITE,"length:%d",max_length);

    
}
