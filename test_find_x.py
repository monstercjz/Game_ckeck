import cv2
import numpy as np
from PIL import ImageGrab
import os

# ==========================================================
# --- 1. 配置区 ---
# ==========================================================

# 【请修改】你的模板图片的文件名
TEMPLATE_FILENAME = "template_close_button.png"

# 【请修改】匹配的置信度阈值
CONFIDENCE_THRESHOLD = 0.8

# --- 新增：区域截图配置 ---
# 【请修改】是否只在特定区域进行测试 (True = 是, False = 否/全屏)
ENABLE_AREA_SEARCH = True

# 【请修改】如果上面设置为True, 请在这里指定测试区域的坐标 (左, 上, 右, 下)
# 这个坐标应该和你 config.ini 里的 SuccessSearchAreaBbox 保持一致
SEARCH_AREA_BBOX = (700, 0, 960, 400)

# ==========================================================
# --- 2. 测试逻辑 ---
# ==========================================================

def run_test():
    """
    执行一次查找和可视化测试，现已支持区域截图。
    """
    print("--- 开始测试 ---")
    
    if not os.path.exists(TEMPLATE_FILENAME):
        print(f"[错误] 模板文件 '{TEMPLATE_FILENAME}' 未找到！")
        return

    # --- 核心修改：根据配置选择截图方式 ---
    if ENABLE_AREA_SEARCH:
        print(f"1. 正在截取指定区域: {SEARCH_AREA_BBOX}...")
        try:
            screenshot = ImageGrab.grab(bbox=SEARCH_AREA_BBOX)
            bbox_offset = SEARCH_AREA_BBOX # 记录偏移量，以便后续坐标转换
        except Exception as e:
            print(f"[错误] 截取指定区域时失败: {e}")
            print("请检查 SEARCH_AREA_BBOX 的坐标是否正确。")
            return
    else:
        print("1. 正在截取整个屏幕...")
        screenshot = ImageGrab.grab()
        bbox_offset = (0, 0, 0, 0) # 全屏时，偏移量为0
    
    # 用于显示的彩色原图
    main_image_for_display = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    # 用于匹配的灰度图
    main_image_gray = cv2.cvtColor(main_image_for_display, cv2.COLOR_BGR2GRAY)
    print("   截图完成。")

    print(f"2. 正在加载模板图片 '{TEMPLATE_FILENAME}'...")
    template_image = cv2.imread(TEMPLATE_FILENAME, cv2.IMREAD_GRAYSCALE)
    if template_image is None:
        print(f"[错误] 无法读取模板图片 '{TEMPLATE_FILENAME}'。")
        return
    print("   模板加载完成。")
    
    w, h = template_image.shape[::-1]

    print("3. 正在进行模板匹配运算...")
    result = cv2.matchTemplate(main_image_gray, template_image, cv2.TM_CCOEFF_NORMED)
    print("   运算完成。")

    locations = np.where(result >= CONFIDENCE_THRESHOLD)
    
    rectangles = []
    for pt in zip(*locations[::-1]):
        rectangles.append([int(pt[0]), int(pt[1]), int(w), int(h)])
        
    rects_grouped, _ = cv2.groupRectangles(rectangles, groupThreshold=0, eps=0.5)

    found_count = len(rects_grouped)
    print(f"\n--- 测试结果 ---")
    print(f"在阈值为 {CONFIDENCE_THRESHOLD} 的情况下，共找到 {found_count} 个目标。")

    if found_count > 0:
        print("正在绘制识别结果...")
        for (x, y, w, h) in rects_grouped:
            # 在用于显示的彩色图上画绿框
            cv2.rectangle(main_image_for_display, (x, y), (x + w, y + h), (0, 255, 0), 2)
        print("   绘制完成。")
    else:
        # 如果一个都没找到，我们来看看相似度最高的地方在哪里
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        print(f"虽然没有找到超过阈值的目标，但相似度最高的地方在截图区域内的坐标 {max_loc}，相似度为 {max_val:.4f}")
        # 把它用红色方框画出来
        cv2.rectangle(main_image_for_display, max_loc, (max_loc[0] + w, max_loc[1] + h), (0, 0, 255), 2)
        
    # 5. 显示结果图片
    print("\n即将弹出一个名为 'Test Result' 的窗口显示结果...")
    print("按键盘上的任意键即可关闭窗口并退出程序。")
    
    # 创建一个可调整大小的窗口
    cv2.namedWindow('Test Result', cv2.WINDOW_NORMAL)
    cv2.imshow('Test Result', main_image_for_display)
    
    cv2.waitKey(0)
    cv2.destroyAllWindows()
    print("--- 测试结束 ---")


# --- 脚本入口 ---
if __name__ == '__main__':
    run_test()