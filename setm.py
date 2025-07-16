import os
import sys
import subprocess
import json
import platform
import re
import requests
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QFileDialog, QProgressBar,
    QMessageBox, QGroupBox, QTextEdit
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon
import configparser

# 获取视频时长
def get_video_duration(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


# 获取视频码率
def get_video_bitrate(video_path):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0", # v:0 表示第一个视频流
        "-show_entries", "stream=bit_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        bitrate = result.stdout.strip()
        if bitrate and bitrate.isdigit() and int(bitrate) > 0:
            return bitrate  # 返回的是一个字符串，例如 "3403000"
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"无法获取视频流码率: {e}")

    print("[INFO] 无法获取特定视频流的码率，尝试获取容器的平均码率作为备用。")
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=bit_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        bitrate = result.stdout.strip()
        if bitrate and bitrate.isdigit() and int(bitrate) > 0:
            return bitrate
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
         print(f"无法获取容器平均码率: {e}")
    
    return None # 如果两种方法都失败，则返回None

# 打开文件夹
def open_folder(path):
    folder = os.path.dirname(path)
    if platform.system() == "Windows":
        os.startfile(folder)
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", folder])
    else:
        subprocess.Popen(["xdg-open", folder])

# DeepSeek翻译
def translate_text_deepseek(text, api_key):
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个翻译助手，将输入的英文或日文翻译为简体中文。直接翻译即可，不要做任何解释。"},
            {"role": "user", "content": text}
        ],
        "temperature": 0.2
    }
    response = requests.post(url, headers=headers, json=data, timeout=60)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


# 翻译SRT
def translate_srt_file(input_srt, output_srt, api_key, log_signal=None):
    with open(input_srt, "r", encoding="utf-8") as f:
        lines = f.readlines()

    result_lines = []
    buffer = []
    for line in lines:
        if re.match(r"^\d+$", line.strip()):
            if buffer:
                result_lines.extend(buffer)
                buffer = []
            result_lines.append(line)
        elif "-->" in line:
            result_lines.append(line)
        elif line.strip() == "":
            if buffer:
                original_text = " ".join([l.strip() for l in buffer])
                if log_signal:
                    print(f"[DEBUG] log_signal type: {type(log_signal)}")  
                    log_signal.emit(f"[INFO] 翻译: {original_text}")
                translated = translate_text_deepseek(original_text, api_key)
                translated_lines = translated.split("\n")
                for t in translated_lines:
                    result_lines.append(t.strip() + "\n")
                buffer = []
            result_lines.append(line)
        else:
            buffer.append(line)

    if buffer:
        original_text = " ".join([l.strip() for l in buffer])
        if log_signal:
            print(f"[DEBUG] log_signal type: {type(log_signal)}")  
            log_signal.emit(f"[INFO] 翻译: {original_text}")
        translated = translate_text_deepseek(original_text, api_key)
        translated_lines = translated.split("\n")
        for t in translated_lines:
            result_lines.append(t.strip() + "\n")

    with open(output_srt, "w", encoding="utf-8") as f:
        f.writelines(result_lines)

# 一键线程
class ProcessThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, video_path, language, model_size, api_key):
        super().__init__()
        self.video_path = video_path
        self.language = language
        self.model_size = model_size
        self.api_key = api_key
        self.is_running = True

    def run(self):
            try:
                base_path = os.path.splitext(self.video_path)[0]
                srt_path = f"{base_path}.srt"
                translated_srt = f"{base_path}_zh.srt"
                output_video = f"{base_path}_C.mp4"
    
                # 提取字幕
                self.log_signal.emit("[INFO] 开始提取字幕")
                cmd_whisper = [
                    "whisper", self.video_path, "--model", self.model_size, "--language", self.language,
                    "--output_format", "srt", "--output_dir", os.path.dirname(self.video_path)
                ]
                self.log_signal.emit(f"[DEBUG] {cmd_whisper}")
                process = subprocess.Popen(cmd_whisper, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
                for line in process.stdout:
                    if not self.is_running:
                        process.terminate()
                        self.log_signal.emit("[INFO] 用户中止")
                        return
                    self.log_signal.emit(line.strip())
                process.wait()
                if process.returncode != 0:
                    raise RuntimeError("字幕提取失败")
    
                # 翻译
                self.log_signal.emit("[INFO] 开始翻译字幕")
                translate_srt_file(srt_path, translated_srt, self.api_key, log_signal=self.log_signal)
    
                self.log_signal.emit("[INFO] 开始合成字幕到视频")
                
                # 1. 自动检测原始视频码率
                self.log_signal.emit("[INFO] 正在检测原始视频码率...")
                original_bitrate = get_video_bitrate(self.video_path)
    
                # 准备字幕滤镜字符串
                absolute_srt_path = os.path.abspath(translated_srt)
                escaped_srt_path = absolute_srt_path.replace('\\', '/')
                if platform.system() == "Windows":
                    if re.match(r'^[a-zA-Z]:/', escaped_srt_path):
                        escaped_srt_path = escaped_srt_path.replace(':', '\\:', 1)
                filter_string = f"subtitles='{escaped_srt_path}'"
    
                # 2. 根据是否成功检测到码率，来决定编码参数
                if original_bitrate:
                    self.log_signal.emit(f"[INFO] 检测到码率: {original_bitrate} bps. 将使用此码率进行编码。")
                    cmd_ffmpeg = [
                        "ffmpeg",
                        "-i", self.video_path,
                        "-vf", filter_string,
                        "-c:v", "libx264",
                        "-preset", "medium",
                        "-b:v", original_bitrate,  # <-- 使用检测到的原始码率
                        "-c:a", "copy",
                        "-y",
                        output_video
                    ]
                else:
                    # 如果因任何原因无法获取码率，则退回到安全的CRF方案
                    self.log_signal.emit("[WARN] 未能检测到原始码率，将使用CRF=26作为备用方案进行编码。")
                    cmd_ffmpeg = [
                        "ffmpeg",
                        "-i", self.video_path,
                        "-vf", filter_string,
                        "-c:v", "libx264",
                        "-preset", "medium",
                        "-crf", "26",              # <-- 使用CRF作为备用方案
                        "-c:a", "copy",
                        "-y",
                        output_video
                    ]
    
                self.log_signal.emit(f"[DEBUG] {cmd_ffmpeg}")
                
                total_duration = get_video_duration(self.video_path)
                env = os.environ.copy()
                env['PYTHONIOENCODING'] = 'utf-8'
                process = subprocess.Popen(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env, encoding='utf-8')
                while True:
                    if not self.is_running:
                        process.terminate()
                        self.log_signal.emit("[INFO] 用户中止")
                        return
                    line = process.stderr.readline()
                    if not line and process.poll() is not None:
                        break
                    if "time=" in line:
                        try:
                            t = [s for s in line.split() if s.startswith("time=")][0]
                            h, m, s_all = t.split("=")[1].split(":")
                            sec = float(h)*3600 + float(m)*60 + float(s_all)
                            prog = int((sec/total_duration)*100)
                            self.progress_signal.emit(prog)
                        except:
                            pass
                    self.log_signal.emit(line.strip())
                
                process.wait()
                if process.returncode != 0:
                    stderr_output = process.stderr.read()
                    self.log_signal.emit("[ERROR] FFmpeg Stderr Output:\n" + stderr_output)
                    raise RuntimeError("字幕合成失败，请查看日志获取详细错误信息。")
    
                self.finished_signal.emit(output_video)
    
            except Exception as e:
                self.error_signal.emit(str(e))

    def stop(self):
        self.is_running = False
        self.log_signal.emit("[INFO] 停止中...")
        print("[DEBUG] Stopping thread...") 

# 主窗口
class VideoSubtitleApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频字幕工具 (提取-翻译-合成)")
        self.setGeometry(100, 100, 900, 700)
        # 设置窗口图标
        self.setWindowIcon(QIcon('icons/app_icon.png'))

        self.last_dir = ""
        self.process_thread = None
        self.api_key = self.load_api_key()

        self.init_ui()
        self.set_stylesheet()

    def load_api_key(self):
        config = configparser.ConfigParser()
        config.read('config.ini')
        try:
            return config.get('DeepSeek', 'api_key')
        except (configparser.NoSectionError, configparser.NoOptionError):
            print("无法从配置文件中读取 API Key，请检查 config.ini 文件。")
            return ""

    def init_ui(self):
            main = QWidget()
            layout = QVBoxLayout(main)
            layout.setSpacing(15)  # 增加主布局的间距
            layout.setContentsMargins(15, 15, 15, 15) # 增加窗口内边距
            self.setCentralWidget(main)
    
            font = QFont("Segoe UI", 10) # 使用更现代的字体
            self.setFont(font)
    
            # --- 控件分组 ---
            group = QGroupBox("一键处理：字幕提取-->字幕翻译-->字幕合成")
            vbox = QVBoxLayout(group)
            vbox.setSpacing(12) # 增加组内控件的垂直间距
            group.setFont(QFont("Segoe UI", 11, QFont.Bold)) # 加粗组标题
    
            # --- 视频语言选择 ---
            hbox_lang = QHBoxLayout()
            lang_label = QLabel("视频语言:")
            self.lang_combo = QComboBox()
            self.lang_combo.addItems(["ja","en",  "zh"])
            self.lang_combo.setMinimumHeight(35) # 设置最小高度
            hbox_lang.addWidget(lang_label)
            hbox_lang.addWidget(self.lang_combo)
            vbox.addLayout(hbox_lang)
    
            # --- Whisper模型选择 ---
            hbox_model = QHBoxLayout()
            model_label = QLabel("Whisper模型:")
            self.model_combo = QComboBox()
            self.model_combo.addItems(["tiny", "small", "medium", "large"])
            self.model_combo.setMinimumHeight(35) 
            hbox_model.addWidget(model_label)
            hbox_model.addWidget(self.model_combo)
            vbox.addLayout(hbox_model)
    
            # --- 文件选择 ---
            hbox_file = QHBoxLayout()
            self.video_path_label = QLabel("尚未选择视频文件")
            self.video_path_label.setObjectName("filePathLabel") # 设置ObjectName以便单独美化
            self.video_path_label.setWordWrap(True)
            self.video_path_label.setMinimumHeight(40) # 设置最小高度
            btn_select = QPushButton("选择视频")
            btn_select.setIcon(QIcon('icons/select_icon.png')) 
            btn_select.clicked.connect(self.select_video_file)
            hbox_file.addWidget(self.video_path_label)
            hbox_file.addWidget(btn_select)
            vbox.addLayout(hbox_file)
    
            # --- 进度条 ---
            self.progress = QProgressBar()
            self.progress.setTextVisible(True) # 让进度条百分比可见
            vbox.addWidget(self.progress)
    
            # --- 控制按钮 ---
            hbox_btns = QHBoxLayout()
            hbox_btns.setSpacing(10) # 按钮间距
            self.btn_start = QPushButton("开始处理")
            self.btn_start.setObjectName("startButton") # 设置ObjectName
            self.btn_start.setIcon(QIcon('icons/start_icon.png'))
            self.btn_start.clicked.connect(self.start_process)
            self.btn_cancel = QPushButton("取消")
            self.btn_cancel.setObjectName("cancelButton") # 设置ObjectName
            self.btn_cancel.setIcon(QIcon('icons/cancel_icon.png'))
            self.btn_cancel.clicked.connect(self.cancel_process)
            self.btn_cancel.setEnabled(False)
            hbox_btns.addStretch() # 添加伸缩项，让按钮靠右
            hbox_btns.addWidget(self.btn_start)
            hbox_btns.addWidget(self.btn_cancel)
            vbox.addLayout(hbox_btns)
    
            layout.addWidget(group)
    
            # --- 日志窗口 ---
            self.log = QTextEdit()
            self.log.setReadOnly(True)
            layout.addWidget(self.log)

    def set_stylesheet(self):
            self.setStyleSheet("""
                /* ---- 主窗口和通用样式 ---- */
                QMainWindow {
                    background-color: #2E3440; /* 主背景色 - 北欧深蓝 */
                }
                QWidget {
                    color: #D8DEE9; /* 默认前景色 - 浅灰 */
                    font-family: 'Segoe UI', 'Microsoft YaHei', 'sans-serif';
                    font-size: 10pt;
                }
                
                /* ---- 控件分组框 ---- */
                QGroupBox {
                    background-color: #3B4252; /* 组背景色 - 稍亮 */
                    border: 1px solid #4C566A; /* 边框颜色 */
                    border-radius: 8px; /* 圆角更大 */
                    margin-top: 1em; /* 标题与边框的距离 */
                    padding: 15px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    padding: 0 10px;
                    left: 10px;
                    color: #ECEFF4; /* 标题颜色 - 白色 */
                }
    
                /* ---- 标签 ---- */
                QLabel {
                    background-color: transparent; /* 透明背景 */
                    color: #D8DEE9;
                    font-size: 10pt;
                }
    
                /* 特别为文件路径标签设计，使其像一个显示区域 */
                QLabel#filePathLabel {
                    background-color: #2E3440;
                    border: 1px solid #4C566A;
                    border-radius: 4px;
                    padding: 8px;
                    color: #A3BE8C; /* 路径使用绿色，更醒目 */
                }
    
                /* ---- 下拉选择框 ---- */
                QComboBox {
                    background-color: #434C5E;
                    border: 1px solid #4C566A;
                    border-radius: 4px;
                    padding: 5px 10px;
                }
                QComboBox:hover {
                    border: 1px solid #88C0D0; /* 悬停时边框高亮 - 浅蓝 */
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox::down-arrow {
                    image: url(down_arrow.png); /* 您需要一个下拉箭头图标 */
                }
    
                /* ---- 按钮 ---- */
                QPushButton {
                    min-height: 32px;
                    min-width: 80px;
                    padding: 5px 15px;
                    border: none;
                    border-radius: 4px;
                    color: #ECEFF4;
                }
                QPushButton:hover {
                    background-color: #4C566A;
                }
                QPushButton:pressed {
                    background-color: #2E3440;
                }
    
                /* 开始按钮的特定样式 */
                QPushButton#startButton {
                    background-color: #5E81AC; /* 蓝色 */
                }
                QPushButton#startButton:hover {
                    background-color: #81A1C1;
                }
    
                /* 取消按钮的特定样式 */
                QPushButton#cancelButton {
                    background-color: #BF616A; /* 红色 */
                }
                QPushButton#cancelButton:hover {
                    background-color: #D08770; /* 悬停时变为橙色 */
                }
                
                QPushButton:disabled {
                    background-color: #4C566A;
                    color: #6c7583;
                }
    
                /* ---- 进度条 ---- */
                QProgressBar {
                    border: 1px solid #4C566A;
                    border-radius: 4px;
                    text-align: center;
                    color: #ECEFF4;
                    background-color: #3B4252;
                }
                QProgressBar::chunk {
                    background-color: #A3BE8C; /* 进度条填充色 - 绿色 */
                    border-radius: 3px;
                }
                
                /* ---- 日志文本框 ---- */
                QTextEdit {
                    background-color: #272B35; /* 稍亮的黑色 */
                    color: #D8DEE9;
                    border: 1px solid #4C566A;
                    border-radius: 4px;
                    font-family: 'Consolas', 'Courier New', 'monospace';
                    font-size: 10pt;
                }
    
                /* ---- 滚动条 ---- */
                QScrollBar:vertical {
                    border: none;
                    background: #3B4252;
                    width: 10px;
                    margin: 0px 0px 0px 0px;
                }
                QScrollBar::handle:vertical {
                    background: #5E81AC;
                    min-height: 20px;
                    border-radius: 5px;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    border: none;
                    background: none;
                }
            """)

    def log_message(self, msg):
        self.log.append(msg)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        print(msg)

    def select_video_file(self):
        file, _ = QFileDialog.getOpenFileName(
            self, "选择视频", self.last_dir or "", "视频文件 (*.mp4 *.mkv *.avi *.mov)"
        )
        if file:
            self.video_path_label.setText(file)
            self.last_dir = os.path.dirname(file)

    def start_process(self):
        path = self.video_path_label.text()
        if not path or path == "未选择视频文件":
            QMessageBox.warning(self, "提示", "请先选择视频文件")
            return

        language = self.lang_combo.currentText()
        model = self.model_combo.currentText()
        self.progress.setValue(0)

        self.process_thread = ProcessThread(path, language, model, self.api_key)
        self.process_thread.progress_signal.connect(self.progress.setValue)
        self.process_thread.log_signal.connect(self.log_message)
        self.process_thread.error_signal.connect(self.show_error)
        self.process_thread.finished_signal.connect(self.process_finished)
        self.process_thread.start()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)

    def cancel_process(self):
        if self.process_thread and self.process_thread.isRunning():
            self.process_thread.stop()
            self.process_thread.wait()
            self.progress.setValue(0)
            self.log_message("[INFO] 已取消")

        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def process_finished(self, output):
        self.progress.setValue(100)
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        QMessageBox.information(self, "完成", f"处理完成：\n{output}")
        open_folder(output)

    def show_error(self, msg):
        self.log_message("[ERROR] " + msg)
        QMessageBox.critical(self, "错误", msg)
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)

    def closeEvent(self, e):
        if self.process_thread and self.process_thread.isRunning():
            self.process_thread.stop()
            self.process_thread.wait()
        e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoSubtitleApp()
    window.show()
    sys.exit(app.exec_())