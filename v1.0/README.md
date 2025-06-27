pip install pyinstaller 
pip freeze > requirements.txt
pyinstaller --noconsole --add-data "config.ini;." --add-data "*.png;." monitor.py