import cv2
import numpy as np
from PIL import ImageGrab
import time
import os
import socket

# ==========================================================
# --- 1. 用户配置区 ---
# ==========================================================

TEMPLATE_IMAGE_NAME = 'template.png'
CONFIDENCE_THRESHOLD = 0.8
ALERT_SHARE_PATH = r'\\192.168.3.3\002 云主机游戏必备\info'

# ==========================================================
# --- 2. 核心功能区 (添加了大量print用于调试) ---
# ==========================================================

def get_local_ip():
    """获取本机IPv4地址"""
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

def find_template_on_screen(template_path, threshold):
    """在屏幕上查找模板图片，并打印详细过程"""
    print(f"--- 开始屏幕查找 ---")
    print(f"模板文件路径: '{template_path}'")
    
    if not os.path.exists(template_path):
        print(f"[错误] 致命错误：模板文件不存在！请确保 '{template_path}' 和脚本在同一个文件夹里。")
        return False, "模板文件不存在"

    try:
        print("步骤1: 正在进行屏幕截图...")
        screenshot = ImageGrab.grab()
        main_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        print("截图成功。")

        print("步骤2: 正在读取模板图片...")
        template_image = cv2.imread(template_path)
        if template_image is None:
            print(f"[错误] 致命错误：无法读取模板图片 '{template_path}'。文件可能已损坏。")
            return False, "无法读取模板图片"
        print("读取模板成功。")

        print("步骤3: 正在进行模板匹配运算...")
        result = cv2.matchTemplate(main_image, template_image, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        print(f"模板匹配运算完成，最大相似度为: {max_val:.4f}")

        if max_val >= threshold:
            print(f"结果: 找到了！(相似度 {max_val:.4f} >= 阈值 {threshold})")
            return True, f"匹配度 {max_val:.2f}"
        else:
            print(f"结果: 未找到。(相似度 {max_val:.4f} < 阈值 {threshold})")
            return False, f"匹配度 {max_val:.2f}"
    
    except Exception as e:
        print(f"[错误] 致命错误：在图像处理过程中发生异常 - {e}")
        return False, f"图像处理异常: {e}"

def main():
    """主执行函数"""
    print("==================================================")
    print(f"开始执行监控脚本... ({time.strftime('%Y-%m-%d %H:%M:%S')})")
    
    local_ip = get_local_ip()
    print(f"本机IP地址: {local_ip}")
    
    alert_filename = f"{local_ip}_VISUAL_ALERT.txt"
    alert_filepath = os.path.join(ALERT_SHARE_PATH, alert_filename)
    print(f"告警文件路径: {alert_filepath}")
    
    print(f"检查网络共享路径: '{ALERT_SHARE_PATH}'...")
    if not os.path.exists(ALERT_SHARE_PATH):
        print(f"[错误] 致命错误：无法访问网络共享路径！请检查网络和权限。")
        print("脚本已终止。")
        print("==================================================")
        return

    print("网络路径可访问。")

    is_found, reason = find_template_on_screen(TEMPLATE_IMAGE_NAME, CONFIDENCE_THRESHOLD)

    if is_found:
        print("[逻辑判断] 发现异常界面，准备创建告警文件...")
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        alert_message = f"[{timestamp}] - IP: {local_ip} - 检测到异常界面 ({reason})."
        
        try:
            with open(alert_filepath, 'w', encoding='utf-8') as f:
                f.write(alert_message)
            print("告警文件已成功创建/更新。")
        except Exception as e:
            print(f"[错误] 写入告警文件时失败 - {e}")
    else:
        print("[逻辑判断] 未发现异常界面，检查是否需要删除旧的告警文件...")
        if os.path.exists(alert_filepath):
            try:
                os.remove(alert_filepath)
                print("旧的告警文件已成功删除。")
            except Exception as e:
                print(f"[错误] 删除告警文件时失败 - {e}")
        else:
            print("无需操作，没有旧的告警文件。")

    print("脚本执行完毕。")
    print("==================================================")

if __name__ == '__main__':
    main()