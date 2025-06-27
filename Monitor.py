import cv2
import numpy as np
from PIL import ImageGrab
import time
import os
import socket
import configparser
import logging

def setup_logging():
    """
    配置日志系统。
    日志会同时输出到 monitor.log 文件和控制台。
    文件模式为 'a' (append)，每次运行会追加日志，而不是覆盖。
    """
    # 检查日志文件大小，如果过大可以考虑归档或删除
    log_file = 'monitor.log'
    if os.path.exists(log_file) and os.path.getsize(log_file) > 5 * 1024 * 1024: # 大于5MB
        os.remove(log_file) # 简单处理：直接删除

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
    从指定的 .ini 文件加载配置。
    如果文件不存在或读取失败，会抛出异常。
    """
    config = configparser.ConfigParser()
    if not config.read(config_path, encoding='utf-8'):
        raise FileNotFoundError(f"配置文件 '{config_path}' 未找到！请确保它和脚本在同一个目录下。")
    
    cfg = config['Settings']
    
    # 解析区域截图的坐标
    bbox = None
    if cfg.getboolean('EnableSearchArea'):
        try:
            bbox_str = cfg.get('SearchAreaBbox')
            bbox = tuple(map(int, bbox_str.split(',')))
            if len(bbox) != 4:
                raise ValueError("SearchAreaBbox 必须包含4个由逗号分隔的整数。")
        except ValueError as e:
            raise ValueError(f"配置文件中的 SearchAreaBbox 格式错误: {e}")
            
    return {
        'template_name': cfg.get('TemplateImageName'),
        'threshold': cfg.getfloat('ConfidenceThreshold'),
        'alert_path': cfg.get('AlertSharePath'),
        'enable_area': cfg.getboolean('EnableSearchArea'),
        'search_bbox': bbox
    }

def get_local_ip():
    """获取本机IPv4地址，优先使用外网连接，失败则尝试内网主机名解析。"""
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
    在屏幕上（全屏或指定区域）查找模板图片。
    返回一个元组: (是否找到: bool, 原因/详情: str)
    """
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
            logging.error(f"无法读取模板图片 '{template_path}'，文件可能已损坏或格式不支持。")
            return False, "无法读取模板图片"

        result = cv2.matchTemplate(main_image, template_image, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)

        logging.info(f"模板匹配完成，最大相似度: {max_val:.4f} (阈值: {config['threshold']})")

        if max_val >= config['threshold']:
            return True, f"匹配度 {max_val:.2f}"
        else:
            return False, f"匹配度 {max_val:.2f}"
            
    except Exception as e:
        logging.error(f"图像处理过程中发生异常: {e}")
        return False, f"图像处理异常: {e}"

def main():
    """主执行函数，程序的入口点。"""
    setup_logging()
    logging.info("================== 脚本启动 ==================")
    
    try:
        config = load_config()
    except Exception as e:
        logging.error(f"无法加载配置，脚本终止: {e}")
        logging.info("================== 脚本异常退出 ==================\n")
        return

    local_ip = get_local_ip()
    alert_filename = f"{local_ip}_VISUAL_ALERT.txt"
    alert_filepath = os.path.join(config['alert_path'], alert_filename)
    
    # 检查网络路径，带重试机制
    max_retries = 3
    for i in range(max_retries):
        if os.path.exists(config['alert_path']):
            break
        logging.warning(f"无法访问网络路径 '{config['alert_path']}', 5秒后重试... ({i+1}/{max_retries})")
        time.sleep(5)
    else: # for循环正常结束（即重试都失败）
        logging.error("致命错误: 多次重试后仍无法访问网络共享路径！脚本终止。")
        logging.info("================== 脚本异常退出 ==================\n")
        return

    is_found, reason = find_template_on_screen(config)

    if is_found:
        logging.warning(f"检测到异常界面 ({reason})。正在创建/更新告警文件...")
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        alert_message = f"[{timestamp}] - Computer: {os.getenv('COMPUTERNAME')} (IP: {local_ip}) - 检测到异常界面 ({reason})."
        try:
            with open(alert_filepath, 'w', encoding='utf-8') as f:
                f.write(alert_message)
            logging.info(f"告警文件已成功创建/更新: {alert_filepath}")
        except Exception as e:
            logging.error(f"写入告警文件时失败: {e}")
    else:
        logging.info("未发现异常界面，状态正常。")
        if os.path.exists(alert_filepath):
            try:
                os.remove(alert_filepath)
                logging.info(f"旧的告警文件已成功删除: {alert_filepath}")
            except Exception as e:
                logging.error(f"删除旧告警文件时失败: {e}")

    logging.info("================== 脚本正常结束 ==================\n")

if __name__ == '__main__':
    main()