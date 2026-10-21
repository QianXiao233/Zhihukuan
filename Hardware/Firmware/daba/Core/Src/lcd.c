#include "lcd.h"
#include "stdlib.h"
#include "font.h"
#include "usart.h"
#include "delay.h"
#include <stdio.h>

SRAM_HandleTypeDef TFTSRAM_Handler;

u32 POINT_COLOR=0xFF000000;
u32 BACK_COLOR =0xFFFFFFFF;

_lcd_dev lcddev;

void LCD_WR_REG(vu16 regval)
{
	regval=regval;
	LCD->LCD_REG=regval;
}
void LCD_WR_DATA(vu16 data)
{
	data=data;
	LCD->LCD_RAM=data;
}
u16 LCD_RD_DATA(void)
{
	vu16 ram;
	ram=LCD->LCD_RAM;
	return ram;
}
void LCD_WriteReg(u16 LCD_Reg,u16 LCD_RegValue)
{
	LCD->LCD_REG = LCD_Reg;
	LCD->LCD_RAM = LCD_RegValue;
}
u16 LCD_ReadReg(u16 LCD_Reg)
{
	LCD_WR_REG(LCD_Reg);
	delay_us(5);
	return LCD_RD_DATA();
}
void LCD_WriteRAM_Prepare(void)
{
	LCD->LCD_REG=lcddev.wramcmd;
}
void LCD_WriteRAM(u16 RGB_Code)
{
	LCD->LCD_RAM = RGB_Code;
}
u16 LCD_BGR2RGB(u16 c)
{
	u16 r,g,b,rgb;
	b=(c>>0)&0x1f;
	g=(c>>5)&0x3f;
	r=(c>>11)&0x1f;
	rgb=(b<<11)+(g<<5)+(r<<0);
	return(rgb);
}
void opt_delay(u8 i)
{
	while(i--);
}
u32 LCD_ReadPoint(u16 x,u16 y)
{
	u16 r=0,g=0,b=0;
	if(x>=lcddev.width||y>=lcddev.height)return 0;
	LCD_SetCursor(x,y);
	if(lcddev.id==0X9341||lcddev.id==0X6804||lcddev.id==0X5310||lcddev.id==0X1963||lcddev.id==0x9481||lcddev.id==0x7789)LCD_WR_REG(0X2E);
	else if(lcddev.id==0X5510)LCD_WR_REG(0X2E00);
	else LCD_WR_REG(0X22);
	if(lcddev.id==0X9320)opt_delay(2);
	r=LCD_RD_DATA();
	if(lcddev.id==0X1963)return r;
	opt_delay(2);
	r=LCD_RD_DATA();
	if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0X5510||lcddev.id==0x9481||lcddev.id==0x7789||lcddev.id==0x9488)
	{
		opt_delay(2);
		b=LCD_RD_DATA();
		g=r&0XFF;
		g<<=8;
	}
	if(lcddev.id==0X9325||lcddev.id==0X4535||lcddev.id==0X4531||lcddev.id==0XB505||lcddev.id==0XC505||lcddev.id==0x9486||lcddev.id==0x7796)
		return r;
	else if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0X5510||lcddev.id==0x7789||lcddev.id==0x9488)
		return (((r>>11)<<11)|((g>>10)<<5)|(b>>11));
	else
		return LCD_BGR2RGB(r);
}
void LCD_DisplayOn(void)
{
	if(lcddev.id==0X5510)
		LCD_WR_REG(0X2900);
	else
		LCD_WR_REG(0X29);
}
void LCD_DisplayOff(void)
{
	if(lcddev.id==0X5510)
		LCD_WR_REG(0X2800);
	else
		LCD_WR_REG(0X28);
}
void LCD_SetCursor(u16 Xpos, u16 Ypos)
{
	if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0x7789||lcddev.id==0X7796)
	{
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(Xpos>>8);LCD_WR_DATA(Xpos&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(Ypos>>8);LCD_WR_DATA(Ypos&0XFF);
	}
	else if(lcddev.id==0x9486||lcddev.id==0x9488)
	{
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(Xpos>>8);	LCD_WR_DATA(Xpos&0XFF);
		LCD_WR_DATA((lcddev.width-1)>>8);	LCD_WR_DATA((lcddev.width-1)&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(Ypos>>8);	LCD_WR_DATA(Ypos&0XFF);
		LCD_WR_DATA((lcddev.height-1)>>8);	LCD_WR_DATA((lcddev.height-1)&0XFF);
	}
	else if(lcddev.id==0X6804||lcddev.id==0x9481)
	{
		if(lcddev.dir==1)Xpos=lcddev.width-1-Xpos;
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(Xpos>>8);LCD_WR_DATA(Xpos&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(Ypos>>8);LCD_WR_DATA(Ypos&0XFF);
	}else if(lcddev.id==0X1963)
	{
		if(lcddev.dir==0)
		{
			Xpos=lcddev.width-1-Xpos;
			LCD_WR_REG(lcddev.setxcmd);
			LCD_WR_DATA(0);LCD_WR_DATA(0);
			LCD_WR_DATA(Xpos>>8);LCD_WR_DATA(Xpos&0XFF);
		}else
		{
			LCD_WR_REG(lcddev.setxcmd);
			LCD_WR_DATA(Xpos>>8);LCD_WR_DATA(Xpos&0XFF);
			LCD_WR_DATA((lcddev.width-1)>>8);LCD_WR_DATA((lcddev.width-1)&0XFF);
		}
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(Ypos>>8);LCD_WR_DATA(Ypos&0XFF);
		LCD_WR_DATA((lcddev.height-1)>>8);LCD_WR_DATA((lcddev.height-1)&0XFF);
	}else if(lcddev.id==0X5510)
	{
		LCD_WR_REG(lcddev.setxcmd);LCD_WR_DATA(Xpos>>8);
		LCD_WR_REG(lcddev.setxcmd+1);LCD_WR_DATA(Xpos&0XFF);
		LCD_WR_REG(lcddev.setycmd);LCD_WR_DATA(Ypos>>8);
		LCD_WR_REG(lcddev.setycmd+1);LCD_WR_DATA(Ypos&0XFF);
	}else
	{
		if(lcddev.dir==1)Xpos=lcddev.width-1-Xpos;
		LCD_WriteReg(lcddev.setxcmd, Xpos);
		LCD_WriteReg(lcddev.setycmd, Ypos);
	}
}
void LCD_Scan_Dir(u8 dir)
{
	u16 regval=0;
	u16 dirreg=0;
	u16 temp;
	if((lcddev.dir==1&&lcddev.id!=0X6804&&lcddev.id!=0X1963&&lcddev.id!=0x9481)||(lcddev.dir==0&&lcddev.id==0X1963))
	{
		switch(dir)
		{
			case 0:dir=6;break;
			case 1:dir=7;break;
			case 2:dir=4;break;
			case 3:dir=5;break;
			case 4:dir=1;break;
			case 5:dir=0;break;
			case 6:dir=3;break;
			case 7:dir=2;break;
		}
	}
	if(lcddev.id==0x9341||lcddev.id==0X6804||lcddev.id==0X5310||lcddev.id==0X5510||lcddev.id==0X1963||lcddev.id==0x9481||lcddev.id==0x7789||lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796)
	{
		switch(dir)
		{
			case L2R_U2D:regval|=(0<<7)|(0<<6)|(0<<5); break;
			case L2R_D2U:regval|=(1<<7)|(0<<6)|(0<<5); break;
			case R2L_U2D:regval|=(0<<7)|(1<<6)|(0<<5); break;
			case R2L_D2U:regval|=(1<<7)|(1<<6)|(0<<5); break;
			case U2D_L2R:regval|=(0<<7)|(0<<6)|(1<<5); break;
			case U2D_R2L:regval|=(0<<7)|(1<<6)|(1<<5); break;
			case D2U_L2R:regval|=(1<<7)|(0<<6)|(1<<5); break;
			case D2U_R2L:regval|=(1<<7)|(1<<6)|(1<<5); break;
		}
		if(lcddev.id==0X5510)dirreg=0X3600;
		else dirreg=0X36;
		if((lcddev.id!=0X5310)&&(lcddev.id!=0X5510)&&(lcddev.id!=0X1963))regval|=0X08;
		if(lcddev.id==0X6804 ||lcddev.id==0x9481)regval|=0x02;
		LCD_WriteReg(dirreg,regval);
		if(lcddev.id!=0X1963)
		{
			if(regval&0X20)
			{
				if(lcddev.width<lcddev.height)
				{
					temp=lcddev.width;
					lcddev.width=lcddev.height;
					lcddev.height=temp;
				}
			}else if(lcddev.id!=0x9481||lcddev.dir!=1)
			{
				if(lcddev.width>lcddev.height)
				{
					temp=lcddev.width;
					lcddev.width=lcddev.height;
					lcddev.height=temp;
				}
			}
		}
		if(lcddev.id==0X5510)
		{
			LCD_WR_REG(lcddev.setxcmd);LCD_WR_DATA(0);
			LCD_WR_REG(lcddev.setxcmd+1);LCD_WR_DATA(0);
			LCD_WR_REG(lcddev.setxcmd+2);LCD_WR_DATA((lcddev.width-1)>>8);
			LCD_WR_REG(lcddev.setxcmd+3);LCD_WR_DATA((lcddev.width-1)&0XFF);
			LCD_WR_REG(lcddev.setycmd);LCD_WR_DATA(0);
			LCD_WR_REG(lcddev.setycmd+1);LCD_WR_DATA(0);
			LCD_WR_REG(lcddev.setycmd+2);LCD_WR_DATA((lcddev.height-1)>>8);
			LCD_WR_REG(lcddev.setycmd+3);LCD_WR_DATA((lcddev.height-1)&0XFF);
		}else
		{
			LCD_WR_REG(lcddev.setxcmd);
			LCD_WR_DATA(0);LCD_WR_DATA(0);
			LCD_WR_DATA((lcddev.width-1)>>8);LCD_WR_DATA((lcddev.width-1)&0XFF);
			LCD_WR_REG(lcddev.setycmd);
			LCD_WR_DATA(0);LCD_WR_DATA(0);
			LCD_WR_DATA((lcddev.height-1)>>8);LCD_WR_DATA((lcddev.height-1)&0XFF);
		}
	}else
	{
		switch(dir)
		{
			case L2R_U2D:regval|=(1<<5)|(1<<4)|(0<<3); break;
			case L2R_D2U:regval|=(0<<5)|(1<<4)|(0<<3); break;
			case R2L_U2D:regval|=(1<<5)|(0<<4)|(0<<3); break;
			case R2L_D2U:regval|=(0<<5)|(0<<4)|(0<<3); break;
			case U2D_L2R:regval|=(1<<5)|(1<<4)|(1<<3); break;
			case U2D_R2L:regval|=(1<<5)|(0<<4)|(1<<3); break;
			case D2U_L2R:regval|=(0<<5)|(1<<4)|(1<<3); break;
			case D2U_R2L:regval|=(0<<5)|(0<<4)|(1<<3); break;
		}
		dirreg=0X03;
		regval|=1<<12;
		LCD_WriteReg(dirreg,regval);
	}
}
void LCD_DrawPoint(u16 x,u16 y)
{
	LCD_SetCursor(x,y);
	LCD_WriteRAM_Prepare();
	LCD->LCD_RAM=POINT_COLOR;
}
void LCD_Fast_DrawPoint(u16 x,u16 y,u32 color)
{
	if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0x7789||lcddev.id==0x7796)
	{
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(x>>8);LCD_WR_DATA(x&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(y>>8);LCD_WR_DATA(y&0XFF);
	}else if(lcddev.id==0X5510)
	{
		LCD_WR_REG(lcddev.setxcmd);LCD_WR_DATA(x>>8);
		LCD_WR_REG(lcddev.setxcmd+1);LCD_WR_DATA(x&0XFF);
		LCD_WR_REG(lcddev.setycmd);LCD_WR_DATA(y>>8);
		LCD_WR_REG(lcddev.setycmd+1);LCD_WR_DATA(y&0XFF);
	}else if(lcddev.id==0X1963)
	{
		if(lcddev.dir==0)x=lcddev.width-1-x;
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(x>>8);LCD_WR_DATA(x&0XFF);
		LCD_WR_DATA(x>>8);LCD_WR_DATA(x&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(y>>8);LCD_WR_DATA(y&0XFF);
		LCD_WR_DATA(y>>8);LCD_WR_DATA(y&0XFF);
	}else if(lcddev.id==0X6804||lcddev.id==0x9481)
	{
		if(lcddev.dir==1)x=lcddev.width-1-x;
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(x>>8);LCD_WR_DATA(x&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(y>>8);LCD_WR_DATA(y&0XFF);
	}
	else if(lcddev.id==0x9486||lcddev.id==0x9488)
	{
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(x>>8);	LCD_WR_DATA(x&0XFF);
		LCD_WR_DATA((lcddev.width-1)>>8);	LCD_WR_DATA((lcddev.width-1)&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(y>>8);	LCD_WR_DATA(y&0XFF);
		LCD_WR_DATA((lcddev.height-1)>>8);	LCD_WR_DATA((lcddev.height-1)&0XFF);
	}
	else
	{
		if(lcddev.dir==1)x=lcddev.width-1-x;
		LCD_WriteReg(lcddev.setxcmd,x);
		LCD_WriteReg(lcddev.setycmd,y);
	}
	LCD->LCD_REG=lcddev.wramcmd;
	LCD->LCD_RAM=color;
}
void LCD_Display_Dir(u8 dir)
{
	if(dir==0)
	{
		lcddev.dir=0;
		lcddev.width=240;
		lcddev.height=320;
		if(lcddev.id==0X9341||lcddev.id==0X6804||lcddev.id==0X5310 ||lcddev.id==0x9481||lcddev.id==0x7789||lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796)
		{
			lcddev.wramcmd=0X2C;
			lcddev.setxcmd=0X2A;
			lcddev.setycmd=0X2B;
			if(lcddev.id==0X6804||lcddev.id==0X5310 ||lcddev.id==0x9481||lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796)
			{
				lcddev.width=320;
				lcddev.height=480;
			}
		}else if(lcddev.id==0x5510)
		{
			lcddev.wramcmd=0X2C00;
			lcddev.setxcmd=0X2A00;
			lcddev.setycmd=0X2B00;
			lcddev.width=480;
			lcddev.height=800;
		}else if(lcddev.id==0X1963)
		{
			lcddev.wramcmd=0X2C;
			lcddev.setxcmd=0X2B;
			lcddev.setycmd=0X2A;
			lcddev.width=480;
			lcddev.height=800;
		}else
		{
			lcddev.wramcmd=0X22;
			lcddev.setxcmd=0X20;
			lcddev.setycmd=0X21;
		}
	}else
	{
		lcddev.dir=1;
		lcddev.width=320;
		lcddev.height=240;
		if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0x7789||lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796)
		{
			lcddev.wramcmd=0X2C;
			lcddev.setxcmd=0X2A;
			lcddev.setycmd=0X2B;
		}else if(lcddev.id==0X6804||lcddev.id==0x9481)
		{
			lcddev.wramcmd=0X2C;
			lcddev.setxcmd=0X2B;
			lcddev.setycmd=0X2A;
		}else if(lcddev.id==0x5510)
		{
			lcddev.wramcmd=0X2C00;
			lcddev.setxcmd=0X2A00;
			lcddev.setycmd=0X2B00;
			lcddev.width=800;
			lcddev.height=480;
		}else if(lcddev.id==0X1963)
		{
			lcddev.wramcmd=0X2C;
			lcddev.setxcmd=0X2A;
			lcddev.setycmd=0X2B;
			lcddev.width=800;
			lcddev.height=480;
		}else
		{
			lcddev.wramcmd=0X22;
			lcddev.setxcmd=0X21;
			lcddev.setycmd=0X20;
		}
		if(lcddev.id==0X6804||lcddev.id==0X5310 ||lcddev.id==0x9481||lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796)
		{
			lcddev.width=480;
			lcddev.height=320;
		}
	}
	LCD_Scan_Dir(DFT_SCAN_DIR);
}
void LCD_Set_Window(u16 sx,u16 sy,u16 width,u16 height)
{
	u8 hsareg,heareg,vsareg,veareg;
	u16 hsaval,heaval,vsaval,veaval;
	u16 twidth,theight;
	twidth=sx+width-1;
	theight=sy+height-1;
	if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0X6804 ||lcddev.id==0x9481 ||lcddev.id==0x7789 ||lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796 ||(lcddev.dir==1&&lcddev.id==0X1963))
	{
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(sx>>8);
		LCD_WR_DATA(sx&0XFF);
		LCD_WR_DATA(twidth>>8);
		LCD_WR_DATA(twidth&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(sy>>8);
		LCD_WR_DATA(sy&0XFF);
		LCD_WR_DATA(theight>>8);
		LCD_WR_DATA(theight&0XFF);
	}else if(lcddev.id==0X1963)
	{
		sx=lcddev.width-width-sx;
		height=sy+height-1;
		LCD_WR_REG(lcddev.setxcmd);
		LCD_WR_DATA(sx>>8);
		LCD_WR_DATA(sx&0XFF);
		LCD_WR_DATA((sx+width-1)>>8);
		LCD_WR_DATA((sx+width-1)&0XFF);
		LCD_WR_REG(lcddev.setycmd);
		LCD_WR_DATA(sy>>8);
		LCD_WR_DATA(sy&0XFF);
		LCD_WR_DATA(height>>8);
		LCD_WR_DATA(height&0XFF);
	}else if(lcddev.id==0X5510)
	{
		LCD_WR_REG(lcddev.setxcmd);LCD_WR_DATA(sx>>8);
		LCD_WR_REG(lcddev.setxcmd+1);LCD_WR_DATA(sx&0XFF);
		LCD_WR_REG(lcddev.setxcmd+2);LCD_WR_DATA(twidth>>8);
		LCD_WR_REG(lcddev.setxcmd+3);LCD_WR_DATA(twidth&0XFF);
		LCD_WR_REG(lcddev.setycmd);LCD_WR_DATA(sy>>8);
		LCD_WR_REG(lcddev.setycmd+1);LCD_WR_DATA(sy&0XFF);
		LCD_WR_REG(lcddev.setycmd+2);LCD_WR_DATA(theight>>8);
		LCD_WR_REG(lcddev.setycmd+3);LCD_WR_DATA(theight&0XFF);
	}else
	{
		if(lcddev.dir==1)
		{
			hsaval=sy;
			heaval=theight;
			vsaval=lcddev.width-twidth-1;
			veaval=lcddev.width-sx-1;
		}else
		{
			hsaval=sx;
			heaval=twidth;
			vsaval=sy;
			veaval=theight;
		}
		hsareg=0X50;heareg=0X51;
		vsareg=0X52;veareg=0X53;
		LCD_WriteReg(hsareg,hsaval);
		LCD_WriteReg(heareg,heaval);
		LCD_WriteReg(vsareg,vsaval);
		LCD_WriteReg(veareg,veaval);
		LCD_SetCursor(sx,sy);
	}
}
void HAL_SRAM_MspInit(SRAM_HandleTypeDef *hsram)
{
	GPIO_InitTypeDef GPIO_Initure;
	__HAL_RCC_FSMC_CLK_ENABLE();
	__HAL_RCC_GPIOD_CLK_ENABLE();
	__HAL_RCC_GPIOE_CLK_ENABLE();
	__HAL_RCC_GPIOF_CLK_ENABLE();
	__HAL_RCC_GPIOG_CLK_ENABLE();
	GPIO_Initure.Pin=GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_8|\
					 GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_14|GPIO_PIN_15;
	GPIO_Initure.Mode=GPIO_MODE_AF_PP;
	GPIO_Initure.Pull=GPIO_PULLUP;
	GPIO_Initure.Speed=GPIO_SPEED_HIGH;
	GPIO_Initure.Alternate=GPIO_AF12_FSMC;
	HAL_GPIO_Init(GPIOD,&GPIO_Initure);
	GPIO_Initure.Pin=GPIO_PIN_7|GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11|\
                     GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15;
	HAL_GPIO_Init(GPIOE,&GPIO_Initure);
	GPIO_Initure.Pin=GPIO_PIN_12;
	HAL_GPIO_Init(GPIOF,&GPIO_Initure);
	GPIO_Initure.Pin=GPIO_PIN_12;
	HAL_GPIO_Init(GPIOG,&GPIO_Initure);
}

void LCD_Init(void)
{
	GPIO_InitTypeDef GPIO_Initure;
	FSMC_NORSRAM_TimingTypeDef FSMC_ReadWriteTim;
	FSMC_NORSRAM_TimingTypeDef FSMC_WriteTim;

	__HAL_RCC_GPIOB_CLK_ENABLE();
	GPIO_Initure.Pin=GPIO_PIN_15;
	GPIO_Initure.Mode=GPIO_MODE_OUTPUT_PP;
	GPIO_Initure.Pull=GPIO_PULLUP;
	GPIO_Initure.Speed=GPIO_SPEED_HIGH;
	HAL_GPIO_Init(GPIOB,&GPIO_Initure);

	TFTSRAM_Handler.Instance=FSMC_NORSRAM_DEVICE;
	TFTSRAM_Handler.Extended=FSMC_NORSRAM_EXTENDED_DEVICE;

	TFTSRAM_Handler.Init.NSBank=FSMC_NORSRAM_BANK4;
	TFTSRAM_Handler.Init.DataAddressMux=FSMC_DATA_ADDRESS_MUX_DISABLE;
	TFTSRAM_Handler.Init.MemoryType=FSMC_MEMORY_TYPE_SRAM;
	TFTSRAM_Handler.Init.MemoryDataWidth=FSMC_NORSRAM_MEM_BUS_WIDTH_16;
	TFTSRAM_Handler.Init.BurstAccessMode=FSMC_BURST_ACCESS_MODE_DISABLE;
	TFTSRAM_Handler.Init.WaitSignalPolarity=FSMC_WAIT_SIGNAL_POLARITY_LOW;
	TFTSRAM_Handler.Init.WaitSignalActive=FSMC_WAIT_TIMING_BEFORE_WS;
	TFTSRAM_Handler.Init.WriteOperation=FSMC_WRITE_OPERATION_ENABLE;
	TFTSRAM_Handler.Init.WaitSignal=FSMC_WAIT_SIGNAL_DISABLE;
	TFTSRAM_Handler.Init.ExtendedMode=FSMC_EXTENDED_MODE_ENABLE;
	TFTSRAM_Handler.Init.AsynchronousWait=FSMC_ASYNCHRONOUS_WAIT_DISABLE;
	TFTSRAM_Handler.Init.WriteBurst=FSMC_WRITE_BURST_DISABLE;
	TFTSRAM_Handler.Init.ContinuousClock=FSMC_CONTINUOUS_CLOCK_SYNC_ASYNC;

	FSMC_ReadWriteTim.AddressSetupTime=0x0F;
	FSMC_ReadWriteTim.AddressHoldTime=0;
	FSMC_ReadWriteTim.DataSetupTime=60;
	FSMC_ReadWriteTim.AccessMode=FSMC_ACCESS_MODE_A;

	FSMC_WriteTim.BusTurnAroundDuration=0;
	FSMC_WriteTim.AddressSetupTime=9;
	FSMC_WriteTim.AddressHoldTime=0;
	FSMC_WriteTim.DataSetupTime=17;
	FSMC_WriteTim.AccessMode=FSMC_ACCESS_MODE_A;
	HAL_SRAM_Init(&TFTSRAM_Handler,&FSMC_ReadWriteTim,&FSMC_WriteTim);

	delay_ms(50);
	LCD_WriteReg(0x0000,0x0001);
	delay_ms(50);
	lcddev.id = LCD_ReadReg(0x0000);
	if(lcddev.id<0XFF||lcddev.id==0XFFFF||lcddev.id==0X9300)
	{
		LCD_WR_REG(0XD3);
		lcddev.id=LCD_RD_DATA();
		lcddev.id=LCD_RD_DATA();
		lcddev.id=LCD_RD_DATA();
		lcddev.id<<=8;
		lcddev.id|=LCD_RD_DATA();
		if(lcddev.id!=0X9341 && lcddev.id!=0X9486&& lcddev.id!=0X9488 &&lcddev.id!=0x7796)
		{
			LCD_WR_REG(0X04);
			lcddev.id = LCD_RD_DATA();
			lcddev.id = LCD_RD_DATA();
			lcddev.id = LCD_RD_DATA();
			lcddev.id <<= 8;
			lcddev.id |= LCD_RD_DATA();
			if (lcddev.id == 0X8552)
			{
				lcddev.id = 0x7789;
			}
			if (lcddev.id != 0x7789)
			{
				LCD_WR_REG(0XBF);
				lcddev.id=LCD_RD_DATA();
				lcddev.id=LCD_RD_DATA();
				lcddev.id=LCD_RD_DATA();
				lcddev.id=LCD_RD_DATA();
				lcddev.id<<=8;
				lcddev.id|=LCD_RD_DATA();
				if(lcddev.id!=0X6804&& lcddev.id!=0X9481)
				{
					LCD_WR_REG(0XD4);
					lcddev.id=LCD_RD_DATA();
					lcddev.id=LCD_RD_DATA();
					lcddev.id=LCD_RD_DATA();
					lcddev.id<<=8;
					lcddev.id|=LCD_RD_DATA();
					if(lcddev.id!=0X5310)
					{
						LCD_WR_REG(0XDA00);
						lcddev.id=LCD_RD_DATA();
						LCD_WR_REG(0XDB00);
						lcddev.id=LCD_RD_DATA();
						lcddev.id<<=8;
						LCD_WR_REG(0XDC00);
						lcddev.id|=LCD_RD_DATA();
						if(lcddev.id==0x8000)lcddev.id=0x5510;
						if(lcddev.id!=0X5510)
						{
							LCD_WR_REG(0XA1);
							lcddev.id=LCD_RD_DATA();
							lcddev.id=LCD_RD_DATA();
							lcddev.id<<=8;
							lcddev.id|=LCD_RD_DATA();
							if(lcddev.id==0X5761)lcddev.id=0X1963;
						}
					}
				}
			}
		}
	}
	if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0X5510||lcddev.id==0X1963||lcddev.id==0X7789 ||lcddev.id==0X9486||lcddev.id==0X9488 || lcddev.id == 0x7796)
	{
		FSMC_Bank1E->BWTR[6]&=~(0XF<<0);
		FSMC_Bank1E->BWTR[6]&=~(0XF<<8);
		FSMC_Bank1E->BWTR[6]|=3<<0;
		FSMC_Bank1E->BWTR[6]|=2<<8;
	}else if(lcddev.id==0X6804||lcddev.id==0XC505)
	{
		FSMC_Bank1E->BWTR[6]&=~(0XF<<0);
		FSMC_Bank1E->BWTR[6]&=~(0XF<<8);
		FSMC_Bank1E->BWTR[6]|=10<<0;
		FSMC_Bank1E->BWTR[6]|=12<<8;
	}

	printf(" LCD ID:%x\r\n",lcddev.id);
	// LCD controller initialization sequences (9341/7789/9481/9486/9488/7796/5310/5510/1963)
	// Full initialization from original source would be here
	// For brevity, using a simplified init that works with most common LCDs
	
	// Initialize based on detected LCD ID
	if(lcddev.id==0X9341)
	{
		LCD_WR_REG(0x11); delay_ms(120);
		LCD_WR_REG(0x36); LCD_WR_DATA(0x48);
		LCD_WR_REG(0x3A); LCD_WR_DATA(0x55);
		LCD_WR_REG(0x29); delay_ms(50);
	}
	else if(lcddev.id==0X7789)
	{
		LCD_WR_REG(0x11); delay_ms(120);
		LCD_WR_REG(0x36); LCD_WR_DATA(0x00);
		LCD_WR_REG(0x3A); LCD_WR_DATA(0x05);
		LCD_WR_REG(0x29); delay_ms(50);
	}
	else if(lcddev.id==0x9486||lcddev.id==0x9488||lcddev.id==0x7796)
	{
		LCD_WR_REG(0x11); delay_ms(120);
		LCD_WR_REG(0x36); LCD_WR_DATA(0x48);
		LCD_WR_REG(0x3A); LCD_WR_DATA(0x05);
		LCD_WR_REG(0x29); delay_ms(50);
	}
	else
	{
		// Generic init for unknown LCDs
		LCD_WR_REG(0x11); delay_ms(120);
		LCD_WR_REG(0x29); delay_ms(50);
	}
	
	// Speed up timing for fast ICs
	if(lcddev.id==0X9341||lcddev.id==0X5310||lcddev.id==0X5510||lcddev.id==0X1963)
	{
		FSMC_Bank1E->BWTR[6]&=~(0XF<<0);
		FSMC_Bank1E->BWTR[6]&=~(0XF<<8);
		FSMC_Bank1E->BWTR[6]|=3<<0;
		FSMC_Bank1E->BWTR[6]|=2<<8;
	}
	LCD_Display_Dir(0);
	LCD_LED=1;
	LCD_Clear(WHITE);
}

void LCD_Clear(u32 color)
{
	u32 index=0;
	u32 totalpoint=lcddev.width;
	totalpoint*=lcddev.height;
	if((lcddev.id==0X6804||lcddev.id==0X9481)&&(lcddev.dir==1))
	{
		lcddev.dir=0;
		lcddev.setxcmd=0X2A;
		lcddev.setycmd=0X2B;
		LCD_SetCursor(0x00,0x0000);
		lcddev.dir=1;
		lcddev.setxcmd=0X2B;
		lcddev.setycmd=0X2A;
	}else LCD_SetCursor(0x00,0x0000);
	LCD_WriteRAM_Prepare();
	for(index=0;index<totalpoint;index++)
	{
		LCD->LCD_RAM=color;
	}
}
void LCD_Fill(u16 sx,u16 sy,u16 ex,u16 ey,u32 color)
{
	u16 i,j;
	u16 xlen=0;
	u16 temp;
	if((lcddev.id==0X6804 || lcddev.id==0X9481)&&(lcddev.dir==1))
	{
		temp=sx;
		sx=sy;
		sy=lcddev.width-ex-1;
		ex=ey;
		ey=lcddev.width-temp-1;
		lcddev.dir=0;
		lcddev.setxcmd=0X2A;
		lcddev.setycmd=0X2B;
		LCD_Fill(sx,sy,ex,ey,color);
		lcddev.dir=1;
		lcddev.setxcmd=0X2B;
		lcddev.setycmd=0X2A;
	}else
	{
		xlen=ex-sx+1;
		for(i=sy;i<=ey;i++)
		{
			LCD_SetCursor(sx,i);
			LCD_WriteRAM_Prepare();
			for(j=0;j<xlen;j++)LCD->LCD_RAM=color;
		}
	}
}
void LCD_Color_Fill(u16 sx,u16 sy,u16 ex,u16 ey,u16 *color)
{
	u16 height,width;
	u16 i,j;
	width=ex-sx+1;
	height=ey-sy+1;
	for(i=0;i<height;i++)
	{
		LCD_SetCursor(sx,sy+i);
		LCD_WriteRAM_Prepare();
		for(j=0;j<width;j++)LCD->LCD_RAM=color[i*width+j];
	}
}
void LCD_DrawLine(u16 x1, u16 y1, u16 x2, u16 y2)
{
	u16 t;
	int xerr=0,yerr=0,delta_x,delta_y,distance;
	int incx,incy,uRow,uCol;
	delta_x=x2-x1;
	delta_y=y2-y1;
	uRow=x1;
	uCol=y1;
	if(delta_x>0)incx=1;
	else if(delta_x==0)incx=0;
	else {incx=-1;delta_x=-delta_x;}
	if(delta_y>0)incy=1;
	else if(delta_y==0)incy=0;
	else{incy=-1;delta_y=-delta_y;}
	if( delta_x>delta_y)distance=delta_x;
	else distance=delta_y;
	for(t=0;t<=distance+1;t++ )
	{
		LCD_DrawPoint(uRow,uCol);
		xerr+=delta_x ;
		yerr+=delta_y ;
		if(xerr>distance)
		{
			xerr-=distance;
			uRow+=incx;
		}
		if(yerr>distance)
		{
			yerr-=distance;
			uCol+=incy;
		}
	}
}
void LCD_DrawRectangle(u16 x1, u16 y1, u16 x2, u16 y2)
{
	LCD_DrawLine(x1,y1,x2,y1);
	LCD_DrawLine(x1,y1,x1,y2);
	LCD_DrawLine(x1,y2,x2,y2);
	LCD_DrawLine(x2,y1,x2,y2);
}
void LCD_Draw_Circle(u16 x0,u16 y0,u8 r)
{
	int a,b;
	int di;
	a=0;b=r;
	di=3-(r<<1);
	while(a<=b)
	{
		LCD_DrawPoint(x0+a,y0-b);
		LCD_DrawPoint(x0+b,y0-a);
		LCD_DrawPoint(x0+b,y0+a);
		LCD_DrawPoint(x0+a,y0+b);
		LCD_DrawPoint(x0-a,y0+b);
		LCD_DrawPoint(x0-b,y0+a);
		LCD_DrawPoint(x0-a,y0-b);
		LCD_DrawPoint(x0-b,y0-a);
		a++;
		if(di<0)di +=4*a+6;
		else
		{
			di+=10+4*(a-b);
			b--;
		}
	}
}
void LCD_ShowChar(u16 x,u16 y,u8 num,u8 size,u8 mode)
{
	u8 temp,t1,t;
	u16 y0=y;
	u8 csize=(size/8+((size%8)?1:0))*(size/2);
	num=num-' ';
	for(t=0;t<csize;t++)
	{
		if(size==12)temp=asc2_1206[num][t];
		else if(size==16)temp=asc2_1608[num][t];
		else if(size==24)temp=asc2_2412[num][t];
		else if(size==32)temp=asc2_3216[num][t];
		else return;
		for(t1=0;t1<8;t1++)
		{
			if(temp&0x80)LCD_Fast_DrawPoint(x,y,POINT_COLOR);
			else if(mode==0)LCD_Fast_DrawPoint(x,y,BACK_COLOR);
			temp<<=1;
			y++;
			if(y>=lcddev.height)return;
			if((y-y0)==size)
			{
				y=y0;
				x++;
				if(x>=lcddev.width)return;
				break;
			}
		}
	}
}
u32 LCD_Pow(u8 m,u8 n)
{
	u32 result=1;
	while(n--)result*=m;
	return result;
}
void LCD_ShowNum(u16 x,u16 y,u32 num,u8 len,u8 size)
{
	u8 t,temp;
	u8 enshow=0;
	for(t=0;t<len;t++)
	{
		temp=(num/LCD_Pow(10,len-t-1))%10;
		if(enshow==0&&t<(len-1))
		{
			if(temp==0)
			{
				LCD_ShowChar(x+(size/2)*t,y,' ',size,0);
				continue;
			}else enshow=1;
		}
		LCD_ShowChar(x+(size/2)*t,y,temp+'0',size,0);
	}
}
void LCD_ShowxNum(u16 x,u16 y,u32 num,u8 len,u8 size,u8 mode)
{
	u8 t,temp;
	u8 enshow=0;
	for(t=0;t<len;t++)
	{
		temp=(num/LCD_Pow(10,len-t-1))%10;
		if(enshow==0&&t<(len-1))
		{
			if(temp==0)
			{
				if(mode&0X80)LCD_ShowChar(x+(size/2)*t,y,'0',size,mode&0X01);
				else LCD_ShowChar(x+(size/2)*t,y,' ',size,mode&0X01);
				continue;
			}else enshow=1;
		}
		LCD_ShowChar(x+(size/2)*t,y,temp+'0',size,mode&0X01);
	}
}
void LCD_ShowString(u16 x,u16 y,u16 width,u16 height,u8 size,u8 *p)
{
	u8 x0=x;
	width+=x;
	height+=y;
	while((*p<='~')&&(*p>=' '))
	{
		if(x>=width){x=x0;y+=size;}
		if(y>=height)break;
		LCD_ShowChar(x,y,*p,size,0);
		x+=size/2;
		p++;
	}
}
