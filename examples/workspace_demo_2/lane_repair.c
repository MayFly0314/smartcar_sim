#include "lane_repair.h"
void linktwo(uint8_t img[IMG_H][IMG_W],int x1,int y1,int x2,int y2)
{
    int dx=abs(x2-x1);
    int dy=abs(y2-y1);
    int sx=(x1<x2)?1:-1;
    int sy=(y1<y2)?1:-1;
    int err=dx-dy;
    int e2;
    while(1)
    {
        if(x1>=0&&x1<IMG_W&&y1>=0&&y1<IMG_H)
            img[y1][x1]=BLACK;
        if(x1==x2&&y1==y2)break;
        e2=2*err;
        if(e2>-dy){err-=dy;x1+=sx;}
        if(e2<dx){err+=dx;y1+=sy;}
    }
}
/*
 *@brief 左侧单点向下延伸：以拐点及往上4行处边界点拟合直线，延伸至底部
 *@param img 图像数据
 *@param x,y 左侧拐点坐标
 */
void left_lengthen(uint8_t img[IMG_H][IMG_W],int x,int y)
{
    int up_y=y-4;
    if(up_y<0)up_y=0;
    int up_x=left_boundary[up_y];
    if(!left_boundary_valid[up_y])return;//上边界丢线，无法拟合
    //计算底部延伸点的x坐标
    int dy=y-up_y;
    if(dy<=0)return;//防止除零
    int dx=x-up_x;
    int y_bottom=IMG_H-1;
    int x_bottom=up_x+dx*(y_bottom-up_y)/dy;
    //画线并更新left_boundary
    linktwo(img,up_x,up_y,x_bottom,y_bottom);
    for(int row=up_y;row<=y_bottom;row++)
    {
        left_boundary[row]=up_x+dx*(row-up_y)/dy;
    }
}
/*
 *@brief 右侧单点向下延伸：以拐点及往上4行处边界点拟合直线，延伸至底部
 *@param img 图像数据
 *@param x,y 右侧拐点坐标
 */
void right_lengthen(uint8_t img[IMG_H][IMG_W],int x,int y)
{
    int up_y=y-4;
    if(up_y<0)up_y=0;
    int up_x=right_boundary[up_y];
    if(!right_boundary_valid[up_y])return;//上边界丢线，无法拟合
    //计算底部延伸点的x坐标
    int dy=y-up_y;
    if(dy<=0)return;//防止除零
    int dx=x-up_x;
    int y_bottom=IMG_H-1;
    int x_bottom=up_x+dx*(y_bottom-up_y)/dy;
    //画线并更新right_boundary
    linktwo(img,up_x,up_y,x_bottom,y_bottom);
    for(int row=up_y;row<=y_bottom;row++)
    {
        right_boundary[row]=up_x+dx*(row-up_y)/dy;
    }
}
/*
 *@brief 十字路口补线处理：根据拐点检测情况分类补线
 *@detail 四种情况：只有两个上拐点 / 多一个左下拐点 / 多一个右下拐点 / 四个拐点都存在
 */
void cross_process(uint8_t img[IMG_H][IMG_W])
{
    int y,x;
    int left_up_x=corner_list[1].x,left_up_y=corner_list[1].y;
    int right_up_x=corner_list[3].x,right_up_y=corner_list[3].y;
    int left_down_x=corner_list[0].x,left_down_y=corner_list[0].y;
    int right_down_x=corner_list[2].x,right_down_y=corner_list[2].y;

    //出十字阶段只剩一个上拐点时，仅延长对应边界
    if(left_up_find&&!right_up_find)
    {
        int center_start=left_up_y-4;
        if(center_start<0)center_start=0;
        left_lengthen(img,left_up_x,left_up_y);
        for(y=center_start;y<IMG_H;y++)
            center[y]=(left_boundary[y]+right_boundary[y])/2;
        return;
    }
    if(!left_up_find&&right_up_find)
    {
        int center_start=right_up_y-4;
        if(center_start<0)center_start=0;
        right_lengthen(img,right_up_x,right_up_y);
        for(y=center_start;y<IMG_H;y++)
            center[y]=(left_boundary[y]+right_boundary[y])/2;
        return;
    }

    //根据已找到的拐点进行分类处理
    if(corner_list[0].type==CORNER_NONE&&corner_list[2].type==CORNER_NONE)
    {
        //只有两个上拐点，左右两侧都用单点延伸
        left_lengthen(img,left_up_x,left_up_y);
        right_lengthen(img,right_up_x,right_up_y);
        //重新计算中线
        for(y=left_up_y<right_up_y?left_up_y:right_up_y;y<=IMG_H-1;y++)
        {
            center[y]=(left_boundary[y]+right_boundary[y])/2;
        }
    }
    else if(corner_list[0].type!=CORNER_NONE&&corner_list[2].type==CORNER_NONE)
    {
        //两个上拐点+一个左下拐点，左侧连线，右侧单点延伸
        if(left_down_y>left_up_y)
        {
            linktwo(img,left_up_x,left_up_y,left_down_x,left_down_y);
            for(y=left_up_y;y<=left_down_y;y++)
            {
                x=left_up_x+(left_down_x-left_up_x)*(y-left_up_y)/(left_down_y-left_up_y);
                left_boundary[y]=x;
            }
        }
        right_lengthen(img,right_up_x,right_up_y);
        //重新计算中线
        for(y=left_up_y<right_up_y?left_up_y:right_up_y;y<=IMG_H-1;y++)
        {
            center[y]=(left_boundary[y]+right_boundary[y])/2;
        }
    }
    else if(corner_list[0].type==CORNER_NONE&&corner_list[2].type!=CORNER_NONE)
    {
        //两个上拐点+一个右下拐点，左侧单点延伸，右侧连线
        left_lengthen(img,left_up_x,left_up_y);
        if(right_down_y>right_up_y)
        {
            linktwo(img,right_up_x,right_up_y,right_down_x,right_down_y);
            for(y=right_up_y;y<=right_down_y;y++)
            {
                x=right_up_x+(right_down_x-right_up_x)*(y-right_up_y)/(right_down_y-right_up_y);
                right_boundary[y]=x;
            }
        }
        //重新计算中线
        for(y=left_up_y<right_up_y?left_up_y:right_up_y;y<=IMG_H-1;y++)
        {
            center[y]=(left_boundary[y]+right_boundary[y])/2;
        }
    }
    else
    {
        //四个拐点都存在，连接左右两侧上下拐点
        //在图像上画左右两侧连线
        if(left_down_y>left_up_y)
        {
            linktwo(img,left_up_x,left_up_y,left_down_x,left_down_y);
            for(y=left_up_y;y<=left_down_y;y++)
            {
                x=left_up_x+(left_down_x-left_up_x)*(y-left_up_y)/(left_down_y-left_up_y);
                left_boundary[y]=x;
            }
        }
        if(right_down_y>right_up_y)
        {
            linktwo(img,right_up_x,right_up_y,right_down_x,right_down_y);
            for(y=right_up_y;y<=right_down_y;y++)
            {
                x=right_up_x+(right_down_x-right_up_x)*(y-right_up_y)/(right_down_y-right_up_y);
                right_boundary[y]=x;
            }
        }
        //重新计算中线
        for(y=left_up_y<right_up_y?left_up_y:right_up_y;y<=(left_down_y>right_down_y?left_down_y:right_down_y);y++)
        {
            center[y]=(left_boundary[y]+right_boundary[y])/2;
        }
    }
}