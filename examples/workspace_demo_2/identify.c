#include "basic_process.h"
#include "identify.h"
#include "circle.h"
#include <stdlib.h>
#include "image_config.h"
#define STRAIGHT_TH  59//直道判别标准
#define TURN_TH 57
#define ROAD_WIDTH 150
#define STRAIGHT_FIT_MIN_POINTS 10   //拟合直道正常宽度趋势所需的最少有效行数
#define STRAIGHT_WIDTH_MARGIN 10     //远端实际宽度允许超过直道预测宽度的像素余量
#define STRAIGHT_WIDTH_CONSECUTIVE 5 //连续超过余量达到该行数时，不再判定为直道
#define CROSS_CONTINUATION_FRAMES 2  //严格识别为十字后允许宽松识别的最大帧数
int left_up_find,right_up_find,left_down_find,right_down_find;
road_type now_type = DONT_KNOW;
static int cross_continuation_left=0;

/*
 *@brief 根据上拐点识别十字路口
 *@param allow_single_up 是否允许仅找到一个上拐点时延续十字状态
 *@return CROSS（十字路口）或 DONT_KNOW（不是十字路口）
 */
static road_type identify_cross_corners(int allow_single_up)
{
    left_up_find=0;right_up_find=0;
    //先搜索上拐点
    find_corner_up(IMG_H-1,0);
    if(corner_list[1].type==CORNER_L_UP)left_up_find=1;
    if(corner_list[3].type==CORNER_R_UP)right_up_find=1;
    if(left_up_find&&right_up_find)
    {
        //确认是十字路口，基于上拐点位置搜索下拐点
        int search_end=(corner_list[1].y<corner_list[3].y)?corner_list[1].y:corner_list[3].y;
        find_corner_down(IMG_H-1,search_end);

        //同一侧上拐点必须位于下拐点上方，顺序反了就丢弃下拐点并保留上拐点延长
        if(corner_list[0].type!=CORNER_NONE&&
           corner_list[0].y<=corner_list[1].y)
            corner_list[0].type=CORNER_NONE;
        if(corner_list[2].type!=CORNER_NONE&&
           corner_list[2].y<=corner_list[3].y)
            corner_list[2].type=CORNER_NONE;

        return CROSS;
    }
    if(allow_single_up&&(left_up_find||right_up_find))
        return CROSS;
    return DONT_KNOW;
}

/*
 *@brief 严格识别十字路口，必须同时找到左右两个上拐点
 *@return CROSS（十字路口）或 DONT_KNOW（不是十字路口）
 */
road_type identify_cross(void)
{
    return identify_cross_corners(0);
}
/*
 *@brief 识别赛道类型
 *@return 赛道类型保存在全局变量now_type中
*/
road_type identify_straight(void)
{
    int y;
    int roi_top=IMG_H-max_length;
    int fit_start;
    int fit_count=0;
    long sum_y=0,sum_width=0,sum_yy=0,sum_ywidth=0;
    double denominator,slope,intercept;
    int consecutive=0;

    if(max_length<STRAIGHT_TH)
        return DONT_KNOW;

    //使用可见区域中下部拟合正常直道的宽度趋势，避开远端待判断区域
    fit_start=roi_top+max_length/3;
    for(y=fit_start;y<IMG_H;y++)
    {
        if(left_boundary_valid[y]&&right_boundary_valid[y])
        {
            sum_y+=y;
            sum_width+=road_width[y];
            sum_yy+=(long)y*y;
            sum_ywidth+=(long)y*road_width[y];
            fit_count++;
        }
    }
    if(fit_count<STRAIGHT_FIT_MIN_POINTS)
        return DONT_KNOW;

    denominator=(double)fit_count*sum_yy-(double)sum_y*sum_y;
    if(denominator==0.0)
        return DONT_KNOW;
    slope=((double)fit_count*sum_ywidth-(double)sum_y*sum_width)/denominator;
    intercept=((double)sum_width-slope*sum_y)/fit_count;

    //远端连续多行明显宽于预测值，说明宽度趋势已偏离直道模型
    for(y=roi_top;y<fit_start;y++)
    {
        double predicted=slope*y+intercept;
        if((double)road_width[y]>predicted+STRAIGHT_WIDTH_MARGIN)
        {
            consecutive++;
            if(consecutive>=STRAIGHT_WIDTH_CONSECUTIVE)
                return DONT_KNOW;
        }
        else
        {
            consecutive=0;
        }
    }
    return STRAIGHT;
}
void identify_road_type(void)
{
    now_type=DONT_KNOW;

    //环岛入口确认后由环岛内部状态机接管，不再重复执行入口识别
    if(circle_context.state!=CIRCLE_IDLE)
    {
        identify_circle_state();
        now_type=CIRCLE;
        return;
    }

    //严格十字后的两帧优先宽松识别；失败则当帧恢复正常判断
    if(cross_continuation_left>0)
    {
        now_type=identify_cross_corners(1);
        if(now_type==CROSS)
        {
            //当前帧仍满足严格十字条件时，以当前帧为起点刷新两帧预算
            if(max_length>=STRAIGHT_TH&&
               left_lost_rows>=10&&right_lost_rows>=10&&
               left_up_find&&right_up_find)
                cross_continuation_left=CROSS_CONTINUATION_FRAMES;
            else
                cross_continuation_left--;
            return;
        }
        cross_continuation_left=0;
    }

    if(max_length>=STRAIGHT_TH)//直线或十字路口或缓弯或未知
    {
        if(center_var<100&&left_lost_rows<10&&right_lost_rows<10&&identify_straight()==STRAIGHT)
        {
            //中线稳定，直道
            now_type=STRAIGHT;
        }
        else
        {
            //不是直道时先识别环岛，失败后再继续其他赛道类型判断
            now_type=identify_circle();
            if(now_type==DONT_KNOW&&
               left_lost_rows>=10&&right_lost_rows>=10)
            {
                now_type=identify_cross();
                if(now_type==CROSS)
                    cross_continuation_left=CROSS_CONTINUATION_FRAMES;
            }

            if(now_type==DONT_KNOW)
            {
                //不是十字路口，根据丢线情况区分
                if(left_lost_rows<10&&right_lost_rows<10)
                    now_type=SLIGHT_TURN;//丢线少→缓弯
                //丢线多→保持DONT_KNOW
            }
        }
    }
    else if(max_length<=TURN_TH)//弯道
    {
        
        if(right_lost_rows>=40 ||left_lost_rows>=40)
        {
            now_type=SHARP_TURN;
        }
        
    }
}

void sharp_turn_process(void)
{
    int i;
    if(right_lost_rows>=40)
    {
        //右边丢线，右转弯
        for(i=IMG_H-1;i>IMG_H-1-max_length;i--)
        {
            if(left_boundary_valid[i])
                center[i]=left_boundary[i]+ROAD_WIDTH/2;
        }
    }
    else
    {
        for(i=IMG_H-1;i>IMG_H-1-max_length;i--)
        {
            if(right_boundary_valid[i])
                center[i]=right_boundary[i]-ROAD_WIDTH/2;
        }
    }
    
}

void unkown_process(void)
{
    int i;
    for(i=IMG_H-1;i>IMG_H-1-max_length;i--)
    {
        if(center[i]==-1)
            center[i]=(left_boundary[i]+right_boundary[i])/2;
    }
}
/*
 *@brief 两点之间画直线（Bresenham算法），将直线上的点设为BLACK
 *@param img 图像数据
 *@param x1,y1 第一个点（纵坐标较小，即上方的点）
 *@param x2,y2 第二个点（纵坐标较大，即下方的点）
 */

void element_process(uint8_t img[IMG_H][IMG_W])
{
    switch (now_type)
    {
        case 0:
            unkown_process();
            break;
        case 1://缓转弯
            /* code */
            break;
        case 2://急转弯
            sharp_turn_process();
            break;
        case 3:
            break;
            
        case 4://十字路口，补线处理
            cross_process(img);
            break;
        case 5://环岛，根据内部状态和方向补线
            circle_process(img);
            break;
        default:
            break;
    }
}
