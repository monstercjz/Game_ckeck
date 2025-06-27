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
    # 新增: 'savestuckscreenshot' 加入布尔类型配置
    bool_keys = ['enableclick', 'enablestuckareasearch', 'enablesuccessareasearch', 'savestuckscreenshot']

    for key in int_keys:
        cfg[key] = int(cfg.get(key, 0))
    for key in float_keys:
        cfg[key] = float(cfg.get(key, 0.0))
    for key in bool_keys:
        cfg[key] = cfg.get(key, 'false').lower() in ('true', '1', 'yes')

    # 新增: 解析字符串路径
    cfg['screenshotsavepath'] = cfg.get('screenshotsavepath', 'screenshots')

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

def find_stuck_template(template_path, threshold, bbox=None, config=None):
    """
    【重量级操作】专门用于寻找单个“卡住”模板。
    使用彩色图像匹配，返回 (是否找到, 第一个匹配项的中心点坐标)。
    如果配置中启用，当找到模板时会保存截图。
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
            # 新增: 当找到模板时，根据配置保存截图
            if config and config.get('savestuckscreenshot'):
                save_path = config.get('screenshotsavepath', 'screenshots')
                try:
                    os.makedirs(save_path, exist_ok=True)
                    timestamp = time.strftime('%Y%m%d_%H%M%S')
                    filename = os.path.join(save_path, f"stuck_snapshot_{timestamp}.png")
                    screenshot.save(filename)
                    logging.info(f"已将'卡住'状态的截图保存至: {filename}")
                except Exception as e:
                    logging.error(f"保存'卡住'截图时失败: {e}")

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
        # 修改: 传递完整的 config 字典
        is_stuck, stuck_location = find_stuck_template(
            config['templatestuckimagename'], 
            config['stucktemplatethreshold'], 
            config.get('stucksearchareabbox'),
            config=config
        )
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