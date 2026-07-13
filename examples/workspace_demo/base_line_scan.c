#include "sim_api.h"
#include <string.h>
#define BLACK 0
#define WHITE 255
#define MAX_JUMP 8 //爬边的时候跳变最大值
#define PROSPECT 15 //前瞻，用来采样并计算车的偏差
static int center[IMG_H]; //静态全局变量，全局可以拿到中线的数据
static int lost_rows=0;
static float error=0.0f;//代表偏差,error>0说明赛道中线偏右，需要右转，error<0说明赛道中线偏左，需要左转
//计算第n行附近的平均中点横坐标
int cal_average(int n)
{
    int cnt=0,sum=0;
    for(int i=0;i<3;i++)
    {
        if (center[IMG_H-1-n*PROSPECT-i]>=0)cnt++;
        sum+=center[IMG_H-1-n*PROSPECT-i];
    }
    return sum/cnt;
}
static void filter_3x3(uint8_t img[IMG_H][IMG_W])
{
    //3x3滤波，属于二值化的一部分，去除孤立噪点，让图像变的平滑
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

//爬边找边界和中线
void image_process(uint8_t img[IMG_H][IMG_W])
{
    filter_3x3(img);
    lost_rows=0;//每一帧丢线行数都重置一遍
    int x,y;
    int left_baundary[IMG_H];//左边界数组
    int right_baundary[IMG_H];//右边界数组
    

    memset(left_baundary,-1,sizeof(left_baundary));
    memset(right_baundary,-1,sizeof(right_baundary));
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
                left_baundary[y]=x+1;
                break;
            }
            if(x==0&&img[y][x]==WHITE)left_baundary[y]=0;
        }
        if(left_baundary[y]>=0)prev_left=left_baundary[y]+MAX_JUMP;
        //找右边界
        for(x=prev_right;x<IMG_W;x++)
        {
            if(img[y][x]==BLACK&&img[y][x-1]==WHITE)
            {
                right_baundary[y]=x-1;
                break;

            }
            if(x==IMG_W-1&&img[y][x]==WHITE)right_baundary[y]=x;

        }
        if(right_baundary[y]>=0)prev_right=right_baundary[y]-MAX_JUMP;

    }
    //计算中线的值并画点
    for(y=0;y<IMG_H;y++)
    {

        if(left_baundary[y]!=-1)
        {
            sim_draw_point(left_baundary[y],y,SIM_RED);
        }
        if(right_baundary[y]!=-1)
        {
            sim_draw_point(right_baundary[y],y,SIM_BLUE);
        }
        if(left_baundary[y]!=-1&&right_baundary[y]!=-1)
        {
            center[y]=(left_baundary[y]+right_baundary[y])/2;
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
    //打印偏差
    sim_draw_text(0,0,SIM_ORANGE,"error=%.2f",error);
    sim_draw_text(0,2,SIM_ORANGE,"lost_rows=%d",lost_rows);
   
}
