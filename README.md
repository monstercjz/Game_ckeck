pip install pyinstaller 
pip freeze > requirements.txt
pyinstaller --noconsole --add-data "config.ini;." --add-data "*.png;." monitor.py
配置文件 (config.ini)：首次运行 .exe 时，它会自动在旁边生成一个 config.ini 文件。您可以直接编辑此文件来调整所有程序参数。

图片模板 (.png)：如果您需要替换或优化任何图像识别模板，只需在 .exe 文件旁边创建一个名为 templates 的文件夹，然后将您的新图片（保持与旧模板相同的文件名）放入其中即可。程序会自动优先使用这些外部图片。
pyinstaller --noconsole --onefile --name Monitor_App --add-data "config.ini;." --add-data "*.png;." Monitor.py
