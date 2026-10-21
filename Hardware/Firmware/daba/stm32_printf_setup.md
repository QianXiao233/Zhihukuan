# STM32 CMake 串口 printf 不乱码方案

## 核心三要素

| # | 要素 | 作用 | 是否必需 |
|---|------|------|---------|
| 1 | `__io_putchar` 实现 | 重定向 `printf` 到 UART | **必需** |
| 2 | `--specs=nano.specs` | 使用 newlib-nano 精简 libc | **必需** |
| 3 | `-u _printf_float` | 启用浮点格式化支持 | 用到 `%f` 则**必需** |

---

## 1. `__io_putchar` 实现

CubeMX 生成的 `syscalls.c` 中有两个弱符号：

```c
__attribute__((weak)) int __io_putchar(int ch) { }
__attribute__((weak)) int _write(int file, char *ptr, int len) {
    for(int i = 0; i < len; i++) __io_putchar(*ptr++);
    return len;
}
```

需要在项目的任意 `.c` 文件中**提供一个非弱符号的实现**来覆盖它：

```c
int __io_putchar(int ch) {
    HAL_UART_Transmit(&huart1, (uint8_t*)&ch, 1, 100);
    return ch;
}
```

### 放置位置

放在 `/* USER CODE BEGIN 1 */` 段即可（`main.c` 或 `usart.c` 都可以）。

### 原理

`_write` → `__io_putchar`（弱符号）→ 用户提供的强符号覆盖 → `HAL_UART_Transmit`

---

## 2. CMakeLists.txt 链接选项

```cmake
set(CMAKE_EXE_LINKER_FLAGS "... --specs=nano.specs -lc -lm -u _printf_float")
```

| 选项 | 说明 |
|------|------|
| `--specs=nano.specs` | 使用 newlib-nano（非 full newlib），大幅减少 FLASH 占用 |
| `-lc` | 链接 C 标准库 |
| `-lm` | 链接数学库（`sin`、`cos` 等） |
| `-u _printf_float` | **强制链接浮点格式化代码**，不加则 `printf("%f")` 输出空白或 `?` |
| `-u _scanf_float` | 如果用 `scanf` 读浮点数，也需要加 |

### p3 项目已验证的完整链接配置

```cmake
set(CMAKE_EXE_LINKER_FLAGS "${CPU_FLAGS} -T ${CMAKE_CURRENT_SOURCE_DIR}/STM32F407XX_FLASH.ld --specs=nano.specs -Wl,-Map=project.map -Wl,--gc-sections -lc -lm -u _printf_float")
```

---

## 3. 常见错误

| 错误现象 | 原因 | 解决 |
|---------|------|------|
| printf 无输出 | `__io_putchar` 未实现 | 实现 `__io_putchar` |
| printf 无输出 | `__io_putchar` 也是弱符号 | 不要加 `weak` 属性 |
| `%f` 输出空白或 `?` | 缺少 `-u _printf_float` | 链接时加 `-u _printf_float` |
| FLASH 超限 | 没加 `--specs=nano.specs` | 改用 nano.specs |
| 在中断里调用 printf | HAL_UART_Transmit 阻塞导致死锁 | 中断中只设标志，延迟到主循环打印 |
| 换行不显示 | 只有 `\n` 没有 `\r\n` | 用 `\r\n` |

---

## 4. printf 浮点注意事项

```c
// 不要用 sprintf + %f，用 snprintf + %f
// 链接时必须加 -u _printf_float 和 -lm
// 如果没有浮点需求，定义这个宏可以省 FLASH：
// #define printf_float(...)
```

---

## 5. 最小测试代码

```c
#include <stdio.h>

int __io_putchar(int ch) {
    HAL_UART_Transmit(&huart1, (uint8_t*)&ch, 1, 100);
    return ch;
}

void test_printf(void) {
    printf("Hello STM32!\r\n");
    printf("Integer: %d\r\n", 42);
    printf("Float:   %.2f\r\n", 3.14159f);
}
```
