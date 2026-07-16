#include "sim_api.h"
#include <string.h>
#define BLACK 0
#define WHITE 255

#define PROSPECT 15 //前瞻，用来采样并计算车的偏差
static int max_white_x =0;//最长白列横坐标
static int max_length;//最长白列的长度
static int left_boundary[IMG_H];
static int right_boundary[IMG_W];

static int center[IMG_H]; //静态全局变量，全局可以拿到中线的数据

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
//得到最长白列的横坐标和长度，分别存入全局变量max_white_x和max_length中
static void find_longest_whiteline(void)
{
    int i,length,j;
    max_white_x=0;
    max_length=0;
    for(i=0;i<IMG_W;i+=5)
    {
        length=0;
        for(j=IMG_H-1;j>=0;j--)
        {
            if(img[j][i]==BLACK) break;
            length++;
        }
        if(length>max_length)
        {
            max_length=length;
            max_white_x=i;
        }
    }
}
void scan_lines(void)
{
    int x,y;
    //左边界查找
    for(y=IMG_H-1;y>=0;y--)
    {
        for(x=max_white_x;x>=0;x--)
        {
            if()
        }
    }
    
}
void image_process(uint8_t img[IMG_H][IMG_W])
{
    filter_3x3();

}
