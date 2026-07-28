#ifndef __CIRCLE_H_
#define __CIRCLE_H_

#include "basic_process.h"

typedef enum {
    CIRCLE_IDLE=0,
    CIRCLE_ENTRY_DOWN,       //入环：使用入环侧下拐点补线，保持直走
    CIRCLE_ENTRY_UP_EXTEND,  //入环：按另一侧边界的镜像斜率将上拐点延长至底端
    CIRCLE_ENTRY_LINK,       //入环：连接左上拐点与左切点同行的右边界点并重构右边界
    CIRCLE_ENTRY_SLOPE_EXTEND,//入环：LINK位置关系失效后使用保留斜率延长补线
    CIRCLE_INSIDE,           //环中：底行分裂时在最左侧白色区域重新扫线
    CIRCLE_EXIT_LINK,        //出环：连接右边界极小值点与左边界最上方无效点
    CIRCLE_EXIT_SLOPE_EXTEND,//出环：极小值和左上拐点空窗期使用保留斜率补线
    CIRCLE_EXIT_EXTEND,      //出环：延长对应侧上拐点，恢复直走
    CIRCLE_EXIT_COMPLETE     //完整出环
} circle_state_t;

typedef enum {
    CIRCLE_DIR_NONE=0,
    CIRCLE_DIR_LEFT,
    CIRCLE_DIR_RIGHT
} circle_direction_t;

typedef struct {
    circle_state_t state;
    circle_direction_t direction;
    int saved_link_dx;//第三状态最后一次有效补线的横向变化量
    int saved_link_dy;//第三状态最后一次有效补线的纵向变化量
    int saved_link_slope_valid;//保存的第三状态补线斜率是否有效
    int saved_exit_dx;//EXIT_LINK最后一次有效补线的横向变化量
    int saved_exit_dy;//EXIT_LINK最后一次有效补线的纵向变化量
    int saved_exit_slope_valid;//保存的EXIT_LINK补线斜率是否有效
    int exit_up_seen;//最后出环阶段是否至少识别到过一次对应侧上拐点
} circle_context_t;

extern circle_context_t circle_context;// 环岛状态机上下文

/*
 *@brief 从下往上查找左边界与直线赛道相切的候选点
 *@return 接触点行号；0表示未找到
 */
int find_left_contactpoint(void);

/*
 *@brief 从下往上查找右边界7行窗口内的局部极小值点
 *@return 极小值点行号；0表示未找到
 */
int find_right_contactpoint(void);

/*
 *@brief 从下往上查找左边界第一处连续性变化
 *@param start 搜索起始行
 *@param end 搜索结束行
 *@return 0表示连续；非0表示不连续行或当前数据无判断意义
 */
int Continuity_Change_Left(int start,int end);
/*
 *@brief 从下往上查找左边界第一处局部最大值
 *@param start 搜索起始行
 *@param end 搜索结束行
 *@return 0表示未找到；非0表示转折点行或当前数据无判断意义
 */
int Monotonicity_Change_Left(int start,int end);
/*
 *@brief 从下往上查找右边界第一处连续性变化
 *@param start 搜索起始行
 *@param end 搜索结束行
 *@return 0表示连续；非0表示不连续行或当前数据无判断意义
 */
int Continuity_Change_Right(int start,int end);
/*
 *@brief 从下往上查找右边界第一处局部最小值
 *@param start 搜索起始行
 *@param end 搜索结束行
 *@return 0表示未找到；非0表示转折点行或当前数据无判断意义
 */
int Monotonicity_Change_Right(int start,int end);
/*
 *@brief 根据当前帧拐点特征定位环岛阶段并更新状态
 *@return 无
 */
void identify_circle_state(void);
/*
 *@brief 根据当前环岛阶段和方向执行补线处理
 *@param img 当前帧二值图像
 *@return 无
 */
void circle_process(uint8_t img[IMG_H][IMG_W]);

#endif
