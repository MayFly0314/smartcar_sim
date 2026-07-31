# 智能车图像算法仿真器（smartcar-sim）

Windows 上位机：加载本地 BMP 赛道图（总钻风 MT9V03X 188×120 灰度图或已二值化黑白图），在内嵌的 Monaco 编辑器（VSCode 同款内核）里用 **C 语言**写图像处理算法，一键编译运行，把边线、赛道元素识别结果用彩色叠加显示在图像上。支持多帧序列播放——`static` 变量跨帧保持，状态机代码直接仿真。

在仿真器里调好的算法**零修改移植到单片机**：把你的 `.c` 文件和 `csim/port/sim_api.h`（调试函数的空宏实现）拷进 MCU 工程即可。

## 环境要求

- Windows 10/11
- Python 3.10+，包：`PySide6` `Pillow` `numpy`（见 requirements.txt）
- MinGW gcc（默认找 PATH 里的 gcc 或 `C:\MinGW\bin\gcc.exe`）
- 首次使用需获取 Monaco 静态文件：`python tools/fetch_monaco.py`（需要 npm）

## 启动

```powershell
python run.py
```

> 注意：GUI 必须在 PowerShell/CMD 下启动。git-bash/MSYS 环境下 QtWebEngine 渲染进程会因 DLL 解析失败而崩溃。

## 打包成 exe（免装 Python 分发）

```powershell
pip install pyinstaller
python tools/fetch_monaco.py     # 若还没拉过 Monaco
python tools/build_exe.py
```

产物在 `dist/SmartcarSim/`，双击 `SmartcarSim.exe` 即可运行（onedir 模式——整个文件夹一起拷到目标机器，无需装 Python/PySide6）。

> - 目标机器仍需有 MinGW gcc 才能编译 C 代码（这是仿真器的核心，无法内置）。若 gcc 不在 PATH，在设置里指定路径。
> - 首次启动较慢（QtWebEngine 冷启动 + Chromium 初始化，约 15~30 秒），之后正常。
> - 体积约 870MB：其中 anaconda 的 numpy 依赖 mkl（约 400MB）+ QtWebEngine（约 250MB）。想瘦身到约 400MB，在只装 `pyside6 pillow numpy pyinstaller` 的干净 venv 里打包（numpy 会用轻量 OpenBLAS 而非 mkl）。

## 使用流程

1. **打开图像**：`Ctrl+I` 单张 BMP，或 `Ctrl+Shift+I` 打开整个文件夹作为帧序列（自然排序）。8 位灰度图和 1 位二值图都支持（后者自动归一化为 0/255）。
2. **写代码**：左侧编辑器，入口是 `void image_process(uint8_t img[IMG_H][IMG_W])`，每帧调用一次。`img` 可读可写——写回的结果（如二值化后的图）在"处理后"视图查看。**按 F1 随时打开 API 速查**（画点线/日志/颜色/移植说明都在里面）。
3. **运行**：`F5` 编译并运行。编译错误在下方控制台可点击跳转到对应行（红色波浪线标注）。
4. **看结果**：右侧图像区滚轮缩放、拖拽平移；缩放 ≥8 倍显示像素网格；状态栏显示光标下像素坐标和灰度值。"叠加"开关控制绘图显示，"处理后"开关切换原图/算法写回的图。代码里 `sim_plot("name", value)` 记录的变量会出现在图像下方的**监视面板**：每变量一行（当前帧值 + 跨帧曲线），竖线游标即当前帧，点击/拖动曲线跳帧，悬停查看任意帧的值，点"监视"标题可折叠。`sim_tag(x, y, "文本", ...)` 给图上某点附加说明（不遮挡图像）：鼠标悬停该处弹出查看，或看图像下方**"本帧标注"列表**（点击行图上高亮该点）。
5. **序列播放**：下方时间轴上一帧/播放/下一帧/拖动滑块。每次运行从第 0 帧开始，`static` 状态确定性重放。

### 代码保存在哪

- 你打开/保存的 `.c` 文件就在你选的位置（默认首次启动会在 `文档\SmartcarSim\workspace\` 建一份示例）。菜单【文件 → 在资源管理器中打开代码位置】直接跳过去。
- `Ctrl+S` 保存；按 `F5` 运行时也会先自动保存。
- **下次打开软件自动恢复上次编辑的那个文件**——直接接着写即可。
- `Ctrl+N` 新建：从最小模板建一个新 .c 文件（推荐每个算法实验单独建一个文件，如 `edge_scan.c`、`midline.c`，互不干扰）。

### 想用 AI 帮你写？两条路

**内置终端（推荐）**：底部"终端"标签就是一个完整的 PowerShell，工作目录自动落在你的代码文件夹。在里面直接运行 `claude`、`atomcode` 等任何 AI agent——AI 能读到你正在写的 .c 文件、自己改错重试，全过程可见。配合外部编辑模式（下），AI 改完保存，仿真结果自动刷新。终端卡死点右上角"重启终端"。

**外部编辑模式**：菜单【运行 → 外部编辑模式】勾选后：内嵌编辑器变为只读展示，任何程序（VSCode、终端里的 AI agent、记事本都行）修改你的 .c 文件并保存，**仿真器自动重新编译运行**，结果立刻刷新。取消勾选即恢复内嵌编辑。

典型工作流：勾选外部编辑模式 → 切到终端标签 → 运行 `claude` → 告诉它"把左边界的扫线改成从上一行边界位置附近开始搜索" → AI 改完保存 → 右侧图像自动刷新，直接看效果。

## 数据来源：本地图 / 串口图传 / SD 卡

三条路最终都变成一组灰度帧序列，用同一套 F5 编译-运行-叠加流水线跑、确定性回放：

- **本地图**：`Ctrl+I` 单张 / `Ctrl+Shift+I` 文件夹（BMP/PNG，见上）。
- **串口图传**（菜单【连接 → 串口图传】，独立窗口，不堆在主界面）：对接逐飞/山外助手兼容协议，实时收摄像头灰度图。
  - 选端口、波特率（默认 115200，可改到 921600/2M）、协议（山外 4 字节头 `00 FF 01 01` / 逐飞助手 `0xAA` 自描述 / 自定义可配**帧头+帧尾**）、分辨率（默认 188×120）。自定义协议填了帧尾会**校验帧尾**，更抗错位。
  - 连接后窗口里实时预览；**「抓取 N 帧」**把实时流存成帧序列加载到主窗口，按 F5 跑算法、时间轴回放。
  - 勾选**「逐帧在线跑算法叠加」**可边收边跑（在线仿真：车在跑，上位机同步显示算法看到的边线）。
  - 需要 `pip install pyserial`。蓝牙 SPP 在系统里就是个 COM 口，同样走这个对话框。
- **SD 卡读图**（菜单【文件 → 打开 SD 原始数据(raw)】）：把车写在 SD 卡里的多帧连续灰度 raw 读回来。
  - 读卡器插电脑后选那个 `.bin/.raw/.dat` 文件；对话框按文件字节数**猜候选分辨率**（也可手填 W/H 和每帧帧头/帧尾字节数），整除校验实时预览帧数（宽度猜错画面会斜向撕裂，一眼可辨）。
  - 每帧单独存成的 BMP/PNG 直接用【打开图像文件夹】即可，无需走 raw。
- **数据记录方案**（菜单【文件 → 数据记录方案（压缩存图/参数）】，独立设计器窗口）：可视化拼出每帧的 SD 存储布局——帧头 hex + 任意参数（uint8/int16/int32/float 等，填车端变量名）+ 图像（**压缩二值 1bit/像素**（13020B→1628B，写卡阻塞降约 6 倍）/ 原始 8bit / 不存图）。
  - 右侧**实时生成车端 C 函数**，一键复制粘贴进 `image_record.c`，主循环改调它即可；
  - 「按此方案打开记录文件」自动解压图像进时间轴，**参数逐帧显示在监视面板**（名称可在设计器里随时改）；F5 后车端参数以 `rec.` 前缀与 `sim_plot` 曲线并排对比；
  - 帧头搜索自动对齐 HxD 导出起点偏差；方案自动记忆。

### 坐标约定：右下角原点（摄像头倒装）

摄像头倒装的车，图像数据天然以**右下角为 (0,0)**、左上角为 (IMG_W-1, IMG_H-1)，算法直接按此约定写、无需在二值化里翻转。图像区上方两个开关配合：

- **「载入转180°」**：打开本地"正的"赛道图时把数据旋转 180°，使数组符合右下角原点约定（`[0][0]`=图片右下角）。切换时已加载的帧就地翻转并清除旧运行结果。SD 卡/串口来的图本身就是约定坐标，**不要勾**。
- **「旋转显示」**：只把画面转 180° 正着看；数据、叠加边线、鼠标像素读数全部不变（仍是约定坐标）。即传统上位机的"反转图像"功能。

典型组合：本地正图 → 两个都勾；SD/串口图 → 只勾「旋转显示」。两个开关状态均记忆。

## 调试 API（sim_api.h）

```c
sim_draw_point(x, y, SIM_RED);          // 画点（边线）
sim_draw_line(x0, y0, x1, y1, c);       // 线（中线/补线）
sim_draw_rect(x, y, w, h, c);           // 空心矩形（ROI）
sim_draw_circle(cx, cy, r, c);          // 空心圆（环岛）
sim_draw_cross(x, y, size, c);          // 十字标记（角点）
sim_draw_text(x, y, c, "th=%d", th);    // 文本（锚定图像坐标）
sim_log("otsu = %d", th);               // 控制台日志（自动带帧号）
sim_plot("error", err);                 // 数值监视（图像下方面板：值+跨帧曲线）
sim_tag(x, y, "L角点 t=%d", t);         // 位置标注（不画到图上；悬停/列表查看）
sim_trace("进入十字处理");               // 流程节点 → 图像下方"本帧流程"面板
if (SIM_COND(max_length >= 59)) {...}   // 包住 if 条件：面板逐帧显示 ✓/✗ 及条件原文
                                        //（车上展开为条件本身，行为零差异）
sim_frame_index();                      // 当前帧号（仅调试用）
```

颜色常量：`SIM_RED/GREEN/BLUE/YELLOW/CYAN/MAGENTA/ORANGE/PURPLE/WHITE/BLACK`。

printf 风格函数安全格式符：`%d %u %x %s %c %f`（不要用 `%zu/%lld`，Windows msvcrt 不支持——单片机上同样如此，习惯一致）。

## 移植到单片机

1. 把 `csim/port/sim_api.h` 拷进 MCU 工程（和你的算法 .c 同目录）。
2. 把你的算法 `.c` 原样拷入，一个字符都不用改——所有 `sim_*` 调用被空宏吃掉，零体积零开销。
3. 在你的主循环里每帧调用 `image_process(mt9v03x_image)`。

## 测试

```powershell
python -m pytest tests/ --ignore=tests/smoke.py   # 无头单元测试
python -m tests.smoke                              # 无头全链路冒烟
python -m tests.robustness_check                   # 崩溃/死循环/状态机验收
python -m tests.monaco_check                       # Monaco 集成（开窗口）
python -m tests.gui_check                          # GUI 端到端（开窗口）
python -m tests.sequence_check                     # 序列播放验收（开窗口）
```

## 示例资源

- `examples/workspace_demo/image_demo.c` —— 大津二值化 + 双边扫线 + 丢线状态机，开箱即跑
- `examples/tracks/` —— `python tools/gen_track.py` 生成：直道/S 弯/十字 序列 + 单张图
- 逐飞/山外上位机保存的 188×120 摄像头 BMP 可直接拖入使用

## 目录结构

```
smartcar_sim/      Python 包（GUI 外壳）
csim/              C harness：sim_main.c 主循环 / sim_api.c 协议实现 / sim_api.h API
csim/port/         单片机移植版 sim_api.h（空宏）
assets/monaco/     Monaco 静态文件（gitignore，fetch_monaco.py 重建）
tools/             fetch_monaco.py / gen_track.py
examples/          示例代码与赛道
tests/             单元测试 + 验收脚本
```

## 待办（预留）

- 设置对话框（gcc 路径/超时/回放帧率——当前用 QSettings 默认值 188×120）

> 串口/蓝牙实时图传、SD 卡读图已实现，见上文「数据来源」。
