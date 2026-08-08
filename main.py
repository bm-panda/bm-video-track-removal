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

# ── 路径 ──
BASE_DIR = Path(__file__).parent

# 支持的视频扩展名（与 bm-scripts-box-rc.toml 的过滤器一致）
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".ts", ".m4v",
              ".mpg", ".mpeg", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".rmvb", ".rm", ".asf"}

# 输出文件名后缀
SUFFIX = "_无音轨"


class AudioRemover:
    """视频音轨移除器（基于 FFmpeg）：流复制无损移除音轨，承载通用 subprocess 执行，只产数据。"""

    @staticmethod
    def _run(cmd, **kw):
        """执行命令，默认隐藏控制台窗口、按 UTF-8 容错解码。"""
        kw.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
        kw.setdefault("encoding", "utf-8")
        return subprocess.run(cmd, text=True, errors="replace", **kw)

    @staticmethod
    def _require_binaries():
        """校验 ffmpeg，缺则直接报错（供 Cli 开局预检）。"""
        if not shutil.which("ffmpeg"):
            raise FileNotFoundError("未找到 FFmpeg，请安装并加入环境变量 PATH（https://ffmpeg.org/download.html）")

    def __init__(self, videos):
        """videos: 视频文件路径列表。"""
        self.videos = [v for v in videos if Path(v).exists()]

        self._require_binaries()
        self._ffmpeg = shutil.which("ffmpeg")
        self._ffprobe = shutil.which("ffprobe")

    def _get_output_path(self, video_path):
        """生成输出文件路径：同目录 + 后缀，绝不覆盖原文件。"""
        p = Path(video_path)
        return str(p.with_name(f"{p.stem}{SUFFIX}{p.suffix}"))

    def _has_audio(self, video_path):
        """探测视频是否含音轨；探测失败时默认 True（交给 ffmpeg 处理）。"""
        if not self._ffprobe:
            return True
        try:
            proc = self._run(
                [self._ffprobe, "-v", "error", "-select_streams", "a",
                 "-show_entries", "stream=index", "-of", "csv=p=0", video_path],
                capture_output=True,
            )
            if proc.returncode == 0:
                return bool(proc.stdout.strip())
        except Exception:
            pass
        return True

    def _remove_single(self, video_path, on_start=None):
        """移除单个视频音轨，返回 (路径, 状态, 信息)，状态: success/skipped/failed。"""
        try:
            output_path = self._get_output_path(video_path)

            # 已存在跳过
            if os.path.exists(output_path):
                return video_path, "skipped", "输出文件已存在"

            # 无音轨跳过
            if not self._has_audio(video_path):
                return video_path, "skipped", "该视频没有音轨"

            if on_start:
                on_start(video_path)

            # 保留视频流与字幕流（若无字幕自动忽略），丢弃音频流，其余流复制
            cmd = [self._ffmpeg, "-y", "-i", video_path,
                   "-map", "0:v", "-map", "0:s?",
                   "-map_metadata", "0",
                   "-c", "copy", "-an",
                   "-loglevel", "error",
                   output_path]
            proc = self._run(cmd, capture_output=True)
            if proc.returncode != 0:
                return video_path, "failed", (proc.stderr or "移除失败").strip()
            return video_path, "success", output_path
        except Exception as e:
            return video_path, "failed", str(e)

    def remove_all(self, on_start=None, on_done=None) -> dict:
        """顺序移除全部视频音轨，回调供 Cli 展示；返回分组结果 dict。"""
        results = {"success": [], "skipped": [], "failed": [], "total": len(self.videos)}

        for path in self.videos:
            path, status, info = self._remove_single(path, on_start=on_start)
            if status == "success":
                results["success"].append((path, info))
            elif status == "skipped":
                results["skipped"].append((path, info))
            else:
                results["failed"].append((path, info))
            if on_done:
                on_done(path, status, info)

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


class Cli:
    """批处理命令行流程（含盒子参数解析与输出编码修复）。"""

    @staticmethod
    def _fix_encoding():
        # 统一输出编码，避免 GBK 控制台下 emoji/中文报错（盒子环境已设 PYTHONUTF8=1）
        for _s in (sys.stdout, sys.stderr):
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass

    @staticmethod
    def _dw(text):
        """近似显示宽度：CJK/全角/emoji 计 2，其余计 1（横幅自适应宽度用）。"""
        return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)

    @staticmethod
    def _version():
        try:
            for line in (BASE_DIR / "bm-scripts-box-rc.toml").read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            pass
        return ""

    @staticmethod
    def _title():
        v = Cli._version()
        return f"🔇 视频音轨移除{(' v' + v) if v else ''} · 流复制无损移除"

    @staticmethod
    def _banner(text):
        w = Cli._dw(text) + 4
        bar = "─" * w
        print("┌" + bar + "┐")
        print("│  " + text + "  │")
        print("└" + bar + "┘")

    @staticmethod
    def _section(title):
        print(f"── {title} " + "─" * 22)

    @staticmethod
    def get_path(param_path):
        """解析盒子传入的 JSON 参数文件，返回存在的视频路径列表。"""
        if not (param_path and Path(param_path).exists()):
            return []
        try:
            with open(param_path, "r", encoding="utf-8") as f:
                params = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        raw = params.get("data", {}).get("target_paths", [])
        return [p for p in raw if Path(p).exists()]

    def run(self, paths):
        """批处理主流程：扫描 → 处理 → 结果 → 倒计时退出。"""
        Cli._banner(Cli._title())

        videos, skipped = [], []
        for p in paths:
            if Path(p).suffix.lower() in VIDEO_EXTS:
                videos.append(p)
            else:
                skipped.append(p)
        if skipped:
            self._section("扫描")
            for p in skipped:
                print(f"  ⏭️ 忽略非视频: {Path(p).name}")

        if not videos:
            print("  ❌ 未选择有效的视频文件")
            print("  ⚠️ 请选中文件后通过右键菜单或快捷键使用本脚本")
            self._exit()
            return

        self._section("处理")
        total = len(videos)
        started = [0]

        def on_start(path):
            started[0] += 1
            print(f"  ▶ ({started[0]}/{total}) 正在移除音轨: {Path(path).name}")

        def on_done(path, status, info):
            name = Path(path).name
            if status == "success":
                try:
                    size = AudioRemover.get_file_size(info)
                except OSError:
                    size = "?"
                print(f"  ✅ {name} → {Path(info).name}（{size}）")
            elif status == "skipped":
                print(f"  ⏭️ {name}  {info}")
            else:
                print(f"  ❌ {name}  {(info or '未知错误').strip().splitlines()[0]}")

        remover = AudioRemover(videos)
        result = remover.remove_all(on_start=on_start, on_done=on_done)

        self._section("结果")
        parts = [f"✅ 成功 {len(result['success'])} 个"]
        if result["skipped"]:
            parts.append(f"⏭️ 跳过 {len(result['skipped'])} 个")
        if result["failed"]:
            parts.append(f"❌ 失败 {len(result['failed'])} 个")
        print("  " + " · ".join(parts))
        self._exit()

    @staticmethod
    def _exit():
        width, total = 10, 5
        for i in range(total, 0, -1):
            filled = round(width * (total - i + 1) / total)
            bar = "█" * filled + "░" * (width - filled)
            print(f"\r  ⏳ {i}s {bar}  按任意键立即退出", end="")
            time.sleep(1)
        print("\r" + " " * 60, end="\r")
        print("  👋 已退出")
        sys.exit(0)


def main():
    Cli._fix_encoding()                      # 先修编码，再打印任何东西
    param_path = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        if param_path:                        # 盒子传入 JSON 参数 → 批处理
            paths = Cli.get_path(param_path)
            if not paths:
                print("未获取到有效的文件路径")
                time.sleep(2)
            else:
                Cli().run(paths)
        else:                                 # 无参 → 纯命令行工具，仅提示用法
            Cli._banner(Cli._title())
            print("  本脚本由「不忙脚本盒子」通过右键菜单或快捷键调用，无需手动打开")
            print("  手动测试: python main.py <参数JSON路径>")
            time.sleep(2)
    except FileNotFoundError as e:            # 缺 ffmpeg → 中文报错，停留 3 秒
        print(f"❌ {e}")
        time.sleep(3)


if __name__ == "__main__":
    main()
