#include "sim_api.h"
#include "basic_process.h"
#include <stdlib.h>
#include <string.h>

int max_white_x =0;//最长白列横坐标
int max_length;//最长白列的长度
int left_boundary[IMG_H];
int right_boundary[IMG_H];
int center[IMG_H]; //静态全局变量，全局可以拿到中线的数据
corner_t corner_list[MAX_CORNERS];
int left_lost_rows=0;
int right_lost_rows=0;
int center_var=0;//中线方差，衡量中线离散程度
void filter_3x3(uint8_t img[IMG_H][IMG_W])
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
//得到最长白列的横坐标和长度，
//分别存入全局变量max_white_x和max_length中
void find_longest_whiteline(uint8_t img[IMG_H][IMG_W])
{
    int i,length,j;
    int max_length_left=0;
    int max_length_right=0;
    int x_left=0;
    int x_right=0;
    max_white_x=0;
    max_length=0;
    for(i=0;i<IMG_W;i+=5)//从左往右找一遍
    {
        length=0;
        for(j=IMG_H-1;j>=0;j--)
        {
            if(img[j][i]==BLACK) break;
            length++;
        }
        if(length>max_length_left)
        {
            max_length_left=length;
            x_left=i;
        }
    }
    for(i=IMG_W-1;i>0;i-=5)//从右往左找一遍
    {
        length=0;
        for(j=IMG_H-1;j>=0;j--)
        {
            if(img[j][i]==BLACK) break;
            length++;
        }
        if(length>max_length_right)
        {
            max_length_right=length;
            x_right=i;
        }
    }
    if(max_length_left==max_length_right)
    {
        max_length=max_length_right;
        max_white_x=(x_left+x_right)/2;
    }
    else if(max_length_right>max_length_left)
    {
        max_length=max_length_right;
        max_white_x=x_right;
    }
    else 
    {
        max_length=max_length_left;
        max_white_x=x_left;
    }
    
}
/*扫线，边界查找，分别找到左边界数组，右边界数组以及初步中线数组
 *并把数据存进全局变量中
 *@return left_boundary[] right_boundary[] center[] left_lost_rows right_left_rows
 */
void scan_lines(uint8_t img[IMG_H][IMG_W])
{
    int x,y;
    //初始化左边界数组，右边界数组，左右丢线数
    memset(left_boundary,-1,sizeof(left_boundary));
    memset(right_boundary,-1,sizeof(right_boundary));
    memset(center,-1,sizeof(center));
    left_lost_rows=0;
    right_lost_rows=0;
    //左边界查找
    for(y=IMG_H-1;y>=0;y--)
    {
        for(x=max_white_x;x>0;x--)
        {
            if(img[y][x]==WHITE&&img[y][x-1]==BLACK)
            {
                left_boundary[y]=x;
                break;
            }
        }
    }
    for(y=IMG_H-1;y>=0;y--)
    {
        for(x=max_white_x;x<IMG_W-1;x++)
        {
            if(img[y][x]==WHITE&&img[y][x+1]==BLACK)
            {
                right_boundary[y]=x;
                break;
            }
        }
    }
    for(y=IMG_H-1;y>=IMG_H-max_length;y--)
    {
        if(left_boundary[y]<0)left_lost_rows++;
        if(right_boundary[y]<0)right_lost_rows++;
        if(left_boundary[y]>0&&right_boundary[y]>0)center[y]=(left_boundary[y]+right_boundary[y])/2;
    }
    //计算中线方差
    {
        int sum=0,cnt=0,mean=0;
        for(y=IMG_H-1;y>=IMG_H-max_length;y--)
        {
            if(center[y]>=0){sum+=center[y];cnt++;}
        }
        if(cnt>0)
        {
            mean=sum/cnt;
            center_var=0;
            for(y=IMG_H-1;y>=IMG_H-max_length;y--)
            {
                if(center[y]>=0)
                    center_var+=(center[y]-mean)*(center[y]-mean);
            }
        }
        else center_var=0;
    }
}
/*
 *@brief 在指定行范围内查找下拐点（左下、右下）
 *@param start_line 起始行（从大往小搜）
 *@param end_line 结束行（搜索到这一行停止）
 *@return 拐点存入全局 corner_list[0]~corner_list[3] 固定位置
 */
void find_corner_down(int start_line,int end_line)
{
    int y;
    int safe_start=(start_line>IMG_H-4)?IMG_H-4:start_line;//防止y+3越界
    for(y=safe_start;y>end_line&&y>IMG_H-max_length+3;y--)//从下往上找，不超过赛道区域
    {
        if( //判断左下拐点，未找到才添加
            corner_list[0].type==CORNER_NONE&&
            abs(left_boundary[y]-left_boundary[y+1])<3&& // 拐点下方附近差值较小
            abs(left_boundary[y]-left_boundary[y+2])<5&&
            abs(left_boundary[y]-left_boundary[y+3])<7&&
            abs(left_boundary[y]-left_boundary[y-1])>3&&  //拐点上方附近差值较大
            abs(left_boundary[y]-left_boundary[y-2])>8&&
            abs(left_boundary[y]-left_boundary[y-3])>10&&
            left_boundary[y]>0&&                           //平滑测不能有丢线
            left_boundary[y+1]>0&&
            left_boundary[y+2]>0&&
            left_boundary[y+3]>0&&
            left_boundary[y]>EDGE_WARNING                  //不考虑屏幕边界附近的拐点
            )
        {
                corner_list[0].x=left_boundary[y];
                corner_list[0].y=y;
                corner_list[0].type=CORNER_L_DOWN;
            
        }
        if( //判断右下拐点，未找到才添加
            corner_list[2].type==CORNER_NONE&&
            abs(right_boundary[y]-right_boundary[y+1])<3&&
            abs(right_boundary[y]-right_boundary[y+2])<5&&
            abs(right_boundary[y]-right_boundary[y+3])<7&&
            abs(right_boundary[y]-right_boundary[y-1])>3&&
            abs(right_boundary[y]-right_boundary[y-2])>8&&
            abs(right_boundary[y]-right_boundary[y-3])>10&&
            right_boundary[y]>0&&
            right_boundary[y+1]>0&&
            right_boundary[y+2]>0&&
            right_boundary[y+3]>0&&
            
            right_boundary[y]<IMG_W-1-EDGE_WARNING         //不考虑屏幕边界的拐点
        )
        {
                corner_list[2].x=right_boundary[y];
                corner_list[2].y=y;
                corner_list[2].type=CORNER_R_DOWN;
            
        }
    }
}
/*
 *@brief 在指定行范围内查找上拐点（左上、右上）
 *@param start_line 起始行（从大往小搜）
 *@param end_line 结束行（搜索到这一行停止）
 *@return 拐点存入全局 corner_list[0]~corner_list[3] 固定位置
 */
void find_corner_up(int start_line,int end_line)
{
    int y;
    int safe_start=(start_line>IMG_H-4)?IMG_H-4:start_line;//防止y+3越界
    for(y=safe_start;y>end_line&&y>IMG_H-max_length+3;y--)//从下往上找，不超过赛道区域
    {
        if( //判断左上拐点，未找到才添加
            corner_list[1].type==CORNER_NONE&&
            abs(left_boundary[y]-left_boundary[y-1])<3&& // 拐点上方附近差值较小
            abs(left_boundary[y]-left_boundary[y-2])<5&&
            abs(left_boundary[y]-left_boundary[y-3])<7&&
            abs(left_boundary[y]-left_boundary[y+1])>3&&  //拐点下方附近差值较大
            abs(left_boundary[y]-left_boundary[y+2])>8&&
            abs(left_boundary[y]-left_boundary[y+3])>10&&
            left_boundary[y]>0&&                           //平滑测不能有丢线
            left_boundary[y-1]>0&&
            left_boundary[y-2]>0&&
            left_boundary[y-3]>0&&
            left_boundary[y]>EDGE_WARNING
            )
        {
                corner_list[1].x=left_boundary[y];
                corner_list[1].y=y;
                corner_list[1].type=CORNER_L_UP;
        }
        if( //判断右上拐点，未找到才添加
            corner_list[3].type==CORNER_NONE&&
            abs(right_boundary[y]-right_boundary[y-1])<3&&
            abs(right_boundary[y]-right_boundary[y-2])<5&&
            abs(right_boundary[y]-right_boundary[y-3])<7&&
            abs(right_boundary[y]-right_boundary[y+1])>3&&
            abs(right_boundary[y]-right_boundary[y+2])>8&&
            abs(right_boundary[y]-right_boundary[y+3])>10&&
            right_boundary[y]>0&&
            right_boundary[y-1]>0&&
            right_boundary[y-2]>0&&
            right_boundary[y-3]>0&&
            right_boundary[y]<IMG_W-1-EDGE_WARNING
        )
        {
                corner_list[3].x=right_boundary[y];
                corner_list[3].y=y;
                corner_list[3].type=CORNER_R_UP;
        }
    }
}
//打印左右边界和中线 和拐点

