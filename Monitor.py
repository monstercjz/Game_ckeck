import cv2
import numpy as np
from PIL import ImageGrab
import time
import os
import socket
import configparser
import logging
import pyautogui # 导入用于控制鼠标的库

def setup_logging():
    """
    配置日志系统。
    日志会同时输出到 monitor.log 文件和控制台。
    文件模式为 'a' (append)，每次运行会追加日志，而不是覆盖。
    同时会检查日志文件大小，防止无限增大。
    """
    log_file = 'monitor.log'
    # 检查日志文件大小，如果超过5MB，则清空（或可改为归档）
    try:
        if os.path.exists(log_file) and os.path.getsize(log_file) > 5 * 1024 * 1024:
            os.remove(log_file)
    except OSError as e:
        print(f"无法处理日志文件: {e}")

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

        # 获取模板的宽度和高度，用于计算中心点
        h, w = template_image.shape[:2]

        result = cv2.matchTemplate(main_image, template_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        logging.info(f"模板匹配完成，最大相似度: {max_val:.4f} (阈值: {config['threshold']})")

        if max_val >= config['threshold']:
            # 计算找到区域的中心点坐标
            center_x = max_loc[0] + w // 2
            center_y = max_loc[1] + h // 2
            
            # 如果是区域截图，需要将坐标转换回全屏坐标
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
    """主执行函数，程序的入口点。"""
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

    is_found, reason, location = find_template_on_screen(config)

    if is_found:
        logging.warning(f"检测到异常界面 ({reason})。")
        
        # 写入追加模式的日志文件
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        alert_message = f"[{timestamp}] - Computer: {os.getenv('COMPUTERNAME')} (IP: {local_ip}) - 检测到异常界面 ({reason})."
        try:
            with open(alert_filepath, 'a', encoding='utf-8') as f:
                f.write(alert_message + "\n")
            logging.info(f"新的告警已成功追加到日志文件: {alert_filepath}")
        except Exception as e:
            logging.error(f"追加告警日志时失败: {e}")

        # 执行自动点击操作
        if config.get('enable_click', False) and location:
            try:
                # 计算最终要点击的坐标 (中心点 + 偏移量)
                click_x = location[0] + config.get('click_offset_x', 0)
                click_y = location[1] + config.get('click_offset_y', 0)
                
                logging.info(f"检测到点击已启用。准备在坐标 ({click_x}, {click_y}) 执行点击。")
                pyautogui.click(click_x, click_y)
                logging.info("点击操作已成功执行。")
            except Exception as e:
                logging.error(f"执行点击操作时失败: {e}")
    else:
        logging.info("未发现异常界面，状态正常。")

    logging.info("================== 脚本正常结束 ==================\n")

if __name__ == '__main__':
    main()