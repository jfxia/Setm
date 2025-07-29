import os
import sys
import subprocess
import json
import platform
import re
import logging
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


import requests
import json
import re
import time
import logging

# 定义自定义异常处理部分条数不足的情况
class PartialTranslationError(Exception):
    def __init__(self, message, translated_items, missing_indices):
        super().__init__(message)
        self.translated_items = translated_items
        self.missing_indices = missing_indices

#调用Deepseek进行翻译，批处理
def translate_text_deepseek(text_list, api_key, batch_id=None):
    """
    Translates a list of texts using the DeepSeek API with enhanced error handling
    and partial result recovery.
    """
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 优化后的系统提示词 - 更严格的格式控制
    system_prompt = """
    You are an expert subtitle translator. You will receive a numbered list of texts.
    Translate each numbered text into natural, fluent Simplified Chinese without any extra explanations.
    
    RULES:
    1. Preserve EXACTLY the same number of items in the output as in the input
    2. Output MUST be a JSON object with a single key: "translations"
    3. "translations" must be an array of strings in the SAME ORDER as input
    4. Do NOT merge or split any items
    5. Each translation should be concise and match the original length
    
    Example Input:
    1. Hello world
    2. Good morning
    
    Example Output:
    {"translations": ["你好世界", "早上好"]}
    """
    
    # 添加批次ID到用户内容帮助模型跟踪上下文
    batch_header = f"Batch ID: {batch_id}\n" if batch_id else ""
    user_content_lines = [f"{i+1}. {text}" for i, text in enumerate(text_list)]
    user_content = batch_header + "\n".join(user_content_lines)

    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1,
        "top_p": 0.85,
        "max_tokens": 4096,  # 确保最大token设置
        "response_format": {"type": "json_object"}
    }
    
    try:
        # 增加超时和重试逻辑
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()
        
        response_json = response.json()
        response_text = response_json["choices"][0]["message"]["content"]
        
        # 处理可能的非JSON响应
        if not response_text.strip().startswith("{"):
            # 尝试提取可能的JSON部分
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start != -1 and json_end != 0:
                response_text = response_text[json_start:json_end]
        
        parsed_json = json.loads(response_text)
        
        # 增强的错误处理
        if 'error' in parsed_json:
            error_msg = parsed_json.get('error', {}).get('message', 'Unknown API error')
            raise ValueError(f"API error: {error_msg}")
            
        if 'translations' not in parsed_json:
            raise ValueError("Missing 'translations' key in response")
            
        translated_list = parsed_json['translations']
        
        # 检查返回条数是否匹配
        if len(translated_list) != len(text_list):
            # 部分成功时返回已翻译内容
            translated_items = []
            missing_indices = []
            
            for i in range(len(text_list)):
                if i < len(translated_list):
                    translated_items.append((i, translated_list[i]))
                else:
                    missing_indices.append(i)
            
            raise PartialTranslationError(
                f"Partial translation: Got {len(translated_list)} of {len(text_list)}",
                translated_items,
                missing_indices
            )
        
        return [item for item in translated_list]
        
    except (json.JSONDecodeError, KeyError) as e:
        logging.error(f"JSON parsing failed: {str(e)}")
        logging.error(f"API response: {response_text[:500]}")
        raise ValueError("Failed to parse API response as JSON") from e
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error: {str(e)}")
        raise ValueError(f"Network error: {e}") from e
        
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise

def translate_srt_file(input_srt, output_srt, api_key, log_signal):
    """
    Enhanced SRT translation with dynamic batching and automatic retry
    """
    with open(input_srt, "r", encoding="utf-8") as f:
        content = f.read()

    srt_pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)', re.MULTILINE)
    srt_blocks = srt_pattern.findall(content)
    original_texts = [block[2].replace('\n', ' ').strip() for block in srt_blocks]
    translated_texts = [""] * len(original_texts)  # 预填充空结果
    
    # 动态批次大小参数
    MAX_RETRIES = 3
    BASE_BATCH_SIZE = 15
    MIN_BATCH_SIZE = 3
    
    current_batch_size = BASE_BATCH_SIZE
    batch_num = 0
    
    i = 0
    while i < len(original_texts):
        batch_size = min(current_batch_size, len(original_texts) - i)
        batch_originals = original_texts[i:i+batch_size]
        batch_num += 1
        
        retry_count = 0
        success = False
        
        while not success and retry_count < MAX_RETRIES:
            try:
                log_signal.emit(f"[INFO] Translating batch {batch_num} ({i+1}-{i+len(batch_originals)}), size={len(batch_originals)}")
                
                # 添加批次ID帮助跟踪
                batch_translated = translate_text_deepseek(
                    batch_originals, 
                    api_key,
                    batch_id=f"{i+1}-{i+len(batch_originals)}"
                )
                
                # 成功获取完整批次
                for j in range(len(batch_originals)):
                    translated_texts[i+j] = batch_translated[j]
                
                log_signal.emit(f"[SUCCESS] Batch {batch_num} completed")
                success = True
                
                # 成功时稍微增加批次大小（上限为20）
                current_batch_size = min(20, current_batch_size + 1)
                
            except PartialTranslationError as e:
                # 处理部分成功的情况
                log_signal.emit(f"[WARN] Partial translation: {len(e.translated_items)}/{len(batch_originals)} succeeded")
                
                # 填充已翻译的部分
                for idx, text in e.translated_items:
                    translated_texts[i+idx] = text
                
                # 创建仅包含缺失项目的新批次
                missing_items = [batch_originals[idx] for idx in e.missing_indices]
                
                if missing_items:
                    log_signal.emit(f"[INFO] Retrying {len(missing_items)} missing items")
                    
                    try:
                        # 重试缺失的项目
                        retry_translated = translate_text_deepseek(
                            missing_items, 
                            api_key,
                            batch_id=f"RETRY-{i+1}-{i+len(batch_originals)}"
                        )
                        
                        # 填充缺失的翻译
                        for k, idx in enumerate(e.missing_indices):
                            translated_texts[i+idx] = retry_translated[k]
                        
                        success = True
                        log_signal.emit(f"[SUCCESS] Missing items translated")
                    
                    except Exception as retry_e:
                        log_signal.emit(f"[ERROR] Retry failed: {str(retry_e)}")
                        # 重试失败时回退到单行翻译
                        for idx in e.missing_indices:
                            try:
                                single_result = translate_text_deepseek(
                                    [batch_originals[idx]], 
                                    api_key
                                )
                                translated_texts[i+idx] = single_result[0]
                                log_signal.emit(f"[INFO] Translated line {i+idx+1} individually")
                            except Exception:
                                log_signal.emit(f"[WARN] Using original for line {i+idx+1}")
                                translated_texts[i+idx] = batch_originals[idx]  # 使用原文
                        success = True
                
            except Exception as e:
                retry_count += 1
                wait_time = 2 ** retry_count  # 指数退避
                
                if retry_count < MAX_RETRIES:
                    log_signal.emit(f"[WARN] Batch {batch_num} failed (attempt {retry_count}/{MAX_RETRIES}): {str(e)}")
                    log_signal.emit(f"[INFO] Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    
                    # 减少批次大小防止反复失败
                    current_batch_size = max(MIN_BATCH_SIZE, current_batch_size - 2)
                else:
                    log_signal.emit(f"[ERROR] Batch {batch_num} failed after {MAX_RETRIES} attempts")
                    
                    # 回退到逐行翻译
                    for j in range(len(batch_originals)):
                        try:
                            single_result = translate_text_deepseek(
                                [batch_originals[j]], 
                                api_key
                            )
                            translated_texts[i+j] = single_result[0]
                            log_signal.emit(f"[INFO] Translated line {i+j+1} individually")
                        except Exception:
                            log_signal.emit(f"[WARN] Using original for line {i+j+1}")
                            translated_texts[i+j] = batch_originals[j]  # 使用原文
                    success = True
        
        # 移动到下一批次
        i += len(batch_originals)

    # 写入翻译后的SRT文件
    with open(output_srt, "w", encoding="utf-8") as f:
        for idx, block in enumerate(srt_blocks):
            if idx < len(translated_texts):
                f.write(f"{block[0]}\n")
                f.write(f"{block[1]}\n")
                f.write(f"{translated_texts[idx]}\n\n")
            else:
                f.write(f"{block[0]}\n")
                f.write(f"{block[1]}\n")
                f.write(f"{block[2]}\n\n")  # 使用原始文本作为后备
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
    
                # 检查是否存在同名SRT文件 ---
                if os.path.exists(srt_path):
                    self.log_signal.emit(f"[INFO] 发现已存在的字幕文件: {os.path.basename(srt_path)}")
                    self.log_signal.emit("[INFO] 跳过 Whisper 字幕提取步骤。")
                else:
                    self.log_signal.emit("[INFO] 未发现同名字幕文件，开始使用 Whisper 提取字幕。")
                    # 强制子进程使用 UTF-8 环境
                    proc_env = os.environ.copy()
                    proc_env['PYTHONUTF8'] = '1'
                    cmd_whisper = [
                        "whisper", self.video_path, "--model", self.model_size, "--language", self.language,
                        "--output_format", "srt", "--output_dir", os.path.dirname(self.video_path)
                    ]
                    self.log_signal.emit(f"[DEBUG] {cmd_whisper}")
                    process = subprocess.Popen(cmd_whisper, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8',env=proc_env)
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
                        "-b:v", original_bitrate,
                        "-c:a", "copy",
                        "-y",
                        output_video
                    ]
                else:
                    self.log_signal.emit("[WARN] 未能检测到原始码率，将使用CRF=26作为备用方案进行编码。")
                    cmd_ffmpeg = [
                        "ffmpeg",
                        "-i", self.video_path,
                        "-vf", filter_string,
                        "-c:v", "libx264",
                        "-preset", "medium",
                        "-crf", "26",
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
            self.model_combo.addItems(["small", "tiny","medium", "large"])
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