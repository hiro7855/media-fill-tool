# 录录媒 · 媒介信息回填工具 (media-fill-tool)

一个在本机运行的小工具:把媒体老师发来的**参会回执、机票、高铁截图**直接拖进浏览器,AI 自动识别出姓名、职位、电话、身份证、收款信息以及去程/返程行程;人工核对无误后,一键**回填到飞书表格**,告别逐项手敲。

全程在本地网页里点鼠标完成 —— 不需要打开命令行,也不需要手动改 Excel。

> 数据只在你本机、你自己的模型 relay 与飞书租户之间流转,不经过任何第三方。

## 功能

- **视觉识别**:截图 base64 直传视觉模型(OpenAI 兼容接口),无需 OCR;群聊「一图多人」自动拆分为多条记录。
- **硬校验 + AI 存疑标记**:手机号、身份证(含校验位)、银行卡(Luhn)、日期时间等本地规则校验;格式错标红,AI 不确定标黄。
- **按人卡片核对**:一媒体一卡、每人三行(身份信息 / 去程 / 返程),红黄就地高亮并给出原因,顶部问题汇总条一键跳到待修正项。
- **待认领行程**:没有出行人姓名的行程集中列出,下拉选人认领。
- **一键回填飞书**:按**列位置**映射写入飞书电子表格(支持重复列名场景),写入前可试算预览,确认后再追加,写入默认关闭需显式确认。

## 技术栈

- 后端:Python 3.9+,Flask(仅绑定 `127.0.0.1`)、requests、Pillow、openpyxl、PyYAML
- 前端:纯 vanilla JS,无构建步骤;苹果风设计 token
- 模型:任意 OpenAI 兼容 + 视觉的 relay(默认模型名 `claude-sonnet-5`)
- 回填:飞书开放平台 Sheets v2 `values_append`,纯 Python 取 `tenant_access_token`

## 快速开始

1. **装 Python 3.9+**(<https://www.python.org/downloads/>,Windows 安装时勾选 “Add python.exe to PATH”)。
2. **装依赖**:双击 `安装依赖.bat`(Windows)/ `安装依赖.command`(macOS),或手动:
   ```bash
   pip install -r requirements.txt
   ```
3. **填配置**:把 `config.example.yaml` 复制为 `config.yaml`,填入你的 relay `api_key`、飞书 `app_id`/`app_secret` 和目标表 `target_url`。
   > `config.yaml` 含密钥,已被 `.gitignore` 忽略,请勿提交或外发。
4. **启动**:双击 `启动媒介助手.bat` / `启动媒介助手.command`,浏览器会自动打开 `http://127.0.0.1:8765/`。**保持那个黑色窗口开着**,它就是工具本体;用完关掉即停止。

详细图文步骤见 [使用说明.md](使用说明.md)。

## 网页里三步走

1. **选活动** —— 新建活动,或从活动历史里进入已有活动。
2. **资料识别** —— 把这场活动的文字/截图拖进去(建议一人一个单元),点识别,按人核对红黄标记并保存。
3. **回填飞书** —— 试算预览确认每列落点,再确认写入,数据追加到目标表。

## 命令行(可选)

网页之外也保留 CLI,与网页共用同一套校验与安全闸门:

```bash
# 冒烟自检
PYTHONUTF8=1 py -3 src/run_extract.py --selfcheck
# 识别某活动
PYTHONUTF8=1 py -3 src/run_extract.py --activity <活动名>
# 回填(默认只试算,加 --write 才真正写)
PYTHONUTF8=1 py -3 src/run_apply.py --file 产出/<活动>.records.json
```

## 示例数据

`输入/测试活动/` 下是 [make_sample.py](make_sample.py) 生成的**全合成脱敏**样例(虚构的张三/李四 + 测试卡号),仅用于体验流程,不含任何真实个人信息。

## 目录结构

```
src/          业务模块(config/llm_client/extract/validate/mapping/feishu/service/webapp …)
web/          前端(index.html / app.js / styles.css,无构建)
输入/          放待识别的资料(按 活动/单元 组织)
产出/          识别结果与复核表(运行时生成,已被 .gitignore 忽略)
config.example.yaml   配置模板(复制为 config.yaml 使用)
```

## 隐私与安全

- 本工具在本机运行,Web 服务只绑定 `127.0.0.1`。
- `config.yaml`、`产出/`、真实输入资料均已被 [.gitignore](.gitignore) 忽略,不会进入版本库。
- 待处理数据含个人敏感信息(身份证、银行卡等),请妥善保管本机文件,勿将真实数据提交到任何仓库。

## License

[MIT](LICENSE)
