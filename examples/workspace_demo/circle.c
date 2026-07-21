#include "circle.h"
#include "basic_process.h"
#include "identify.h"
#include <stdlib.h>

#define CIRCLE_CONTINUITY_JUMP 5          //相邻有效边界发生不连续时的最小横向像素差
#define CIRCLE_MONOTONICITY_RADIUS 5      //单调性检测点上下两侧各自参与比较的行数
#define CIRCLE_LOST_RATIO_NUMERATOR 9     //边界严重丢失比例的分子，对应最长白列的90%
#define CIRCLE_LOST_RATIO_DENOMINATOR 10  //边界严重丢失比例的分母，对应最长白列的90%
#define CIRCLE_MIN_WHITE_LENGTH 60         //允许进入环岛入口判断的最小最长白列长度
#define CIRCLE_SIDE_LOST_ROWS 10           //环岛入口中内侧与外侧边界丢线数量的分界值
#define CIRCLE_BOTH_LOST_ROWS 10           //环岛入口允许双边同时丢线的最大行数上限
#define CIRCLE_CORNER_MIN_ROW 26           //环岛入口下拐点允许出现的最小行号
#define CIRCLE_CONTACT_RADIUS 3             //接触点检测中心点上下各检查的行数，窗口总长为7
#define CIRCLE_ENTRY_UP_ROW_LIMIT 10        //由下拐点阶段进入上拐点阶段时，上拐点行号必须严格小于该值
#define CIRCLE_BOTTOM_RUN_MIN_WIDTH 3       //环中底行白色连通段参与判断的最小宽度
#define CIRCLE_EXIT_SLOPE_MAX_LENGTH 60   //出环空窗期允许的原始最长白列长度上限，不包含该值

circle_context_t circle_context = {
    CIRCLE_IDLE,
    CIRCLE_DIR_NONE,
    0,
    0,
    0,
    0,
    0,
    0,
    0
};
static int right_contactpoint_y=0;

/*
 *@brief 将搜索起止行限制在有效范围内，并统一为从下向上搜索
 *@param start 搜索起始行地址，处理后为较大的行号
 *@param end 搜索结束行地址，处理后为较小的行号
 *@param min_row 允许访问的最小行号
 *@param max_row 允许访问的最大行号
 *@return 无
 */
static void normalize_search_range(int *start,int *end,int min_row,int max_row)
{
    int temp;

    if(*start<min_row)*start=min_row;
    if(*start>max_row)*start=max_row;
    if(*end<min_row)*end=min_row;
    if(*end>max_row)*end=max_row;
    if(*start<*end)
    {
        temp=*start;
        *start=*end;
        *end=temp;
    }
}

/*
 *@brief 从下往上查找左边界与直线赛道相切的候选点
 *@details 中心点及上下各3行必须有效，且中心点横坐标不小于窗口内其他边界点
 *@return 接触点行号；0表示未找到
 */
int find_left_contactpoint(void)
{
    int i,offset;
    int start;
    int end;

    if(max_length<2*CIRCLE_CONTACT_RADIUS+1)
        return 0;

    start=IMG_H-1-CIRCLE_CONTACT_RADIUS;
    end=IMG_H-max_length+CIRCLE_CONTACT_RADIUS;
    if(end<CIRCLE_CONTACT_RADIUS)
        end=CIRCLE_CONTACT_RADIUS;
    if(start>end)
    {
        for(i=start;i>=end;i--)
        {
            int all_valid=left_boundary_valid[i];
            int is_local_max=1;

            for(offset=-CIRCLE_CONTACT_RADIUS;
                offset<=CIRCLE_CONTACT_RADIUS;
                offset++)
            {
                if(offset==0)continue;
                if(!left_boundary_valid[i+offset])
                {
                    all_valid=0;
                    break;
                }
                if(left_boundary[i]<left_boundary[i+offset])
                    is_local_max=0;
            }
            if(all_valid&&is_local_max)
                return i;
        }
    }
    return 0;
}

/*
 *@brief 从下往上查找右边界的局部极小值点
 *@details 中心点及上下各3行必须有效，且中心点横坐标不大于窗口内其他边界点
 *@return 极小值点行号；0表示未找到
 */
int find_right_contactpoint(void)
{
    int i,offset;
    int start;
    int end;

    if(max_length<2*CIRCLE_CONTACT_RADIUS+1)
        return 0;

    start=IMG_H-1-CIRCLE_CONTACT_RADIUS;
    end=IMG_H-max_length+CIRCLE_CONTACT_RADIUS;
    if(end<CIRCLE_CONTACT_RADIUS)
        end=CIRCLE_CONTACT_RADIUS;
    if(start>end)
    {
        for(i=start;i>=end;i--)
        {
            int all_valid=right_boundary_valid[i];
            int is_local_min=1;

            for(offset=-CIRCLE_CONTACT_RADIUS;
                offset<=CIRCLE_CONTACT_RADIUS;
                offset++)
            {
                if(offset==0)continue;
                if(!right_boundary_valid[i+offset])
                {
                    all_valid=0;
                    break;
                }
                if(right_boundary[i]>right_boundary[i+offset])
                    is_local_min=0;
            }
            if(all_valid&&is_local_min)
                return i;
        }
    }
    return 0;
}

/*
 *@brief 在左侧拐点和接触点之间重构左边界，并更新对应中线
 *@param img 当前帧二值图像
 *@param corner_x 左侧拐点横坐标
 *@param corner_y 左侧拐点行号
 *@param contact_x 接触点横坐标
 *@param contact_y 接触点行号
 *@return 无
 */
static void rebuild_left_boundary(uint8_t img[IMG_H][IMG_W],
                                  int corner_x,int corner_y,
                                  int contact_x,int contact_y)
{
    int start_y;
    int end_y;
    int row;

    if(corner_y<0||corner_y>=IMG_H||contact_y<0||contact_y>=IMG_H)
        return;

    linktwo(img,corner_x,corner_y,contact_x,contact_y);

    start_y=(corner_y<contact_y)?corner_y:contact_y;
    end_y=(corner_y>contact_y)?corner_y:contact_y;
    for(row=start_y;row<=end_y;row++)
    {
        if(contact_y==corner_y)
            left_boundary[row]=corner_x;
        else
            left_boundary[row]=corner_x+
                (int)((long)(contact_x-corner_x)*(row-corner_y)/
                      (contact_y-corner_y));
        center[row]=(left_boundary[row]+right_boundary[row])/2;
    }
}

/*
 *@brief 从下向上查找左边界第一处连续性变化
 *@param start 搜索起始行，允许传入越界值或较小的行号
 *@param end 搜索结束行，允许传入越界值或较大的行号
 *@return 0表示搜索范围内连续；非0表示首个不连续行，无有效判断条件时返回1
 */
int Continuity_Change_Left(int start,int end)
{
    int i;
    int checked_pair=0;
    int roi_top;
    int min_row;

    if(max_length<=5)
        return 1;
    if(left_lost_rows*CIRCLE_LOST_RATIO_DENOMINATOR>=
       max_length*CIRCLE_LOST_RATIO_NUMERATOR)
        return 1;

    roi_top=IMG_H-max_length;
    if(roi_top<0)roi_top=0;
    min_row=roi_top+1;
    if(min_row>IMG_H-1)
        return 1;
    normalize_search_range(&start,&end,min_row,IMG_H-1);

    for(i=start;i>=end;i--)
    {
        if(!left_boundary_valid[i]||!left_boundary_valid[i-1])
            continue;
        checked_pair=1;
        if(abs(left_boundary[i]-left_boundary[i-1])>=CIRCLE_CONTINUITY_JUMP)
            return i;
    }
    return checked_pair?0:1;
}

/*
 *@brief 从下向上查找左边界由单调变化形成的第一个局部最大值
 *@param start 搜索起始行，允许传入越界值或较小的行号
 *@param end 搜索结束行，允许传入越界值或较大的行号
 *@return 0表示未找到局部最大值；非0表示转折点行号，无有效判断条件时返回1
 */
int Monotonicity_Change_Left(int start,int end)
{
    int i,offset;
    int checked_window=0;
    int roi_top;
    int min_row;
    int max_row=IMG_H-1-CIRCLE_MONOTONICITY_RADIUS;

    if(max_length<2*CIRCLE_MONOTONICITY_RADIUS+1)
        return 1;
    if(left_lost_rows*CIRCLE_LOST_RATIO_DENOMINATOR>=
       max_length*CIRCLE_LOST_RATIO_NUMERATOR)
        return 1;

    roi_top=IMG_H-max_length;
    if(roi_top<0)roi_top=0;
    min_row=roi_top+CIRCLE_MONOTONICITY_RADIUS;
    if(min_row<CIRCLE_MONOTONICITY_RADIUS)
        min_row=CIRCLE_MONOTONICITY_RADIUS;
    if(min_row>max_row)
        return 1;
    normalize_search_range(&start,&end,min_row,max_row);

    for(i=start;i>=end;i--)
    {
        int all_valid=left_boundary_valid[i];
        int all_equal=1;
        int is_local_max=1;

        for(offset=-CIRCLE_MONOTONICITY_RADIUS;
            offset<=CIRCLE_MONOTONICITY_RADIUS;
            offset++)
        {
            if(offset==0)continue;
            if(!left_boundary_valid[i+offset])
            {
                all_valid=0;
                break;
            }
            if(left_boundary[i]!=left_boundary[i+offset])
                all_equal=0;
            if(left_boundary[i]<left_boundary[i+offset])
                is_local_max=0;
        }
        if(!all_valid)
            continue;

        checked_window=1;
        if(all_equal)
            continue;
        if(is_local_max)
            return i;
    }
    return checked_window?0:1;
}

/*
 *@brief 从下向上查找右边界第一处连续性变化
 *@param start 搜索起始行，允许传入越界值或较小的行号
 *@param end 搜索结束行，允许传入越界值或较大的行号
 *@return 0表示搜索范围内连续；非0表示首个不连续行，无有效判断条件时返回1
 */
int Continuity_Change_Right(int start,int end)
{
    int i;
    int checked_pair=0;
    int roi_top;
    int min_row;

    if(max_length<=5)
        return 1;
    if(right_lost_rows*CIRCLE_LOST_RATIO_DENOMINATOR>=
       max_length*CIRCLE_LOST_RATIO_NUMERATOR)
        return 1;

    roi_top=IMG_H-max_length;
    if(roi_top<0)roi_top=0;
    min_row=roi_top+1;
    if(min_row>IMG_H-1)
        return 1;
    normalize_search_range(&start,&end,min_row,IMG_H-1);

    for(i=start;i>=end;i--)
    {
        if(!right_boundary_valid[i]||!right_boundary_valid[i-1])
            continue;
        checked_pair=1;
        if(abs(right_boundary[i]-right_boundary[i-1])>=CIRCLE_CONTINUITY_JUMP)
            return i;
    }
    return checked_pair?0:1;
}

/*
 *@brief 从下向上查找右边界由单调变化形成的第一个局部最小值
 *@param start 搜索起始行，允许传入越界值或较小的行号
 *@param end 搜索结束行，允许传入越界值或较大的行号
 *@return 0表示未找到局部最小值；非0表示转折点行号，无有效判断条件时返回1
 */
int Monotonicity_Change_Right(int start,int end)
{
    int i,offset;
    int checked_window=0;
    int roi_top;
    int min_row;
    int max_row=IMG_H-1-CIRCLE_MONOTONICITY_RADIUS;

    if(max_length<2*CIRCLE_MONOTONICITY_RADIUS+1)
        return 1;
    if(right_lost_rows*CIRCLE_LOST_RATIO_DENOMINATOR>=
       max_length*CIRCLE_LOST_RATIO_NUMERATOR)
        return 1;

    roi_top=IMG_H-max_length;
    if(roi_top<0)roi_top=0;
    min_row=roi_top+CIRCLE_MONOTONICITY_RADIUS;
    if(min_row<CIRCLE_MONOTONICITY_RADIUS)
        min_row=CIRCLE_MONOTONICITY_RADIUS;
    if(min_row>max_row)
        return 1;
    normalize_search_range(&start,&end,min_row,max_row);

    for(i=start;i>=end;i--)
    {
        int all_valid=right_boundary_valid[i];
        int all_equal=1;
        int is_local_min=1;

        for(offset=-CIRCLE_MONOTONICITY_RADIUS;
            offset<=CIRCLE_MONOTONICITY_RADIUS;
            offset++)
        {
            if(offset==0)continue;
            if(!right_boundary_valid[i+offset])
            {
                all_valid=0;
                break;
            }
            if(right_boundary[i]!=right_boundary[i+offset])
                all_equal=0;
            if(right_boundary[i]>right_boundary[i+offset])
                is_local_min=0;
        }
        if(!all_valid)
            continue;

        checked_window=1;
        if(all_equal)
            continue;
        if(is_local_min)
            return i;
    }
    return checked_window?0:1;
}

/*
 *@brief 判断当前边界是否满足左环岛入口的镜像特征
 *@param start 搜索起始行
 *@param end 搜索结束行
 *@return 1表示满足；0表示不满足
 */
static int is_left_circle_entry(int start,int end)
{
    if(left_lost_rows<CIRCLE_SIDE_LOST_ROWS||
       right_lost_rows>CIRCLE_SIDE_LOST_ROWS)
        return 0;
    if(Continuity_Change_Right(start,end)!=0||
       Monotonicity_Change_Right(start,end)!=0||
       Continuity_Change_Left(start,end)==0)
        return 0;
    return 1;
}

/*
 *@brief 判断当前边界是否满足右环岛入口的镜像特征
 *@param start 搜索起始行
 *@param end 搜索结束行
 *@return 1表示满足；0表示不满足
 */
static int is_right_circle_entry(int start,int end)
{
    if(right_lost_rows<CIRCLE_SIDE_LOST_ROWS||
       left_lost_rows>CIRCLE_SIDE_LOST_ROWS)
        return 0;
    if(Continuity_Change_Left(start,end)!=0||
       Monotonicity_Change_Left(start,end)!=0||
       Continuity_Change_Right(start,end)==0)
        return 0;
    return 1;
}

/*
 *@brief 根据原始边界特征识别左右环岛入口
 *@return CIRCLE表示识别到环岛；DONT_KNOW表示条件不满足或方向不明确
 */
road_type identify_circle(void)
{
    int search_start=IMG_H-1;
    int search_end=IMG_H-max_length;
    int left_entry;
    int right_entry;
    corner_t saved_left_down;
    corner_t saved_right_down;

    //公共基础条件不满足时不进入边界形态和拐点判断
    if(max_length<=CIRCLE_MIN_WHITE_LENGTH||
       both_lost_rows>=CIRCLE_BOTH_LOST_ROWS)
        return DONT_KNOW;

    left_entry=is_left_circle_entry(search_start,search_end);
    right_entry=is_right_circle_entry(search_start,search_end);
    if(left_entry==right_entry)
        return DONT_KNOW;

    saved_left_down=corner_list[0];
    saved_right_down=corner_list[2];
    find_corner_down(search_start,search_end);
    if(left_entry&&
       corner_list[0].type==CORNER_L_DOWN&&
       corner_list[0].y>=CIRCLE_CORNER_MIN_ROW)
    {
        circle_context.state=CIRCLE_ENTRY_DOWN;
        circle_context.direction=CIRCLE_DIR_LEFT;
        circle_context.saved_link_dx=0;
        circle_context.saved_link_dy=0;
        circle_context.saved_link_slope_valid=0;
        circle_context.saved_exit_dx=0;
        circle_context.saved_exit_dy=0;
        circle_context.saved_exit_slope_valid=0;
        circle_context.exit_up_seen=0;
        return CIRCLE;
    }
    if(right_entry&&
       corner_list[2].type==CORNER_R_DOWN&&
       corner_list[2].y>=CIRCLE_CORNER_MIN_ROW)
    {
        circle_context.state=CIRCLE_ENTRY_DOWN;
        circle_context.direction=CIRCLE_DIR_RIGHT;
        circle_context.saved_link_dx=0;
        circle_context.saved_link_dy=0;
        circle_context.saved_link_slope_valid=0;
        circle_context.saved_exit_dx=0;
        circle_context.saved_exit_dy=0;
        circle_context.saved_exit_slope_valid=0;
        circle_context.exit_up_seen=0;
        return CIRCLE;
    }

    //识别失败时恢复下拐点，避免影响后续其他赛道类型判断
    corner_list[0]=saved_left_down;
    corner_list[2]=saved_right_down;
    return DONT_KNOW;
}

/*
 *@brief 根据当前帧拐点特征定位环岛阶段并更新状态
 *@details 优先判断当前状态；当前状态条件不满足时，才判断下一状态条件
 *@return 无
 */
void identify_circle_state(void)
{
    int search_start=IMG_H-1;
    int search_end=IMG_H-max_length;

    right_contactpoint_y=0;

    switch(circle_context.state)
    {
        case CIRCLE_ENTRY_DOWN:
            find_corner_down(search_start,search_end);
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                int contact_y=find_left_contactpoint();

                //只有下拐点位于切点下方时，当前下拐点阶段才仍然成立
                if(corner_list[0].type==CORNER_L_DOWN&&
                   contact_y>0&&corner_list[0].y>contact_y)
                    break;

                find_corner_up(search_start,search_end);
                if(corner_list[1].type==CORNER_L_UP&&
                   corner_list[1].y<CIRCLE_ENTRY_UP_ROW_LIMIT)
                    circle_context.state=CIRCLE_ENTRY_UP_EXTEND;
            }
            else if(circle_context.direction==CIRCLE_DIR_RIGHT)
            {
                if(corner_list[2].type==CORNER_R_DOWN)
                    break;

                find_corner_up(search_start,search_end);
                if(corner_list[3].type==CORNER_R_UP&&
                   corner_list[3].y<CIRCLE_ENTRY_UP_ROW_LIMIT)
                    circle_context.state=CIRCLE_ENTRY_UP_EXTEND;
            }
            break;

        case CIRCLE_ENTRY_UP_EXTEND:
            find_corner_up(search_start,search_end);
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[1].type==CORNER_L_UP&&
               corner_list[1].y>=CIRCLE_ENTRY_UP_ROW_LIMIT)
            {
                int contact_y=find_left_contactpoint();

                if(contact_y>0&&corner_list[1].y<contact_y)
                    circle_context.state=CIRCLE_ENTRY_LINK;
            }
            else if(circle_context.direction==CIRCLE_DIR_RIGHT&&
                    corner_list[3].type==CORNER_R_UP&&
                    corner_list[3].y>=CIRCLE_ENTRY_UP_ROW_LIMIT)
            {
                circle_context.state=CIRCLE_ENTRY_LINK;
            }
            break;

        case CIRCLE_ENTRY_LINK:
            find_corner_up(search_start,search_end);
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[1].type==CORNER_L_UP)
            {
                int contact_y=find_left_contactpoint();

                //切点丢失或不再位于上拐点下方时，使用最后一次LINK斜率延长
                if(!(contact_y>0&&corner_list[1].y<contact_y)&&
                   circle_context.saved_link_slope_valid&&
                   circle_context.saved_link_dy>0)
                {
                    circle_context.state=CIRCLE_ENTRY_SLOPE_EXTEND;
                }
            }
            break;

        case CIRCLE_ENTRY_SLOPE_EXTEND:
            //新状态每帧重新定位左上拐点，供保存斜率延长补线使用
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                find_corner_up(search_start,search_end);
                if(corner_list[1].type!=CORNER_L_UP)
                    circle_context.state=CIRCLE_INSIDE;
            }
            break;

        case CIRCLE_INSIDE:
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                right_contactpoint_y=find_right_contactpoint();
                if(right_contactpoint_y>0)
                    circle_context.state=CIRCLE_EXIT_LINK;
            }
            break;

        case CIRCLE_EXIT_LINK:
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                right_contactpoint_y=find_right_contactpoint();
                if(right_contactpoint_y==0)
                {
                    find_corner_up(search_start,search_end);
                    if(corner_list[1].type!=CORNER_L_UP&&
                       max_length<CIRCLE_EXIT_SLOPE_MAX_LENGTH&&
                       circle_context.saved_exit_slope_valid&&
                       circle_context.saved_exit_dx>0&&
                       circle_context.saved_exit_dy>0)
                    {
                        circle_context.state=CIRCLE_EXIT_SLOPE_EXTEND;
                    }
                    else
                    {
                        if(corner_list[1].type==CORNER_L_UP)
                            circle_context.exit_up_seen=1;
                        circle_context.state=CIRCLE_EXIT_EXTEND;
                    }
                }
            }
            break;

        case CIRCLE_EXIT_SLOPE_EXTEND:
            //以下条件使用补线重扫前的原始边界信息，任一失效即进入最后出环阶段
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                right_contactpoint_y=find_right_contactpoint();
                find_corner_up(search_start,search_end);
                if(right_contactpoint_y>0||
                   corner_list[1].type==CORNER_L_UP||
                   max_length>=CIRCLE_EXIT_SLOPE_MAX_LENGTH||
                   !circle_context.saved_exit_slope_valid||
                   circle_context.saved_exit_dx<=0||
                   circle_context.saved_exit_dy<=0)
                {
                    if(corner_list[1].type==CORNER_L_UP)
                        circle_context.exit_up_seen=1;
                    circle_context.state=CIRCLE_EXIT_EXTEND;
                }
            }
            break;

        case CIRCLE_IDLE:
        case CIRCLE_EXIT_COMPLETE:
            break;

        case CIRCLE_EXIT_EXTEND:
            //必须先看到上拐点；之后上拐点消失才确认完整出环
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                find_corner_up(search_start,search_end);
                if(corner_list[1].type==CORNER_L_UP)
                    circle_context.exit_up_seen=1;
                else if(circle_context.exit_up_seen)
                    circle_context.state=CIRCLE_EXIT_COMPLETE;
            }
            break;

        default:
            break;
    }
}

/*
 *@brief 根据当前环岛阶段和方向分派补线处理
 *@param img 当前帧二值图像
 *@return 无
 */
void circle_process(uint8_t img[IMG_H][IMG_W])
{
    switch(circle_context.state)
    {
        case CIRCLE_IDLE:
            break;

        case CIRCLE_ENTRY_DOWN:
            //左环连接左下拐点与圆环和直线跑道的相切点，保持直走
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[0].type==CORNER_L_DOWN)
            {
                int contact_y=find_left_contactpoint();

                if(contact_y>0&&corner_list[0].y>contact_y)
                {
                    rebuild_left_boundary(img,
                                          corner_list[0].x,
                                          corner_list[0].y,
                                          left_boundary[contact_y],
                                          contact_y);
                }
            }
            break;

        case CIRCLE_ENTRY_UP_EXTEND:
            //以左切点同行的右边界斜率作镜像，从左上拐点延长至图像底端
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[1].type==CORNER_L_UP&&
               corner_list[1].y<CIRCLE_ENTRY_UP_ROW_LIMIT)
            {
                int contact_y=find_left_contactpoint();
                int row;
                int right_dx;
                int x_bottom;

                if(contact_y>=3&&contact_y<=IMG_H-4&&
                   corner_list[1].y<contact_y&&
                   right_boundary_valid[contact_y-3]&&
                   right_boundary_valid[contact_y]&&
                   right_boundary_valid[contact_y+3])
                {
                    right_dx=right_boundary[contact_y+3]-
                             right_boundary[contact_y-3];
                    x_bottom=corner_list[1].x-
                             right_dx*(IMG_H-1-corner_list[1].y)/6;

                    linktwo(img,
                            corner_list[1].x,corner_list[1].y,
                            x_bottom,IMG_H-1);
                    for(row=corner_list[1].y;row<IMG_H;row++)
                    {
                        left_boundary[row]=corner_list[1].x-
                            right_dx*(row-corner_list[1].y)/6;
                        center[row]=(left_boundary[row]+right_boundary[row])/2;
                    }
                }
            }
            break;

        case CIRCLE_ENTRY_LINK:
            //左环连接左上拐点与左切点同行的右边界点，并将连线作为右边界
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[1].type==CORNER_L_UP&&
               corner_list[1].y>=CIRCLE_ENTRY_UP_ROW_LIMIT)
            {
                int contact_y=find_left_contactpoint();
                int contact_x;
                int row;

                if(contact_y>0&&corner_list[1].y<contact_y&&
                   right_boundary_valid[contact_y])
                {
                    contact_x=right_boundary[contact_y];
                    circle_context.saved_link_dx=contact_x-corner_list[1].x;
                    circle_context.saved_link_dy=contact_y-corner_list[1].y;
                    circle_context.saved_link_slope_valid=1;
                    linktwo(img,
                            corner_list[1].x,corner_list[1].y,
                            contact_x,contact_y);
                    for(row=corner_list[1].y;row<=contact_y;row++)
                    {
                        right_boundary[row]=corner_list[1].x+
                            (contact_x-corner_list[1].x)*
                            (row-corner_list[1].y)/
                            (contact_y-corner_list[1].y);
                        center[row]=(left_boundary[row]+right_boundary[row])/2;
                    }
                }
            }
            break;

        case CIRCLE_ENTRY_SLOPE_EXTEND:
            //沿第三状态最后一次有效补线的斜率延长，再在左侧区域重新扫线
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[1].type==CORNER_L_UP&&
               circle_context.saved_link_slope_valid&&
               circle_context.saved_link_dy>0)
            {
                int up_x=corner_list[1].x;
                int up_y=corner_list[1].y;
                int x_bottom=up_x+
                    (int)((long)circle_context.saved_link_dx*
                          (IMG_H-1-up_y)/circle_context.saved_link_dy);

                linktwo(img,up_x,up_y,x_bottom,IMG_H-1);
                find_longest_whiteline_range(img,0,up_x);
                scan_lines(img);
            }
            break;

        case CIRCLE_INSIDE:
            //底行出现多个有效白色连通段时，选择最左侧区域重新扫线
            if(circle_context.direction==CIRCLE_DIR_LEFT)
            {
                int x;
                int is_white;
                int run_start=-1;
                int run_end;
                int left_run_start=-1;
                int left_run_end=-1;
                int valid_run_count=0;

                for(x=0;x<=IMG_W;x++)
                {
                    is_white=(x<IMG_W&&img[IMG_H-1][x]==WHITE);
                    if(is_white&&run_start<0)
                    {
                        run_start=x;
                    }
                    else if(!is_white&&run_start>=0)
                    {
                        run_end=x-1;
                        if(run_end-run_start+1>=CIRCLE_BOTTOM_RUN_MIN_WIDTH)
                        {
                            valid_run_count++;
                            if(valid_run_count==1)
                            {
                                left_run_start=run_start;
                                left_run_end=run_end;
                            }
                        }
                        run_start=-1;
                    }
                }

                if(valid_run_count>=2)
                {
                    find_longest_whiteline_range(img,
                                                 left_run_start,
                                                 left_run_end);
                    scan_lines(img);
                }
            }
            break;

        case CIRCLE_EXIT_LINK:
            //连接右边界极小值点与可见范围内最上方的左边界无效点
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               right_contactpoint_y>0)
            {
                int row;
                int roi_top=IMG_H-max_length;
                int left_invalid_y=-1;
                int right_point_x=right_boundary[right_contactpoint_y];

                if(roi_top<0)roi_top=0;
                for(row=IMG_H-1;row>=roi_top;row--)
                {
                    if(!left_boundary_valid[row])
                        left_invalid_y=row;
                }

                if(left_invalid_y>=0)
                {
                    if(right_contactpoint_y>left_invalid_y&&
                       right_point_x>left_boundary[left_invalid_y])
                    {
                        circle_context.saved_exit_dx=
                            right_point_x-left_boundary[left_invalid_y];
                        circle_context.saved_exit_dy=
                            right_contactpoint_y-left_invalid_y;
                        circle_context.saved_exit_slope_valid=1;
                    }
                    linktwo(img,
                            right_point_x,right_contactpoint_y,
                            left_boundary[left_invalid_y],left_invalid_y);
                    find_longest_whiteline(img);
                    scan_lines(img);
                }
            }
            break;

        case CIRCLE_EXIT_SLOPE_EXTEND:
            //使用EXIT_LINK最后有效斜率，从最底行右边界点向左上延长至屏幕最左边
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               circle_context.saved_exit_slope_valid&&
               circle_context.saved_exit_dx>0&&
               circle_context.saved_exit_dy>0)
            {
                int start_y=IMG_H-1;
                int start_x=right_boundary[IMG_H-1];
                int end_y=start_y-
                    (int)((long)start_x*circle_context.saved_exit_dy/
                          circle_context.saved_exit_dx);

                if(end_y<0)end_y=0;
                if(end_y>start_y)end_y=start_y;
                linktwo(img,start_x,start_y,0,end_y);
                find_longest_whiteline(img);
                scan_lines(img);
            }
            break;

        case CIRCLE_EXIT_EXTEND:
            //找到左上拐点时按十字路口的单上拐点方式延长左边界
            if(circle_context.direction==CIRCLE_DIR_LEFT&&
               corner_list[1].type==CORNER_L_UP)
            {
                int row;
                int center_start=corner_list[1].y-4;

                if(center_start<0)center_start=0;
                left_lengthen(img,corner_list[1].x,corner_list[1].y);
                for(row=center_start;row<IMG_H;row++)
                    center[row]=(left_boundary[row]+right_boundary[row])/2;
            }
            break;

        case CIRCLE_EXIT_COMPLETE:
            circle_context.state=CIRCLE_IDLE;
            circle_context.direction=CIRCLE_DIR_NONE;
            circle_context.saved_link_dx=0;
            circle_context.saved_link_dy=0;
            circle_context.saved_link_slope_valid=0;
            circle_context.saved_exit_dx=0;
            circle_context.saved_exit_dy=0;
            circle_context.saved_exit_slope_valid=0;
            circle_context.exit_up_seen=0;
            break;

        default:
            circle_context.state=CIRCLE_IDLE;
            circle_context.direction=CIRCLE_DIR_NONE;
            circle_context.saved_link_dx=0;
            circle_context.saved_link_dy=0;
            circle_context.saved_link_slope_valid=0;
            circle_context.saved_exit_dx=0;
            circle_context.saved_exit_dy=0;
            circle_context.saved_exit_slope_valid=0;
            circle_context.exit_up_seen=0;
            break;
    }
}
