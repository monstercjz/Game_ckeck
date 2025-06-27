## 标题：高级工程师任务执行规则
### 适用范围：所有任务
### 规则说明：
你是一位经验丰富的高级软件工程师，专注于编写高质量、生产可用的代码。擅长在不引入副作用的前提下，完成精准的函数级变更、模块集成与缺陷修复。
在执行任何任务时，必须严格遵守以下流程规范，不得跳过或简化任一步骤。：
- 1.先明确任务范围
在编写任何代码之前，必须先明确任务的处理方式。确认你对任务目标的理解无误。
撰写一份清晰的计划，说明将会涉及哪些函数、模块或组件，并解释原因。未完成以上步骤并合理推理之前，禁止开始编码。
- 2.找到精确的代码插入点
明确指出变更应落地到哪个文件的哪一行。严禁对无关文件进行大范围修改。
如需涉及多个文件，必须逐一说明每个文件的必要性。除非任务明确要求，否则不得新增抽象、重构已有结构。
- 3.仅做最小且封闭的更改
只编写为满足任务而必须实现的代码。
严禁任何“顺便”性质的修改或推测性变动。
所有逻辑必须做到隔离，确保不影响已有流程。
- 4.全面复查每一项变更
检查代码是否正确、符合任务范围，避免副作用。
保证代码风格与现有代码保持一致，防止引入回归问题。明确确认此改动是否会影响到下游流程。
- 5.清晰交付成果
做好代码变更的版本日志，做好新增及变化代码相应的注释，严禁随意删除已有注释。
总结变更内容及其原因。
列出所有被修改的文件及每个文件的具体改动。如果有任何假设或风险，请明确标注以供评审。
最终提交的代码应该是涉及到代码变更的整个函数块，禁止提供有折叠的不完整代码块。
### 提醒：
你不是副驾驶、助手或头脑风暴的参与者。你是负责高杠杆、生产安全级变更的高级工程师。请勿即兴设计或偏离规范。

## 目前代码
```python
# -*- coding: utf-8 -*-
"""
游戏多开状态监控与自动纠正工具

功能:
1. 轻量级轮询监控指定进程数量。
2. 当进程数异常时，进入重量级诊断模式。
3. 在诊断模式中，通过图像识别“卡住”界面，并自动点击尝试修复。
4. 诊断模式的最终目标是让系统恢复到“进程数达标”且“屏幕内容达标”的健康状态。
5. 所有操作和决策均有详细日志记录。
6. 所有参数均可通过 config.ini 文件进行配置。
"""

import cv2
import numpy as np
from PIL import ImageGrab
import time
import os
import socket
import configparser
import logging
import pyautogui

# --- 全局常量定义 ---
CONFIG_FILE = 'config.ini'
LOG_FILE = 'monitor.log'
LOG_MAX_SIZE_MB = 5  # 日志文件最大体积（MB）

# ==============================================================================
# --- 1. 初始化与配置模块 ---
# ==============================================================================

def setup_logging():
    """
    配置日志系统。
    - 日志级别: INFO
    - 格式: 时间 - 级别 - 消息
    - 输出: 同时输出到控制台和 LOG_FILE
    - 日志滚动: 当日志文件超过 LOG_MAX_SIZE_MB 时，清空文件。
    """
    log_max_bytes = LOG_MAX_SIZE_MB * 1024 * 1024
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > log_max_bytes:
            os.remove(LOG_FILE)
            print(f"提示: 日志文件 '{LOG_FILE}' 已超过 {LOG_MAX_SIZE_MB}MB，已清空。")
    except OSError as e:
        print(f"提示: 无法处理日志文件 '{LOG_FILE}': {e}")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'),
            logging.StreamHandler()
        ]
    )

def load_config(config_path=CONFIG_FILE):
    """
    从指定的 .ini 文件加载所有配置，并进行类型转换。
    强制将所有配置项的键名转换为小写，以避免因大小写不一致导致错误。

    Args:
        config_path (str): 配置文件的路径。

    Returns:
        dict: 包含所有配置项的字典。

    Raises:
        FileNotFoundError: 如果配置文件不存在。
        ValueError: 如果配置项格式不正确。
    """
    config = configparser.ConfigParser()
    if not config.read(config_path, encoding='utf-8'):
        raise FileNotFoundError(f"配置文件 '{config_path}' 未找到！")
    
    raw_cfg = {}
    if 'Settings' in config:
        raw_cfg.update(config['Settings'].items())
    if 'ClickAction' in config:
        raw_cfg.update(config['ClickAction'].items())
        
    cfg = {k.lower(): v for k, v in raw_cfg.items()}

    # 类型转换，带默认值以增加健壮性
    int_keys = ['requiredprocesscount', 'requiredsuccesscount', 'loopinterval', 'timeoutseconds', 'clickoffsetx', 'clickoffsety', 'clickretrydelay']
    float_keys = ['stucktemplatethreshold', 'successtemplatethreshold']
    bool_keys = ['enableclick', 'enablestuckareasearch', 'enablesuccessareasearch']

    for key in int_keys:
        cfg[key] = int(cfg.get(key, 0))
    for key in float_keys:
        cfg[key] = float(cfg.get(key, 0.0))
    for key in bool_keys:
        cfg[key] = cfg.get(key, 'false').lower() in ('true', '1', 'yes')

    # 解析区域截图坐标
    for area_type in ['stuck', 'success']:
        enable_key = f'enable{area_type}areasearch'
        bbox_key = f'{area_type}searchareabbox'
        if cfg.get(enable_key):
            try:
                bbox_str = cfg.get(bbox_key, '0,0,0,0')
                cfg[bbox_key] = tuple(map(int, bbox_str.split(',')))
            except ValueError:
                logging.warning(f"配置项 '{bbox_key}' 格式错误，将对 {area_type} 模板使用全屏搜索。")
                cfg[bbox_key] = None
        else:
            cfg[bbox_key] = None
            
    return cfg

# ==============================================================================
# --- 2. 系统与图像识别核心功能模块 ---
# ==============================================================================

def get_local_ip():
    """获取本机IPv4地址，提供多种回退机制。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            return "127.0.0.1" # 最终回退

def get_process_count(process_name):
    """【轻量级操作】获取指定名称的进程数量。"""
    if not process_name:
        return 0
    try:
        command = f'tasklist /FI "IMAGENAME eq {process_name}"'
        output = os.popen(command).read()
        return output.count(process_name)
    except Exception as e:
        logging.error(f"检查进程数时出错: {e}")
        return -1  # -1 表示检查失败

def find_stuck_template(template_path, threshold, bbox=None):
    """
    【重量级操作】专门用于寻找单个“卡住”模板。
    使用彩色图像匹配，返回 (是否找到, 第一个匹配项的中心点坐标)。
    """
    try:
        if not os.path.exists(template_path): return False, None
        
        screenshot = ImageGrab.grab(bbox=bbox)
        main_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        template_image = cv2.imread(template_path)
        
        if template_image is None: logging.error(f"无法读取模板 '{template_path}'"); return False, None
        
        h, w = template_image.shape[:2]
        res = cv2.matchTemplate(main_image, template_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        logging.info(f"查找'卡住'模板: 最大相似度 {max_val:.4f} (阈值: {threshold})")

        if max_val >= threshold:
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            if bbox:
                center_x += bbox[0]
                center_y += bbox[1]
            return True, (center_x, center_y)
        return False, None
    except Exception as e:
        logging.error(f"查找'卡住'模板时出错: {e}"); return False, None

def count_success_templates(template_path, threshold, bbox=None):
    """
    【重量级操作】专门用于计数多个“成功”模板 (如'X'按钮)。
    使用灰度图和去重逻辑，返回找到的数量。
    """
    try:
        if not os.path.exists(template_path): return 0
        
        screenshot = ImageGrab.grab(bbox=bbox)
        main_image_gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_BGR2GRAY)
        template_image_gray = cv2.imread(template_path, cv2.IMREAD_GRAYSCALE)
        
        if template_image_gray is None: logging.error(f"无法读取模板 '{template_path}'"); return 0
        
        w, h = template_image_gray.shape[::-1]
        res = cv2.matchTemplate(main_image_gray, template_image_gray, cv2.TM_CCOEFF_NORMED)
        
        loc = np.where(res >= threshold)
        rects = [[int(pt[0]), int(pt[1]), int(w), int(h)] for pt in zip(*loc[::-1])]
        
        # 过滤重叠的矩形框，groupThreshold=0表示单个框也能被保留
        rects_grouped, _ = cv2.groupRectangles(rects, groupThreshold=0, eps=0.5)
        
        return len(rects_grouped)
    except Exception as e:
        logging.error(f"计数'成功'模板时出错: {e}"); return 0

# ==============================================================================
# --- 3. 诊断与操作逻辑模块 ---
# ==============================================================================

def handle_alert_state(config):
    """
    【重量级诊断与纠正】
    此函数全权负责将系统从任何异常状态恢复到最终的健康状态。
    只有在成功恢复或超时后，它才会返回。
    """
    local_ip = get_local_ip()
    alert_filepath = os.path.join(config['alertsharepath'], f"{local_ip}_VISUAL_HISTORY.log")
    
    logging.info("--- 已进入重量级诊断与纠正流程 ---")
    start_time = time.time()
    timeout_seconds = config.get('timeoutseconds', 300)

    # 记录进入诊断状态的日志
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    alert_message = f"[{timestamp}] - IP: {local_ip} - 系统状态异常，开始自动纠正流程。"
    try:
        with open(alert_filepath, 'a', encoding='utf-8') as f:
            f.write(alert_message + "\n")
    except Exception as e:
        logging.error(f"写入初始诊断日志时失败: {e}")

    while time.time() - start_time < timeout_seconds:
        # 1. 检查是否已达到最终健康状态
        proc_count = get_process_count(config['processname'])
        success_icon_count = count_success_templates(config['templatesuccessimagename'], config['successtemplatethreshold'], config.get('successsearchareabbox'))
        
        logging.info(f"诊断中 - 进程数: {proc_count}/{config['requiredprocesscount']}, 成功标志: {success_icon_count}/{config['requiredsuccesscount']}")
        
        if proc_count == config['requiredprocesscount'] and success_icon_count >= config['requiredsuccesscount']:
            logging.info("成功！诊断中发现系统已完全恢复健康，退出诊断流程。")
            return

        # 2. 如果未恢复，则寻找“卡住”模板并尝试点击
        is_stuck, stuck_location = find_stuck_template(config['templatestuckimagename'], config['stucktemplatethreshold'], config.get('stucksearchareabbox'))
        if is_stuck:
            logging.warning("诊断中发现'卡住'标志，准备点击。")
            if config.get('enableclick', False) and stuck_location:
                try:
                    click_x = stuck_location[0] + config.get('clickoffsetx', 0)
                    click_y = stuck_location[1] + config.get('clickoffsety', 0)
                    logging.info(f"在坐标 ({click_x}, {click_y}) 执行点击。")
                    pyautogui.click(click_x, click_y)
                except Exception as e:
                    logging.error(f"执行点击时失败: {e}")
            
            logging.info(f"等待 {config['clickretrydelay']} 秒后再次检查...")
            time.sleep(config['clickretrydelay'])
        else:
            logging.info("未找到已知'卡住'标志，等待5秒观察变化...")
            time.sleep(5)
    
    # 3. 如果循环是因为超时而结束
    logging.error(f"诊断超时（{timeout_seconds}秒），未能解决问题。")
    final_fail_message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] - IP: {local_ip} - 自动纠正超时，问题仍未解决。"
    try:
        with open(alert_filepath, 'a', encoding='utf-8') as f:
            f.write(final_fail_message + "\n")
    except Exception as e:
        logging.error(f"写入超时日志时失败: {e}")

# ==============================================================================
# --- 4. 主程序入口与循环 ---
# ==============================================================================

def main_loop():
    """
    主循环，程序的总指挥。
    逻辑已简化：只负责“放哨”，如果发现不健康，则无条件调用专家函数 `handle_alert_state`。
    """
    setup_logging()
    try:
        config = load_config()
    except Exception as e:
        logging.error(f"启动失败: 无法加载或解析配置 - {e}")
        return
    
    logging.info("监控程序已启动，进入主循环...")
    
    while True:
        try:
            # 1. 轻量级检查：只检查进程数
            proc_count = get_process_count(config['processname'])
            
            # 2. 判断是否需要深入检查
            if proc_count == config['requiredprocesscount']:
                logging.info(f"状态正常 (进程数: {proc_count})。")
            else:
                logging.warning(f"状态异常 (进程数: {proc_count})，启动完整的诊断和纠正流程...")
                handle_alert_state(config)
            
            # 3. 主循环休眠
            logging.info(f"--- 本轮结束，休眠 {config['loopinterval']} 秒 ---\n")
            time.sleep(config['loopinterval'])

        except KeyboardInterrupt:
            logging.info("脚本被用户手动中断 (Ctrl+C)，正在退出...")
            break
        except Exception as e:
            # 捕获主循环中的未知错误，防止整个程序因意外崩溃
            logging.error(f"主循环中发生严重错误: {e}")
            logging.info(f"将休眠 {config.get('loopinterval', 60)} 秒后重试...")
            time.sleep(config.get('loopinterval', 60))

if __name__ == '__main__':
    main_loop()
```
```config.ini
[Settings]
# =================================================
# --- 基本监控目标配置 ---
# =================================================

# 【必需】要监控的游戏进程名，必须带 .exe 后缀
ProcessName = Game.exe

# 【必需】健康状态下，应有的进程数量
RequiredProcessCount = 6


# =================================================
# --- 状态模板配置 ---
# =================================================

# 【必需】用于识别“卡住/掉线”状态的模板图片文件名
TemplateStuckImageName = template_stuck.png

# “卡住”模板的匹配阈值 (0.0到1.0的小数)。值越高越严格。建议 0.8
StuckTemplateThreshold = 0.8

# 【必需】用于识别“成功/健康”状态的模板图片文件名 (例如关闭按钮X的图标)
TemplateSuccessImageName = template_close_button.png

# “成功”模板的匹配阈值。图标类模板通常可以设置得更高以求精确。建议 0.8 或 0.9
SuccessTemplateThreshold = 0.8

# 【必需】屏幕上应找到多少个“成功”模板才算真正恢复正常
RequiredSuccessCount = 6


# =================================================
# --- 循环与超时控制 ---
# =================================================

# 【必需】网络共享文件夹的路径，用于存放告警日志文件
AlertSharePath = \\192.168.3.3\002 云主机游戏必备\info

# 主循环的间隔时间（秒）。即每隔多少秒进行一次轻量级的进程数检查。
LoopInterval = 30

# 在“重量级诊断”模式下的总超时时间（秒）。超过这个时间未能解决问题，则放弃本次纠正。
TimeoutSeconds = 300


# =================================================
# --- 高级性能与区域选项 ---
# =================================================

# 是否为“卡住”模板启用区域搜索 (1 = 开启, 0 = 关闭)。
# 如果卡住的界面位置固定，开启此项可提升性能。
EnableStuckAreaSearch = 0

# 如果开启，请设置“卡住”模板的搜索区域 (左, 上, 右, 下)。
StuckSearchAreaBbox = 0,0,1920,1080

# 是否为“成功X”模板启用区域搜索 (1 = 开启, 0 = 关闭)。
# 【强烈建议开启】以排除屏幕其他区域的干扰。
EnableSuccessAreaSearch = 1

# 如果开启，请设置“成功X”模板的搜索区域 (左, 上, 右, 下)。
# 使用 test_find_x.py 脚本来帮助你获取这个值。
SuccessSearchAreaBbox = 700, 0, 960, 400





[ClickAction]
# =================================================
# --- 自动点击操作配置 ---
# =================================================

# 是否在找到“卡住”模板后，执行自动点击操作 (1 = 开启, 0 = 关闭)
EnableClick = 1

# 点击位置的X轴偏移量，相对于找到的“卡住”模板图片的【中心点】
ClickOffsetX = 0

# 点击位置的Y轴偏移量，相对于找到的“卡住”模板图片的【中心点】
ClickOffsetY = 0

# 在诊断模式中，每次点击后，等待多少秒再进行下一次检查，给游戏响应时间。
ClickRetryDelay = 10
```
## 修改方案：
在config里添加一个控制参数，支持当检测到“卡住”模板后，截图保持到目录