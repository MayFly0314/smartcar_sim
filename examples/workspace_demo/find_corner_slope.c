#include "sim_api.h"
#include <string.h>
#include <math.h>
#define BLACK 0
#define WHITE 255
#define MAX_JUMP 5 //爬边的时候跳变最大值
#define PROSPECT 15 //前瞻，用来采样并计算车的偏差
#define MAX_CORNERS 6 //定义拐点结构体数组中每一帧最大长度
#define CORNER_THRESHOLD 1.5f //定义拐点强度的阈值，拐点强度的绝对值大于这个阈值才可以成为候选拐点
#define CORNER_K 3 //定义为计算斜率的时候间隔的行数，用来取点计算拐点强度
#define INVALID_STRENGTH 0.0f
#define NMS_RADIUS 3 //(Non-Maximum Suppression，中文是“非极大值抑制”)避免一个转弯中出现多个拐点，在一块区域中选取拐点强度最大的，这是拐点区域大小

typedef enum {      
    //定义拐点类型的enum，四种类型对应正方形的四个角，
    //如1对应右边边界向右边拐形成的拐点
    CORNER_NONE=0,
    CORNER_R_OUT=1,
    CORNER_L_OUT=2,
    CORNER_R_IN=3,
    CORNER_L_IN=4,
}corner_type_t;//拐点类型enum的名称
typedef struct{
    //定义拐点结构体，包含拐点的横纵坐标和拐点的类型
    int x;
    int y;
    corner_type_t type;
}corner_t; 

static int center[IMG_H]; //静态全局变量，全局可以拿到中线的数据
static int left_boundary[IMG_H];
static int right_boundary[IMG_H];
static int lost_rows=0;
static float error=0.0f;//代表偏差,error>0说明赛道中线偏右，需要右转，error<0说明赛道中线偏左，需要左转
//计算第n行附近的平均中点横坐标
static corner_t corner_list[MAX_CORNERS]={0};//用来存放某一帧上的全部拐点
static float left_strength[IMG_H]={0.0f};
static float right_strength[IMG_H]={0.0f};//存放左右边界的拐点强度（每一点的拐点强度都等于这一点上下附近点拟合直线斜率之差）
int cal_average(int n)
{
    int cnt=0,sum=0;
    for(int i=0;i<3;i++)
    {
        if (center[IMG_H-1-n*PROSPECT-i]>=0)
        {
            cnt++;
            sum+=center[IMG_H-1-n*PROSPECT-i];
        }
    }
    return sum/cnt;
}
//3x3滤波，属于二值化的一部分，去除孤立噪点，让图像变的平滑
static void filter_3x3(uint8_t img[IMG_H][IMG_W])
{
    static uint8_t tmp[IMG_H][IMG_W];
    int x,y,cnt,i,j;
    for(y=1;y<IMG_H-1;y++)
    {
        for(x=1;x<IMG_W-1;x++)
        {
            cnt=0;
            for(i=y-1;i<y+2;i++)
            {
                for(j=x-1;j<x+2;j++)
                {
                    if(img[i][j]==BLACK)
                    cnt++;
                }
            }
            if(cnt>=5)tmp[y][x]=BLACK;
            else tmp[y][x]=WHITE;
        }
    }
    for(y=0;y<IMG_H;y++)
    {
        tmp[y][0]=img[y][0];
        tmp[y][IMG_W-1]=img[y][IMG_W-1];
    }
    for(x=0;x<IMG_W;x++)
    {
        tmp[0][x]=img[0][x];
        tmp[IMG_H-1][x]=img[IMG_H-1][x];
    }
    memcpy(img,tmp,sizeof(tmp));
}
/*
 *@brief 基础扫线
 *@param img 二值化图像
 *@return 把左边界，右边界，中线的值存入数组中，并且在图像上显示三条不同颜色的线
 */
void base_line_scan(uint8_t img[IMG_H][IMG_W])
{
    int x,y;
    lost_rows=0;//每一帧丢线行数都重置一遍
    memset(left_boundary,-1,sizeof(left_boundary));
    memset(right_boundary,-1,sizeof(right_boundary));
    memset(center,-1,sizeof(center));
    int prev_left=IMG_W/2;
    int prev_right=IMG_W/2;
    //逐行遍历，查找左右边界
    for(y=IMG_H-1;y>=0;y--)
    {
        //找左边界
        for(x=prev_left;x>=0;x--)
        {
            if(img[y][x]==BLACK&&img[y][x+1]==WHITE)
            {
                left_boundary[y]=x+1;
                break;
            }
            if(x==0&&img[y][x]==WHITE)left_boundary[y]=0;
        }
        if(left_boundary[y]==-1)//如果这一行小窗口没有搜索到，那就从上一行中间开始搜一遍
        {
            for(x=(prev_left+prev_right)/2;x>prev_left;x--)
            {
                if(img[y][x]==BLACK&&img[y][x+1]==WHITE)
                {
                    left_boundary[y]=x+1;
                    break;
                }
            }
        }
        if(left_boundary[y]>=0)prev_left=left_boundary[y]+MAX_JUMP;
        //找右边界
        for(x=prev_right;x<IMG_W;x++)
        {
            if(img[y][x]==BLACK&&img[y][x-1]==WHITE)
            {
                right_boundary[y]=x-1;
                break;
            }
            if(x==IMG_W-1&&img[y][x]==WHITE)right_boundary[y]=x;
        }
        if(right_boundary[y]==-1)//如果这一次小窗口的右边界没有找到，就从中间开始搜索
        {
            for(x=(prev_left+prev_right)/2;x<prev_right;x++)
            {
                if(img[y][x]==BLACK&&img[y][x-1]==WHITE)
                {
                    right_boundary[y]=x-1;
                    break;
                }
            }
        }
        if(right_boundary[y]>=0)prev_right=right_boundary[y]-MAX_JUMP;
    }
    //计算中线的值并画点
    for(y=0;y<IMG_H;y++)
    {
        if(left_boundary[y]!=-1)
        {
            sim_draw_point(left_boundary[y],y,SIM_RED);
        }
        if(right_boundary[y]!=-1)
        {
            sim_draw_point(right_boundary[y],y,SIM_BLUE);
        }
        if(left_boundary[y]!=-1&&right_boundary[y]!=-1)
        {
            center[y]=(left_boundary[y]+right_boundary[y])/2;
            sim_draw_point(center[y],y,SIM_YELLOW);
        }
        else
        {
            lost_rows++;
        }
    }
    //计算偏差
    int c0,c1,c2;//分别代表三个点处的横坐标,c0为底线中电，c1为一倍前瞻点，c2为2倍前瞻点
    c0=cal_average(0);
    c1=cal_average(1);
    c2=cal_average(2);
    error=0.7*((float)(c1-c0))+0.3*((float)(c2-c0));
}

float is_valid_corner(int boundary[],int n)//判断这一点是否为有效的拐点，可能越界或者范围内有丢线都不算
{
    if(n<CORNER_K||n>=IMG_H-CORNER_K)
    {
        return INVALID_STRENGTH;
    }
    for(int i=n-CORNER_K;i<=n+CORNER_K;i++)
    {
        if(boundary[i]==-1)
        {
            return INVALID_STRENGTH;
        }
    }
    return 1.0f;
}
float calculate_up_slope(const int boundary[],int n)//算这一点往上附近拟合直线的斜率
{
    
    return ((float)boundary[n-CORNER_K]-(float)boundary[n])/(float)CORNER_K;
}
float calculate_down_slope(const int boundary[],int n)//算这一点往下附近拟合直线的斜率
{   
    return ((float)boundary[n]-(float)boundary[n+CORNER_K])/(float)CORNER_K;
}
void calculate_strength(void)//计算左右边界每个点的拐点强度
{
    int i;
    for(i=0;i<IMG_H;i++)
    {
        if(!is_valid_corner(left_boundary,i))continue;
        left_strength[i]=calculate_up_slope(left_boundary,i)-calculate_down_slope(left_boundary,i);
    }
    for(i=0;i<IMG_H;i++)
    {
        if(!is_valid_corner(right_boundary,i))continue;
        right_strength[i]=calculate_up_slope(right_boundary,i)-calculate_down_slope(right_boundary,i);        
    }

}
//找到拐点，存进拐点结构体数组，并在图上显示出来
static void find_corner(void)
{
    //这里说的拐点，是边界上这个点之后，边界数组开始发生跳变的点，即下一行开始会跳变，是“沿前点”
    int i=0,j;
    int cnt=0;
    float max;
    memset(left_strength,0,sizeof(left_strength));
    memset(right_strength,0,sizeof(right_strength));
    
    memset(corner_list,0,sizeof(corner_list));
    calculate_strength();
    while(i<IMG_H)//遍历左边的边界数组，寻找左拐点
    {
        if(fabsf(left_strength[i])>CORNER_THRESHOLD)
        {
            max=fabsf(left_strength[i]); 
            for(j=i;j<i+NMS_RADIUS;j++)
            {
                  
                if(fabsf(left_strength[j])>=max&&cnt<MAX_CORNERS)
                {
                    corner_list[cnt].x=left_boundary[j];
                    corner_list[cnt].y=j;
                    if(left_strength[j]>0) corner_list[cnt].type=CORNER_L_IN;
                    else corner_list[cnt].type=CORNER_L_OUT;
                    max=fabsf(left_strength[j]);
                }
            }
            cnt++;
            if(cnt==MAX_CORNERS)return;
            i+=NMS_RADIUS;//直接跳过这一片区域，接着寻找拐点
        }
        else
        {
            i++;//不符合拐点要求，往下一行寻找
        }
    }
    i=0;
    while(i<IMG_H)
    {
        if(fabsf(right_strength[i])>CORNER_THRESHOLD)
        {
            max=fabsf(right_strength[i]);
            for(j=i;j<i+NMS_RADIUS;j++)
            {                
                if(fabsf(right_strength[j])>=max&&cnt<MAX_CORNERS)
                {
                    corner_list[cnt].x=right_boundary[j];
                    corner_list[cnt].y=j;
                    if(right_strength[j]>0)corner_list[cnt].type=CORNER_R_OUT;
                    else corner_list[cnt].type=CORNER_R_IN;
                    max=fabsf(right_strength[j]);
                }
            }
            cnt++;
            if(cnt==MAX_CORNERS)return;
            i+=NMS_RADIUS;
        }
        else
        {
            i++;
        }
    
    }

    //打印拐点
    for(i=0;i<cnt;i++)
    {
        sim_draw_cross(corner_list[i].x,corner_list[i].y,3,SIM_ORANGE);
    }

}
//主函数，唯一对外接口，进行图像处理
void image_process(uint8_t img[IMG_H][IMG_W])
{
    filter_3x3(img);
    
    base_line_scan(img);
    find_corner();
    //打印偏差
    sim_draw_text(0,0,SIM_ORANGE,"error=%.2f",error);
    sim_draw_text(0,2,SIM_ORANGE,"lost_rows=%d",lost_rows);

}

