import cv2
import numpy as np
from PIL import ImageGrab
import time
import os
import socket
import configparser
import logging

def setup_logging():
    log_file = 'monitor.log'
    if os.path.exists(log_file) and os.path.getsize(log_file) > 5 * 1024 * 1024:
        os.remove(log_file)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8', mode='a'),
            logging.StreamHandler()
        ]
    )

def load_config(config_path='config.ini'):
    config = configparser.ConfigParser()
    if not config.read(config_path, encoding='utf-8'):
        raise FileNotFoundError(f"配置文件 '{config_path}' 未找到！")
    cfg = config['Settings']
    bbox = None
    if cfg.getboolean('EnableSearchArea'):
        try:
            bbox_str = cfg.get('SearchAreaBbox')
            bbox = tuple(map(int, bbox_str.split(',')))
            if len(bbox) != 4: raise ValueError("Bbox 必须是4个整数。")
        except Exception as e:
            raise ValueError(f"SearchAreaBbox 格式错误: {e}")
    return {
        'template_name': cfg.get('TemplateImageName'), 'threshold': cfg.getfloat('ConfidenceThreshold'),
        'alert_path': cfg.get('AlertSharePath'), 'enable_area': cfg.getboolean('EnableSearchArea'),
        'search_bbox': bbox
    }

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        try: return socket.gethostbyname(socket.gethostname())
        except Exception: return "Unknown_IP"

def find_template_on_screen(config):
    template_path = config['template_name']
    if not os.path.exists(template_path):
        logging.error(f"模板文件 '{template_path}' 不存在。")
        return False, "模板文件不存在"
    try:
        logging.info(f"开始屏幕查找 (模板: {template_path}, 区域搜索: {config['enable_area']})...")
        screenshot = ImageGrab.grab(bbox=config['search_bbox'])
        main_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        template_image = cv2.imread(template_path)
        if template_image is None:
            logging.error(f"无法读取模板图片 '{template_path}'。")
            return False, "无法读取模板图片"
        result = cv2.matchTemplate(main_image, template_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        logging.info(f"模板匹配完成，最大相似度: {max_val:.4f} (阈值: {config['threshold']})")
        if max_val >= config['threshold']:
            return True, f"匹配度 {max_val:.2f}"
        else:
            return False, f"匹配度 {max_val:.2f}"
    except Exception as e:
        logging.error(f"图像处理异常: {e}")
        return False, f"图像处理异常: {e}"

def main():
    setup_logging()
    logging.info("================== 脚本启动 ==================")
    try:
        config = load_config()
    except Exception as e:
        logging.error(f"无法加载配置: {e}"); logging.info("================== 脚本异常退出 ==================\n"); return

    local_ip = get_local_ip()
    alert_filename = f"{local_ip}_VISUAL_HISTORY.log" # 文件名改为.log，更符合日志的身份
    alert_filepath = os.path.join(config['alert_path'], alert_filename)

    max_retries = 3
    for i in range(max_retries):
        if os.path.exists(config['alert_path']): break
        logging.warning(f"无法访问网络路径 '{config['alert_path']}', 5秒后重试... ({i+1}/{max_retries})")
        time.sleep(5)
    else:
        logging.error("致命错误: 无法访问网络共享路径！"); logging.info("================== 脚本异常退出 ==================\n"); return

    is_found, reason = find_template_on_screen(config)

    if is_found:
        logging.warning(f"检测到异常界面 ({reason})。正在追加告警日志...")
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        alert_message = f"[{timestamp}] - Computer: {os.getenv('COMPUTERNAME')} (IP: {local_ip}) - 检测到异常界面 ({reason})."
        try:
            # 这里是关键修改：使用 'a' 模式来追加内容
            with open(alert_filepath, 'a', encoding='utf-8') as f:
                f.write(alert_message + "\n")
            logging.info(f"新的告警已成功追加到日志文件: {alert_filepath}")
        except Exception as e:
            logging.error(f"追加告警日志时失败: {e}")
    else:
        logging.info("未发现异常界面，状态正常。")
        # 由于是日志模式，我们不再删除文件，所以这部分逻辑被移除了。

    logging.info("================== 脚本正常结束 ==================\n")

if __name__ == '__main__':
    main()