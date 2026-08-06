"""
视频音轨移除 - 基于 FFmpeg 移除视频中的音轨
流复制（-c copy）无损处理，保留画质与字幕，输出到原视频旁「<视频名>_无音轨」文件。
用法: python main.py <参数JSON路径>
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# 支持的视频扩展名（与 bm-scripts-box-rc.toml 的过滤器一致）
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".ts", ".m4v",
              ".mpg", ".mpeg", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".rmvb", ".rm", ".asf"}

# 输出文件名后缀
SUFFIX = "_无音轨"

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def get_path(param_path):
    """解析不忙脚本盒子传入的参数 JSON，返回有效的文件路径列表"""
    initial_files = []

    if param_path and Path(param_path).exists():
        with open(param_path, "r", encoding="utf-8") as f:
            params = json.load(f)
        raw = params.get("data", {}).get("target_paths", [])
        initial_files = [p for p in raw if Path(p).exists()]
    return initial_files


def exit_with_countdown():
    """倒计时 + 按键退出（防止右键调用时弹窗一闪而过）"""
    print("\n" + "-" * 50)
    print("按任意键立即退出，或等待倒计时自动退出")

    for i in range(5, 0, -1):
        print(f"\r⏳ {i} 秒后自动退出... (按任意键退出)", end="")
        time.sleep(1)
    print("\r👋 已退出")
    sys.exit(0)


class AudioRemover:
    """视频音轨移除器(基于 FFmpeg)：流复制无损移除音轨"""

    def __init__(self, videos, suffix=SUFFIX):
        self.videos = videos
        self.suffix = suffix
        self._ffmpeg = shutil.which("ffmpeg")
        if not self._ffmpeg:
            raise FileNotFoundError("未找到 FFmpeg（ffmpeg 命令），请确认已安装并在环境变量中")
        self._ffprobe = shutil.which("ffprobe")

    def _get_output_path(self, video_path):
        """生成输出文件路径：同目录 + 后缀，绝不覆盖原文件"""
        p = Path(video_path)
        return str(p.with_name(f"{p.stem}{self.suffix}{p.suffix}"))

    def _has_audio(self, video_path):
        """探测视频是否含音轨；探测失败时默认 True（交给 ffmpeg 处理）"""
        if not self._ffprobe:
            return True
        try:
            proc = subprocess.run(
                [self._ffprobe, "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0", video_path],
                capture_output=True, text=True, errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.returncode == 0:
                return bool(proc.stdout.strip())
        except Exception:
            pass
        return True

    def _remove_single(self, video_path):
        """移除单个视频音轨，返回 (路径, 状态, 信息)，状态: success/skipped/failed"""
        try:
            output_path = self._get_output_path(video_path)

            # 已存在跳过
            if os.path.exists(output_path):
                return video_path, "skipped", "输出文件已存在"

            # 无音轨跳过
            if not self._has_audio(video_path):
                return video_path, "skipped", "该视频没有音轨"

            # 保留视频流与字幕流（若无字幕自动忽略），丢弃音频流，其余流复制
            cmd = [self._ffmpeg, "-y", "-i", video_path,
                   "-map", "0:v", "-map", "0:s?",
                   "-map_metadata", "0",
                   "-c", "copy", "-an",
                   "-loglevel", "error",
                   output_path]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
            if proc.returncode != 0:
                return video_path, "failed", (proc.stderr or "移除失败").strip()
            return video_path, "success", output_path
        except Exception as e:
            return video_path, "failed", str(e)

    def remove_all(self, progress_callback=None):
        """批量移除音轨"""
        total = len(self.videos)
        results = {"success": [], "skipped": [], "failed": [], "total": total}

        if total == 0:
            return results

        for idx, path in enumerate(self.videos, 1):
            path, status, info = self._remove_single(path)
            if status == "success":
                results["success"].append((path, info))
            elif status == "skipped":
                results["skipped"].append((path, info))
            else:
                results["failed"].append((path, info))

            if progress_callback:
                progress_callback(idx, total)

        return results

    @staticmethod
    def get_file_size(path):
        """获取文件大小（人性化显示）"""
        size = os.path.getsize(path)
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


def cli(videos):
    # 兼容 GBK 控制台，避免打印 emoji/中文时崩溃
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    print("-" * 50)
    print('视频音轨移除')
    print("-" * 50)

    # 只保留支持的视频文件
    videos = [v for v in videos if Path(v).suffix.lower() in VIDEO_EXTS]
    if not videos:
        print("❌ 未选择有效的视频文件")
        print("⚠️ 请选中文件后通过右键菜单或快捷键使用本脚本")
        exit_with_countdown()
        return

    try:
        remover = AudioRemover(videos=videos)
    except Exception as e:
        print(f"❌ {e}")
        exit_with_countdown()
        return

    print(f"输出：原视频旁「<视频名>_无音轨」文件（流复制，不损失画质，保留字幕）")
    print(f"待处理视频：{len(videos)} 个")
    print("-" * 50)

    def show_progress(current, total):
        print(f"\r进度：{current}/{total} ({current / total * 100:.1f}%)", end="")

    result = remover.remove_all(progress_callback=show_progress)
    print(f"\n\n✅ 成功：{len(result['success'])} 个")
    for path, output in result["success"]:
        try:
            size = AudioRemover.get_file_size(output)
        except OSError:
            size = "?"
        print(f"   {os.path.basename(path)} → {os.path.basename(output)}（{size}）")

    if result["skipped"]:
        print(f"\n⏭️ 跳过：{len(result['skipped'])} 个")
        for path, reason in result["skipped"]:
            print(f"   {os.path.basename(path)}：{reason}")

    if result["failed"]:
        print(f"\n❌ 失败：{len(result['failed'])} 个")
        for path, error in result["failed"]:
            print(f"   {os.path.basename(path)}：{error}")

    exit_with_countdown()


def main():
    param_path = sys.argv[1] if len(sys.argv) > 1 else None
    paths = get_path(param_path)
    cli(paths)


if __name__ == "__main__":
    main()
