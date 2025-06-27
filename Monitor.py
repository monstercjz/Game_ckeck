import cv2
import numpy as np
from PIL import ImageGrab
import time
import os
import socket
import configparser
import logging
import pyautogui

def setup_logging():
    """
    配置日志系统。
    日志会同时输出到 monitor.log 文件和控制台。
    文件模式为 'a' (append)，每次运行会追加日志，而不是覆盖。
    同时会检查日志文件大小，防止无限增大。
    """
    log_file = 'monitor.log'
    try:
        if os.path.exists(log_file) and os.path.getsize(log_file) > 5 * 1024 * 1024: # 大于5MB
            os.remove(log_file)
    except OSError as e:
        # 在某些情况下（如文件被占用），删除可能会失败，打印一个提示即可
        print(f"提示: 无法处理日志文件 '{log_file}': {e}")

    # 使用RotatingFileHandler可以更专业地处理日志滚动，但为了简单，这里用基本配置
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8', mode='a'),
            logging.StreamHandler()
        ]
    )

def load_config(config_path='config.ini'):
    """
    从指定的 .ini 文件加载所有配置，包括常规设置和点击操作设置。
    如果文件或必要配置项不存在，会抛出异常。
    """
    config = configparser.ConfigParser()
    if not config.read(config_path, encoding='utf-8'):
        raise FileNotFoundError(f"配置文件 '{config_path}' 未找到！请确保它和脚本在同一个目录下。")
    
    cfg = {}
    
    # --- 读取 [Settings] 区块 ---
    if 'Settings' not in config:
        raise ValueError("配置文件中缺少 [Settings] 区块。")
    settings_cfg = config['Settings']
    cfg['template_name'] = settings_cfg.get('TemplateImageName')
    cfg['threshold'] = settings_cfg.getfloat('ConfidenceThreshold')
    cfg['alert_path'] = settings_cfg.get('AlertSharePath')
    cfg['enable_area'] = settings_cfg.getboolean('EnableSearchArea')
    
    if cfg['enable_area']:
        try:
            bbox_str = settings_cfg.get('SearchAreaBbox')
            bbox = tuple(map(int, bbox_str.split(',')))
            if len(bbox) != 4:
                raise ValueError("SearchAreaBbox 必须包含4个由逗号分隔的整数 (左, 上, 右, 下)。")
            cfg['search_bbox'] = bbox
        except (ValueError, configparser.NoOptionError) as e:
            raise ValueError(f"配置文件中的 SearchAreaBbox 格式错误或缺失: {e}")
    else:
        cfg['search_bbox'] = None

    # --- 读取 [ClickAction] 区块 ---
    if 'ClickAction' in config:
        click_cfg = config['ClickAction']
        cfg['enable_click'] = click_cfg.getboolean('EnableClick', fallback=False)
        cfg['click_offset_x'] = click_cfg.getint('ClickOffsetX', fallback=0)
        cfg['click_offset_y'] = click_cfg.getint('ClickOffsetY', fallback=0)
        cfg['max_click_retries'] = click_cfg.getint('MaxClickRetries', fallback=3)
        cfg['click_retry_delay'] = click_cfg.getint('ClickRetryDelay', fallback=10)
    else:
        # 如果没有ClickAction区块，则默认禁用点击
        cfg['enable_click'] = False

    return cfg

def get_local_ip():
    """获取本机IPv4地址。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "Unknown_IP"

def find_template_on_screen(config):
    """
    在屏幕上查找模板图片，并返回(是否找到, 原因详情, 找到位置的中心点坐标)。
    """
    template_path = config['template_name']
    
    if not os.path.exists(template_path):
        logging.error(f"模板文件 '{template_path}' 不存在。")
        return False, "模板文件不存在", None

    try:
        logging.info(f"开始屏幕查找 (模板: {template_path}, 区域搜索: {config['enable_area']})...")
        screenshot = ImageGrab.grab(bbox=config['search_bbox'])
        main_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        template_image = cv2.imread(template_path)
        
        if template_image is None:
            logging.error(f"无法读取模板图片 '{template_path}'，文件可能已损坏或格式不支持。")
            return False, "无法读取模板图片", None

        h, w = template_image.shape[:2]

        result = cv2.matchTemplate(main_image, template_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        logging.info(f"模板匹配完成，最大相似度: {max_val:.4f} (阈值: {config['threshold']})")

        if max_val >= config['threshold']:
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            
            if config['search_bbox']:
                center_x += config['search_bbox'][0]
                center_y += config['search_bbox'][1]

            return True, f"匹配度 {max_val:.2f}", (center_x, center_y)
        else:
            return False, f"匹配度 {max_val:.2f}", None
            
    except Exception as e:
        logging.error(f"图像处理过程中发生异常: {e}")
        return False, f"图像处理异常: {e}", None

def main():
    """主执行函数，包含了循环点击和验证的逻辑。"""
    setup_logging()
    logging.info("================== 脚本启动 ==================")
    
    try:
        config = load_config()
    except Exception as e:
        logging.error(f"无法加载或解析配置，脚本终止: {e}")
        logging.info("================== 脚本异常退出 ==================\n")
        return

    local_ip = get_local_ip()
    alert_filename = f"{local_ip}_VISUAL_HISTORY.log"
    alert_filepath = os.path.join(config['alert_path'], alert_filename)

    max_retries = 3
    for i in range(max_retries):
        if os.path.exists(config['alert_path']):
            break
        logging.warning(f"无法访问网络路径 '{config['alert_path']}', 5秒后重试... ({i+1}/{max_retries})")
        time.sleep(5)
    else:
        logging.error("致命错误: 多次重试后仍无法访问网络共享路径！脚本终止。")
        logging.info("================== 脚本异常退出 ==================\n")
        return

    # --- 核心逻辑从这里开始 ---
    is_found, reason, location = find_template_on_screen(config)

    if not is_found:
        logging.info("未发现异常界面，状态正常。")
        logging.info("================== 脚本正常结束 ==================\n")
        return

    # --- 如果程序能走到这里，说明第一次就发现了异常界面 ---
    logging.warning(f"检测到异常界面 ({reason})。")
    
    # 记录第一次发现的日志
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    alert_message = f"[{timestamp}] - Computer: {os.getenv('COMPUTERNAME')} (IP: {local_ip}) - 首次检测到异常界面 ({reason})."
    try:
        with open(alert_filepath, 'a', encoding='utf-8') as f:
            f.write(alert_message + "\n")
        logging.info(f"告警已追加到日志: {alert_filepath}")
    except Exception as e:
        logging.error(f"追加告警日志时失败: {e}")

    # 检查是否禁用了点击，如果禁用则直接结束
    if not config.get('enable_click', False):
        logging.info("点击操作已禁用，脚本结束。")
        logging.info("================== 脚本正常结束 ==================\n")
        return

    # --- 进入循环点击和验证的阶段 ---
    click_attempts = 0
    max_attempts = config.get('max_click_retries', 3)
    
    # 使用一个循环，最多执行 max_attempts 次纠正操作
    while click_attempts < max_attempts:
        click_attempts += 1
        logging.info(f"--- 开始第 {click_attempts}/{max_attempts} 次自动纠正尝试 ---")
        
        # 在每次点击前，都重新获取一次位置，以防万一
        is_still_found, _, current_location = find_template_on_screen(config)
        
        if not is_still_found:
            logging.info("在准备点击前，异常界面已消失。无需操作。")
            break # 异常已自行解决，跳出循环

        if not current_location:
            logging.error("无法获取点击位置，自动纠正终止。")
            break

        # 1. 执行点击
        try:
            click_x = current_location[0] + config.get('click_offset_x', 0)
            click_y = current_location[1] + config.get('click_offset_y', 0)
            logging.info(f"在坐标 ({click_x}, {click_y}) 执行点击。")
            pyautogui.click(click_x, click_y)
            logging.info("点击操作已执行。")
        except Exception as e:
            logging.error(f"执行点击操作时失败: {e}")
            break # 如果点击本身就失败了，没必要继续了
        
        # 2. 等待一段时间，让界面有时间响应
        retry_delay = config.get('click_retry_delay', 10)
        logging.info(f"等待 {retry_delay} 秒后重新检查屏幕...")
        time.sleep(retry_delay)
        
        # 3. 再次检查屏幕，看问题是否已解决
        is_resolved, reason_after_click, _ = find_template_on_screen(config)
        
        if not is_resolved:
            # 成功了！图片消失了
            logging.info("成功！点击后异常界面已消失。自动纠正完成。")
            break # 跳出 while 循环
        else:
            # 失败了，图片还在
            logging.warning(f"点击后异常界面依然存在 ({reason_after_click})。")
            if click_attempts >= max_attempts:
                logging.error(f"已达到最大重试次数 ({max_attempts}次)，自动纠正失败。")
                # 记录最终失败的日志
                final_fail_message = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] - 经过 {max_attempts} 次点击后，异常界面仍未解决。"
                try:
                    with open(alert_filepath, 'a', encoding='utf-8') as f:
                        f.write(final_fail_message + "\n")
                except Exception as e:
                    logging.error(f"写入最终失败日志时出错: {e}")
    
    logging.info("================== 脚本正常结束 ==================\n")

if __name__ == '__main__':
    main()