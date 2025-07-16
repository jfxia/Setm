# Setm--视频字幕提取翻译合成工具
提取视频文件中的字幕（Whisper），将之翻译为中文（Deepseek），并合成为一个新的带中文字幕的视频文件（FFMpeg）。

与Youtube Downloader(github.com/jfxia/YouTube-Downloader)配合使用，可以实现Youtube视频处理一条龙：从Youtube下载英文/日文视频-->语音字幕提取-->字幕翻译为中文-->合成新的中文视频文件。

## 程序依赖

**-- Python 3.8及以上版本**

**-- OpenAI Whisper** (github.com/openai/whisper，安装后在PATH环境变量中设定）)

**-- DeepSeek API Key** (订阅platform.deepseek.com，并将API Key写在配置文件config.ini中)

**-- FFMpeg**（安装后在PATH环境变量中设定）

## 用法

```
python .\setm.py
```

## 界面截屏

![截屏](/assets/screenshot1.png)

![截屏](/assets/screenshot2.png)

![截屏](/assets/screenshot3.png)
