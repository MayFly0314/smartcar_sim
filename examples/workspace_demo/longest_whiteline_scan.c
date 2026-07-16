#include "sim_api.h"
#include <stdlib.h>
#include <string.h>

#define BLACK 0

#define WHITE 255
#define MAX_CORNERS 5
static int max_white_x =0;//最长白列横坐标

static int max_length;//最长白列的长度

static int left_boundary[IMG_H];

static int right_boundary[IMG_H];

static int center[IMG_H]; //静态全局变量，全局可以拿到中线的数据


typedef enum {      
    //定义拐点类型的enum，四种类型对应有右边向外的拐点，右边向内的拐点...查看的方向是从下往上
    //如1对应右边边界向右边拐形成的拐点
    CORNER_NONE=0,
    CORNER_L_DOWN=1,
    CORNER_L_UP=2,
    CORNER_R_DOWN=3,
    CORNER_R_UP=4,
}corner_type_t;//拐点类型enum的名称
typedef struct{
    //定义拐点结构体，包含拐点的横纵坐标和拐点的类型
    int x;
    int y;
    corner_type_t type;
}corner_t; 
static corner_t corner_list[MAX_CORNERS];
static int cnt=0;
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

static void find_longest_whiteline(uint8_t img[IMG_H][IMG_W])

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

/*扫线，边界查找，分别找到左边界数组，右边界数组以及初步中线数组

 *并把数据存进全局变量中

 */

void scan_lines(uint8_t img[IMG_H][IMG_W])

{

    int x,y;

    memset(left_boundary,-1,sizeof(left_boundary));

    memset(right_boundary,-1,sizeof(right_boundary));

    memset(center,-1,sizeof(center));

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

        if(left_boundary[y]>=0&&right_boundary[y]>=0)

        {

            center[y]=(left_boundary[y]+right_boundary[y])/2;

        }

    }
}

/*
 *@brief 寻找这一帧图像的拐点
 *@return 把拐点存在拐点结构体数组中
 *
 */

void find_corner_boundary_jump(void)
{
    memset(corner_list,0,sizeof(corner_list));
    int y;
    cnt=0;
    for(y=IMG_H-4;y>IMG_H-max_length+3;y--)//从下往上找
    {
        if( //判断左下拐点
            cnt<MAX_CORNERS&&                           //拐点结构体数组未越界
            
            abs(left_boundary[y]-left_boundary[y+1])<3&& // 拐点下方附近差值较小
            abs(left_boundary[y]-left_boundary[y+2])<5&&
            abs(left_boundary[y]-left_boundary[y+3])<7&&

            abs(left_boundary[y]-left_boundary[y-1])>3&&  //拐点上方附近差值较大
            abs(left_boundary[y]-left_boundary[y-2])>8&&
            abs(left_boundary[y]-left_boundary[y-3])>10&&
        
            left_boundary[y]>0&&                           //平滑测不能有丢线
            left_boundary[y+1]>0&&
            left_boundary[y+2]>0&&
            left_boundary[y+3]>0
            )
        {
            corner_list[cnt].x=left_boundary[y];
            corner_list[cnt].y=y;
            corner_list[cnt].type=CORNER_L_DOWN;
            cnt++;
        }


        if( //判断的是左上拐点
            cnt<MAX_CORNERS&&                           //拐点结构体数组未越界
            
            abs(left_boundary[y]-left_boundary[y-1])<3&& // 拐点上方附近差值较小
            abs(left_boundary[y]-left_boundary[y-2])<5&&
            abs(left_boundary[y]-left_boundary[y-3])<7&&

            abs(left_boundary[y]-left_boundary[y+1])>3&&  //拐点下方附近差值较大
            abs(left_boundary[y]-left_boundary[y+2])>8&&
            abs(left_boundary[y]-left_boundary[y+3])>10&&
        
            left_boundary[y]>0&&                           //平滑测不能有丢线
            left_boundary[y-1]>0&&
            left_boundary[y-2]>0&&
            left_boundary[y-3]>0
            )
        {
            corner_list[cnt].x=left_boundary[y];
            corner_list[cnt].y=y;
            corner_list[cnt].type=CORNER_L_UP;
            cnt++;
        }


        if(
            cnt<MAX_CORNERS&&
            abs(right_boundary[y]-right_boundary[y+1])<3&&
            abs(right_boundary[y]-right_boundary[y+2])<5&&
            abs(right_boundary[y]-right_boundary[y+3])<7&&

            abs(right_boundary[y]-right_boundary[y-1])>3&&
            abs(right_boundary[y]-right_boundary[y-2])>8&&
            abs(right_boundary[y]-right_boundary[y-3])>10&&

            right_boundary[y]>0&&
            right_boundary[y+1]>0&&
            right_boundary[y+2]>0&&
            right_boundary[y+3]>0  
        )
        {
            corner_list[cnt].x=right_boundary[y];
            corner_list[cnt].y=y;
            corner_list[cnt].type=CORNER_R_DOWN;
            cnt++;
        }

        if(
            cnt<MAX_CORNERS&&
            abs(right_boundary[y]-right_boundary[y-1])<3&&
            abs(right_boundary[y]-right_boundary[y-2])<5&&
            abs(right_boundary[y]-right_boundary[y-3])<7&&

            abs(right_boundary[y]-right_boundary[y+1])>3&&
            abs(right_boundary[y]-right_boundary[y+2])>8&&
            abs(right_boundary[y]-right_boundary[y+3])>10&&

            right_boundary[y]>0&&
            right_boundary[y-1]>0&&
            right_boundary[y-2]>0&&
            right_boundary[y-3]>0  
        )
        {
            corner_list[cnt].x=right_boundary[y];
            corner_list[cnt].y=y;
            corner_list[cnt].type=CORNER_R_UP;
            cnt++;
        }
    }

}

//打印左右边界和中线 和拐点

void image_process(uint8_t img[IMG_H][IMG_W])

{

    int y,i;

    filter_3x3(img);
    find_longest_whiteline(img);
    scan_lines(img);
    find_corner_boundary_jump();
    //下面是打印部分，在图上显示出来
    for(y=IMG_H-1;y>=IMG_H-max_length;y--)

    {

        if(left_boundary[y]>=0)sim_draw_point(left_boundary[y],y,SIM_RED);
        else sim_draw_point(left_boundary[y],y,SIM_PURPLE);

        if(right_boundary[y]>=0)sim_draw_point(right_boundary[y],y,SIM_GREEN);
        else sim_draw_point(right_boundary[y],y,SIM_PURPLE);

        if(center[y]>=0)sim_draw_point(center[y],y,SIM_YELLOW);

    }
    for(i=0;i<cnt;i++)
    {
        sim_draw_cross(corner_list[i].x,corner_list[i].y,3,SIM_ORANGE);
    }
    



}

