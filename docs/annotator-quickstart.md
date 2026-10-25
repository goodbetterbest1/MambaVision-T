# 给标注者的使用说明

## 安装

下载仓库 ZIP → 解压 → 安装 Python 3.9+。无需 GPU、Node 或 GitHub 登录。

原始图片入口见 README 的“原始标注图片在哪里下载”：原作者仓库 https://github.com/PuckBlink/PDCNN ，Google Drive https://drive.google.com/drive/folders/18qUxeRPHPcCQT9o8AgV5400f05Fu3ISW 。只需下载 `Images.zip`（约 2.72 GB）；先确认授权，不再分发原图。

将获授权 ZIP 用 `python3 tools/prepare_images.py --archive /path/to/Images.zip --out data/images` 统一解压（Windows 用 `py -3`）。也可将负责人分配的、已获授权的匿名全景图放进 `data/images/`。必须保留统一相对路径、文件名和源图字节；目录不同会导致 ID 不同。不要裁剪、旋转或重新压缩原图。建议 JPG/PNG；其他格式在部分浏览器中可能无法显示。

## 启动

- macOS：双击 `start_macos.command`，或终端中执行 `python3 run_local.py`。
- Windows：双击 `start_windows.bat`，或 PowerShell 中执行 `py -3 run_local.py`。
- Linux：执行 `python3 run_local.py`。
- 打开 http://127.0.0.1:8000/，不要直接双击网页 HTML。

正式配置建议：

```bash
python3 run_local.py \
  --data data/images \
  --db annotations/annotator_A.sqlite3 \
  --coco data/imports/via_export_coco_BL.json \
  --autosave-delay-ms 750 \
  --undo-depth 100
```

`--coco` 是只读辅助标注；`--autosave-delay-ms` 是自动保存防抖时间；`--undo-depth` 是线段/点位撤回栈深度。服务启动后网页底部会显示这些配置和实际保存路径。

## 每例操作

1. 填写唯一标注者 ID，检查原图是否清晰。
2. 选择上颌/下颌骨嵴线工具，按住左键描画**可见的骨嵴边缘**。松开结束一段，下一段另起一笔。不要跨不确定区猜测连接。
3. 选择严重度点，先选颌别、等级、置信度，再点影像中的局部位置。右侧可删除错误点。
4. 填写影像质量、病例整体等级和备注。等级由项目统一 SOP 定义，不是工具自动给出的诊断。
5. 可选填写解释样本：可见发现、对应证据、简洁解释和局限。
6. 检查保存状态，再设“已完成”或“需要复核”。仍不确定的病例应明确记录不确定，不能默认健康。

## 本机自动保存

完成一笔/修改字段后约 750 ms 自动保存，不需要每次导出。默认写入 `annotations/annotator.sqlite3` 及 `annotations/annotator_json/<image_id>.json`。带 `--db annotations/annotator_A.sqlite3` 启动则写入 A 对应的数据库和 `annotator_A_json/` 文件夹。主库保存完整修订历史，JSON 保存最新标注；网页右下角显示真实路径。顶部保存失败或右下角 JSON 警告时请处理，不要直接关闭。

“撤回上一步”或 `Ctrl/⌘+Z` 只撤回最近的绘线/位置点操作；病例等级、备注和解释文字需要人工修改后再次保存。切换病例或刷新页面会清空网页撤回栈，但不会删除 SQLite 历史。

## 交付

右下角导出“完整 JSON”，按标注者和批次命名。通过负责人指定的**私密渠道**返还；不上传 GitHub。CSV 只有汇总统计，不能代替完整 JSON 几何记录。每个标注者使用自己的数据库，不共享 SQLite。

导入默认保留本机已有记录；需要覆盖时显式选择替换，旧内容仍保留在数据库修订历史。合并多人结果时由负责人使用合并脚本，不要依次覆盖同一个数据库。

## 注意

- 一般浏览器缩放会改变显示大小，但记录的是原始影像归一化坐标。
- 不要用练习合成图充当真实标注。
- 不能只凭骨嵴线推导标准 RBL% 或牙周炎临床分期。
- 此版本不含自动判别或 VLM 模型。
