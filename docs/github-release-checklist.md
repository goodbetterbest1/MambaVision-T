# GitHub 发布前检查清单

## 必须提交

- `run_local.py`
- `app/`
- `web/`
- `tools/merge_annotations.py`
- `tools/prepare_images.py`（只解压本地授权 ZIP，不下载数据）
- `tests/`（Python API/持久化与 Node 保存回归）
- `docs/annotation-schema.json`
- `docs/annotation-guidelines.md`
- `README.md`
- `docs/assets/synthetic-annotation-demo.png`（仅合成演示）
- `start_macos.command`、`start_windows.bat`
- `tools/create_demo.py`、`docs/annotator-quickstart.md`
- `.gitignore`
- 空目录占位文件 `.gitkeep`

## 不得提交

- 全景片、DICOM、患者 ID、病历号、可识别文件名或备注
- `annotations/*.sqlite3`、`exports/*`
- `*.pth`、`*.pt`、`*.ckpt`、训练日志和服务器路径
- 受限数据集的 COCO 标签、原始压缩包或派生影像
- 含访问令牌、SSH 配置、私有服务地址/账号的文件

## 发布前本地命令

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile run_local.py app/*.py tools/*.py
node --check web/app.js
node --test tests/frontend.test.cjs
python3 -m json.tool docs/annotation-schema.json >/dev/null
find data/images annotations exports -type f -not -name .gitkeep -print
```

最后一条命令应为空，或只显示经过项目负责人确认可以公开的合成测试文件。公开代码前还需单独确认原始数据集的访问/再分发许可；开源工具本身不授予影像数据再分发权。
