# MambaVision-T · 牙槽骨吸收影像标注工作台

本项目是**单机运行、浏览器访问、无需云端账户**的全景片人工标注工具。标注数据保存在运行机器的 SQLite 数据库中，可导出为 JSON、JSONL、CSV 和用于后续解释模型的数据证据 JSONL。项目不包含影像、患者数据或训练权重。

> 此仓库当前发布的是**标注工具**，不是 NVIDIA MambaVision 官方实现，也不包含 Mamba/VLM 训练程序或预训练权重。

> 研究用途，不是临床诊断软件。人工标注需按统一标注规范培训、双人复核和专家仲裁。

## 功能

- 从指定本地目录递归读取 JPG / JPEG / PNG / WEBP / GIF / BMP / TIFF 影像；支持刷新队列。
- 在原始像素坐标对应的画布上绘制上颌、下颌牙槽嵴折线，并添加局部严重程度位置点。
- 记录影像质量、整体等级、复核状态、标注者 ID、备注和可选的解释样本。
- SQLite 自动保存、修订历史；每个标注者使用自己的数据库/导出包。
- 结构化证据预览；可选只读叠加兼容的 COCO polygon。
- 完整 JSON 导入；JSON / JSONL / 汇总 CSV / evidence-JSONL 导出。CSV 是质控汇总，不包含完整几何，不能代替完整 JSON 备份。
- 多标注者导出汇总：保留每位标注者的原始标注，生成需要人工仲裁的病例清单，不自动平均骨嵴线。
- 默认只绑定 `127.0.0.1`，不会把影像上传到其他服务；前端不依赖 CDN。

## 界面预览

下面仅使用程序生成的合成练习图，不含任何患者影像；线与点只用于演示操作，不代表解剖标注或诊断。

![合成练习图上的标注界面](docs/assets/synthetic-annotation-demo.png)

## 快速开始

需要 Python 3.9+（核心服务只用 Python 标准库；可选安装 Pillow 用于更准确读取 TIFF 等图像尺寸）。

1. 下载仓库 ZIP 并解压，或运行：

   ```bash
   git clone https://github.com/goodbetterbest1/MambaVision-T.git
   cd MambaVision-T
   ```

   然后将已获授权、已匿名化的原始图片复制到 `data/images/`，子文件夹可按来源或批次组织。
2. 在项目根目录运行：

   ```bash
   python3 run_local.py
   ```

   Windows 用户可在 PowerShell 中运行 `py -3 run_local.py`，或双击 `start_windows.bat`；macOS 可双击 `start_macos.command`。Windows 的 `py -3` 应指向 Python 3.9 或更新版本。

3. 浏览器访问 `http://127.0.0.1:8000/`。
4. 在页面填写标注者 ID，逐例标注。线条或表单修改自动保存；顶部状态显示保存结果。
5. 右下角导出 JSON（完整记录）或 JSONL/CSV。数据库默认位于 `annotations/annotator.sqlite3`。
6. 按 `Ctrl/⌘ + C` 停止服务。

指定数据、数据库、端口：

```bash
python3 run_local.py \
  --data /path/to/panoramic_images \
  --db /path/to/annotator_A.sqlite3 \
  --port 8000
```

可选地显示公开 COCO polygon（只读，不会覆盖公开标签）：

```bash
python3 run_local.py --data data/images --coco /path/to/instances.json
```

首次打开、替换或移动图片目录后，点病例队列右上的刷新按钮。无法读取尺寸的图片会被跳过并提示（TIFF 等可安装 Pillow：`python3 -m pip install Pillow`）。若浏览器本身无法解码 TIFF，由负责人统一无损转换为 PNG 后分发，保持像素方向和尺寸不变，不删除原图；所有人使用同一转换版本。

## 标注建议与标签边界

建议先制定由口腔/牙周专业人员确认的标注 SOP，再分发标注：

1. **影像可评估性**：良好、有限、不可评估；备注遮挡、缺牙、植体/修复体、重叠和投照伪影。
2. **上/下颌骨嵴线**：沿影像可辨认的牙槽嵴走向绘制折线；遇到不可见/严重重叠区域，应结束当前笔画，在下一个可辨识区另起一笔或在备注中明确，不要猜测连接。
3. **局部严重度点**：在需要记录的局部位置点击；标注上/下颌、六级标签（未见明显吸收、轻、中、重、不确定、不可评估）。此版本不要求 FDI 牙位，也不自动把点解释为牙位级临床诊断。
4. **整体等级**：病例级人工判断，与局部点分开记录；不确定或不可评估是有效标签。
5. **解释样本**：仅用于收集专家期望的简洁、基于影像可见证据的解释和不确定性。不要要求或保存隐藏推理过程。

### 重要：骨嵴线 + 严重度点并不能单独得到可靠 RBL 百分比

用户提出的“画骨嵴线、标严重度和位置，然后交给 VLM 解释”可作为**第一版标注和结构化证据流程**。但骨吸收的标准化测量一般还需要可识别的 CEJ、根尖/牙根轴或等效参考、影像投照校正和经专业人员确认的判定标准；单靠弓形骨嵴折线和一个局部点，不能证明精确 RBL% 或牙位级严重度。因此当前工具只保存人工等级、线和点，不会自动给患者诊断、算标准 RBL 或分期。下一版若要训练“位置+量化严重度”模型，应扩充到必要的解剖参考点、局部区域/牙位配对和标注置信度，并验证不同标注者间一致性。

## 分标注者工作流

- 每名标注者使用独立本机目录或独立数据库，例如 `annotator_A.sqlite3`、`annotator_B.sqlite3`。
- 不要把多人连接到同一网络目录的 SQLite 文件；当前工具是离线单标注者模式。
- 完成后导出 JSON/JSONL，通过受控渠道汇总。切勿把有患者信息的标注包公开上传到 GitHub。
- 合并：

  ```bash
  python3 tools/merge_annotations.py exports/A.json exports/B.jsonl --out-dir exports/merged
  ```

  生成：
  - `all_annotator_cases.jsonl`：完整保留每位标注者的原始案例；
  - `consensus_review_queue.jsonl`：同图多标注版本与待仲裁框架；不自动合成骨嵴线或等级；
  - `agreement_summary.csv`：标注数量、病例级等级多数票等质控摘要。

多数票只用于发现/排队分歧，不是临床共识。训练前应对双标子集计算序数等级一致性，并由专家对线条/位置/等级分歧仲裁。

## 解释模型数据使用

工具的 `evidence` 导出把人工标注转为可审计的结构化字段，适合作为 VLM 输入或解释评估记录。建议模型返回：结论标签、引用的证据点/线、可观察发现、局限/不确定性；当证据不够时拒判。不要将 VLM 的隐藏 chain-of-thought 作为监督目标，100 条专家解释适合做模板/提示校准和小规模验证，不足以从头训练视觉语言模型。

## 导入导出格式

- `docs/annotation-schema.json`：完整 JSON schema；核心坐标均为相对于影像宽高归一化的 `[0,1]`。
- `annotations/*.sqlite3`：本机数据库；每次保存会追加版本快照。
- `exports/*.json|jsonl|csv`：人工交换/分析文件。
- 导入默认按 `image_id` 保留本机已有标注；只有显式选择“替换并保留旧版本历史”时才覆盖当前版本；独立数据库合并请优先用脚本保留原始病例，而不是直接覆盖同一标注者数据库。

**所有人应保持相同的数据目录层级和文件名**，否则相同源图可能无法按 ID 汇总。`image_id` 根据数据目录内相对路径与文件内容摘要生成；重新编码/裁剪后的影像会得到新 ID。所有标注导出仍附带原始相对文件名，导入时需确保所用源图一致。

## 安全和 GitHub 发布

- 本服务默认绑定 `127.0.0.1`，仅当前电脑可访问。不要随便改为 `0.0.0.0` 暴露到局域网。
- Git 忽略影像目录、SQLite 数据库、导出、权重与训练产物。发布前检查 `git status` / 上传文件清单，确认无原始影像、患者 ID、未脱敏备注、许可受限数据或私有模型权重。
- GitHub 仓库只放程序、schema、文档和合成测试图；数据使用者根据数据许可自行下载原图到 `data/images/`。
- 开源标注工具不改变原始数据集许可；公开发布/训练仍必须遵守原数据协议、机构伦理与隐私要求。

## 开发和测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile run_local.py app/*.py tools/*.py
node --check web/app.js
node --test tests/frontend.test.cjs
python3 -m json.tool docs/annotation-schema.json >/dev/null
```

支持只读 COCO 标注叠加；目前不导入/覆盖 COCO，也不自动转成训练框架格式。训练前需再依据具体任务编写并验证数据导出适配器。

## 给标注者的最短流程

1. 下载本仓库并安装 Python 3.9+，不需要 GPU、Node、GitHub token 或模型。
2. 向项目负责人获取**获授权的原始图片和统一目录说明**，解压后放入 `data/images/`；不要自行重命名、重新编码或调整方向。
3. 启动本地服务，访问网页，填写自己的唯一标注者 ID。
4. 按 [标注规范](docs/annotation-guidelines.md) 绘线、添加局部等级点、选择质量和病例状态。不可见处不补画猜测线。
5. 关闭页面前确认“已保存”；每批完成后导出 **完整 JSON**，将文件重命名为 `annotator_A_batch01.json`，通过负责人指定的私密渠道返还。
6. 不要把图片或标注包上传到 GitHub。停止服务后可备份整个 `annotations/` 文件夹；服务运行时不要只拷贝 SQLite 主文件而漏掉 WAL。

想先熟悉操作、又没有原图时，可生成明确标识的合成练习图（不是真实医学影像）：

```bash
python3 tools/create_demo.py --out data/images/demo
python3 run_local.py --db annotations/practice.sqlite3
```

练习图应从正式标注目录移走；不要把练习标签混入训练集。首次扫描会读取图片用于生成稳定 ID，大型目录可能需要等待；这不是影像上传。

## 许可证与边界

代码遵循仓库的 Apache-2.0 许可证。源影像、公开数据集标签和模型权重的许可独立管理，本仓库不提供这些材料。此版本不提供自动诊断、标准 RBL% 测量、VLM 推理或训练功能。正式大规模标注前先由专业人员完成试标、统一分级规范并复核。
