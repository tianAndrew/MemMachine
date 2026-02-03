# MemMachine 前端（列表 / 搜索记忆 + 本地图片）

简易页面：列表记忆、搜索记忆，并根据记忆中的 `image_path` 从本机按路径读取并显示图片。

## 运行

在仓库根目录执行：

```bash
uv run python frontend/server.py
```

浏览器打开：<http://127.0.0.1:7000>。

## 环境变量

- **MEMMACHINE_BASE_URL**：MemMachine API 地址，默认 `http://127.0.0.1:8080`。前端通过本服务代理请求，不直接连 MemMachine。
- **MEMMACHINE_FRONTEND_IMAGE_ROOT**：允许读取图片的本地根目录；记忆里的 `image_path` 必须落在此目录下才会被 `/local-image` 返回。默认 `$HOME`。**上传的图片**会保存到该目录下的 `memmachine_uploads/`，并以相对路径（如 `memmachine_uploads/xxx.jpg`）写入记忆，便于列表里正常显示。
- **Write Article** 功能需要配置 LLM（OpenAI 兼容）：
  - **OPENAI_API_BASE**：Chat 接口地址，默认 `https://api.openai.com/v1`。可用通义等兼容地址（如 `https://dashscope.aliyuncs.com/compatible-mode/v1`）。
  - **OPENAI_API_KEY**：API Key。
  - **OPENAI_MODEL**：模型名，默认 `gpt-4o`。

## 功能

- 配置 **Org ID**、**Project ID**（默认 `test` / `test`）。
- **Memories** 标签：列表记忆、搜索记忆、上传图片记忆（含 Time/Location 元数据）；仅展示带 `image_path` 的卡片，支持删除。
- **Write Article** 标签：输入**主题**（如 "Summer trip"），点击 Generate article。后端会按主题搜索记忆（文本 + 图片路径），调用 LLM 生成 Markdown 文章并在合适位置插入图片引用；文章在页面内以 Markdown 渲染显示，图片通过 `/local-image` 加载。
- 每条记忆若在 `metadata.image_path` 中有路径（且在允许根目录下），则通过 `/local-image?path=...` 显示图片。
