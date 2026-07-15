# Windows 11 Electron 双窗口桌面壳最小闭环设计

> 日期：2026-07-15
> 状态：设计已获用户批准；待书面规格复核后编写实施计划
> 项目根：`AI桌宠/`

## 1. 背景与目标

Stage 4 已完成有界情感状态、文本表达、consent-gated 分析、消息绑定 ExpressionPlan/TTS 和浏览器表现事件闭环。下一步不是扩张 Stage 4，而是在 Windows 11 上增加独立的本地展示层，验证现有 React/FastAPI 内核能在原生窗口、系统托盘和透明悬浮表面中持续工作。

本设计定义一个**开发态 Electron 双窗口最小闭环**：

- Electron 承载现有 React 聊天应用；
- 默认只显示聊天窗口；
- 用户可通过聊天按钮或系统托盘显示透明悬浮角色窗口；
- 聊天 renderer 是业务、API、录音、TTS 和播放生命周期的唯一状态源；
- 悬浮 renderer 只消费经过主进程校验和中继的只读表现快照；
- 首轮允许用户导入其有权使用的静态透明 PNG/WebP；
- Live2D 只定义适配器边界，作为紧随其后的独立闭环。

本设计不实现代码。书面规格批准后，另写文件级实施计划。

## 2. 诚实边界与非目标

### 2.1 本闭环交付

- Windows 11 Electron 开发态壳；
- 聊天窗口与透明悬浮窗口；
- 系统托盘、显示/隐藏、置顶、拖动和可切换鼠标穿透；
- 单向、版本化、只读的表现快照投影；
- 用户本地授权静态 PNG/WebP 的受控导入、复制、恢复和清除；
- 静态素材 renderer 和中性 CSS fallback；
- fake-first 自动化与真实 Windows 窗口 smoke。

### 2.2 明确不交付

- Electron 自动启动、停止或重启 FastAPI/Vite；
- 可安装、签名、自动更新或开机启动的生产应用；
- Python sidecar、端口发现、安装数据迁移或卸载清理；
- Live2D SDK、Cubism 模型加载、动作/参数映射、口型或 WebGL context 恢复；
- 后台监听、唤醒词、自动 spoken barge-in 或全双工语音；
- 目标角色或其他受保护名称、立绘、模型、动画、声音；
- 将用户导入素材上传、提交或分发。

## 3. 技术路线

### 3.1 采用 Electron

采用 Electron 而不是 Tauri v2 或 pywebview：

- 当前前端已使用 React、TypeScript、Vite；Electron 与现有构建工具直接衔接；
- 当前录音、VAD、Web Audio、HTMLAudio fallback 和输出设备行为已在 Chromium 浏览器路径上验证；Electron 的 Chromium runtime 更接近既有证据；
- Windows 双窗口、透明、tray、always-on-top 和 `setIgnoreMouseEvents` 能力成熟；
- `contextIsolation`、sandbox 和窄 preload bridge 可建立明确安全边界。

接受的代价是开发与未来分发体积较大。本设计不把 Electron 选型等同于生产打包选型；只有桌面交互契约和资源数据完成测量后，才评估是否保留 Electron 或迁移。

### 3.2 开发态启动边界

开发者分别启动：

1. loopback FastAPI，使用 fake providers；
2. Vite 开发服务器；
3. Electron 主进程。

聊天 renderer 继续通过 Vite proxy 使用相对 `/api` 和 `/health`。本轮不修改 FastAPI CORS，不新增 API base resolver，不放宽网络监听，也不管理开发者启动的后端或前端进程。

## 4. 进程与组件架构

### 4.1 Electron 主进程

主进程只负责桌面系统能力：

- 创建、隐藏和恢复聊天窗口与悬浮窗口；
- 创建系统托盘和固定菜单；
- 管理悬浮窗 always-on-top 与 click-through；
- 保存和恢复非敏感窗口偏好；
- 打开原生素材文件选择器；
- 校验并复制本地静态素材；
- 通过受限本地 scheme 提供 opaque asset ID 对应的只读素材；
- 校验聊天 renderer 发布的表现快照并中继给悬浮 renderer；
- 在内存中保留最新合法快照，用于悬浮 renderer 重载后的重放。

主进程不是聊天、情感、播放或素材表现业务状态源，不调用 Provider，不访问 SQLite，不记录表现快照。

### 4.2 聊天 BrowserWindow

聊天窗口承载现有 React 应用并保持以下唯一所有权：

- 会话、消息、记忆和情感 UI；
- FastAPI API 调用；
- 用户明确触发的录音和 VAD；
- TTS 请求和音频播放；
- `assistantMessageId + playbackRunId` 生命周期；
- expression preview state；
- 表现快照的派生与发布。

应用启动时默认只显示聊天窗口。聊天界面增加最小桌面入口：显示/隐藏桌宠、导入/清除素材和必要的当前桌面状态反馈。

### 4.3 悬浮 Pet BrowserWindow

悬浮窗口：

- 透明、无系统边框、不显示在任务栏；
- 默认 always-on-top；
- 默认可交互和可拖动；
- 只渲染本地静态素材、中性 fallback 和有限语义表现；
- 不访问 FastAPI、SQLite、Provider、文件系统、麦克风或 TTS；
- 不控制播放，不修改聊天业务状态，不发布表现状态。

### 4.4 Preload 分离

聊天窗口与悬浮窗口使用不同 preload：

- chat preload 可请求固定窗口命令、发布严格表现快照、打开受控素材选择器，并订阅非敏感桌面设置结果；
- pet preload 只能订阅表现快照、请求最新快照以及执行必要的有限窗口交互；
- 两者均不暴露 `ipcRenderer`、通用 `send`、Node 对象、真实文件路径、shell 或环境变量。

## 5. 表现投影协议

### 5.1 单向完整快照

固定数据流：

```text
Chat renderer
→ Electron main：发送者、来源与 schema 校验
→ Pet renderer：只读整包替换
```

采用完整快照而不是在第二 renderer 中重放所有 speaking 增量事件。这样即使中间 IPC 丢失，下一快照仍可收敛到聊天 renderer 的真实状态。

### 5.2 `PresentationSnapshotV1`

逻辑结构：

```ts
interface PresentationSnapshotV1 {
  schemaVersion: 1;
  projectionEpoch: number;
  sequence: number;
  selectedAssistantMessageId: string | null;
  expression: {
    delivery: 'neutral' | 'warm' | 'reassuring' | 'reserved' | 'firm';
    intensity: 'low' | 'medium';
    rate: number;
    source: 'rule' | 'llm' | 'default';
  } | null;
  phase: 'idle' | 'ready' | 'speaking' | 'paused';
  activeRun: {
    assistantMessageId: string;
    playbackRunId: number;
  } | null;
  displayLabel: string | null;
  asset: {
    kind: 'neutral' | 'static';
    assetRevision: number;
  };
}
```

精确字段名可在实施计划中按现有类型命名校准，但语义不得扩大。

### 5.3 投影不变量

- `projectionEpoch` 是由主进程为当前 chat `webContents` 分配的非负安全整数。chat renderer 不能自行选择 epoch；它通过 chat preload 取得当前 epoch，并把它原样带入发布请求。chat reload、crash 或 `webContents` replacement 时，主进程先递增 epoch、清除 latest snapshot，再向 pet 发送原子 reset；pet 必须清除表现状态和 sequence watermark，回到 Neutral/Idle，然后才接受新 epoch 的快照。
- `sequence` 在一个 `projectionEpoch` 内严格递增，并由 chat renderer 从 1 开始；不写磁盘。主进程只接受当前分配 epoch，且拒绝该 epoch 内低于或等于当前值的旧 sequence。
- pet 按 `(projectionEpoch, sequence)` 排序：低于当前 epoch 的快照永远拒绝；更高的合法 epoch 必须先经主进程 reset；同 epoch 只接受更高 sequence。Vite HMR、chat reload 和 crash recovery 必须覆盖该握手，避免新 renderer 从低 sequence 开始后被永久拒绝。
- `activeRun` 继续使用 `(assistantMessageId, playbackRunId)` 精确身份；pause/resume 沿用同一 run，replay 创建新 run。
- expression、phase、activeRun 和 selected message 必须满足现有 Stage 4E 状态不变量；不得把不一致组合中继给 pet。
- `displayLabel` 只能使用现有内存中已截断的显示标签；不得发送完整消息、prompt、memory、Provider payload 或音频。
- chat preload 在把快照送入主进程前覆盖/注入当前 `projectionEpoch`；renderer 提供不匹配 epoch 的请求必须被拒绝，不能跨 renderer instance 伪造顺序。
- 主进程只在内存中保留最新合法快照。chat renderer reload/crash 时执行上述 epoch reset；pet 回退为 Neutral/Idle 并清除旧 watermark。
- pet 首次创建、reload 或重新显示时向主进程请求重放最新合法快照；无快照时使用 Neutral/Idle。
- snapshot 和其字段不得写入 settings、manifest、SQLite 或常规日志。

## 6. 悬浮 renderer 状态与表现

悬浮 renderer 使用与 Stage 4E 对齐的四态模型：

```text
Idle → Ready → Speaking ↔ Paused
```

- `Idle`：无可用 expression 或活动 run，显示中性静态素材；
- `Ready`：显示当前 expression，无活动 run；
- `Speaking`：当前 run 正在播放，允许轻量 CSS 呼吸/光晕；
- `Paused`：保留同一 run 和 expression，但停止 speaking 动态。

任何缺失、非法或不兼容快照都降级为 Neutral/Idle，不影响聊天、录音或 TTS。

## 7. 本地授权静态素材

### 7.1 权利与范围

- 导入前必须显示明确提示：只导入用户拥有使用权的素材。首轮只接受单个静态 PNG 或 WebP；推荐透明背景，但不强制拒绝不透明图片。opaque 图片仍按 `contain` 显示，用户可自行更换；应用不把“透明素材”作为已验证文件属性。测试使用仓库内原创、中性、带透明通道的 fixture，不读取用户真实素材。

### 7.2 导入事务

1. 聊天 renderer 调用固定 preload 方法打开原生单文件选择器；
2. 选择器只列出 `.png` 与 `.webp`，但主进程仍独立验证；
3. 主进程验证扩展名、文件签名或 MIME、可解码性、静态约束、字节数和像素尺寸；
4. 主进程生成随机 opaque asset ID 和内部文件名；
5. 使用临时文件原子复制到 `app.getPath('userData')/assets`；
6. 原子更新小型 manifest；
7. 复制与 manifest 全部成功后才切换 active asset 和递增 `assetRevision`；
8. 任一步失败都保留旧素材。

首轮固定上限：

- 单文件不超过 20 MiB；
- 每边不超过 8192 px；
- 总像素不超过 32 MP；
- 不接受动画 PNG/WebP。

实施中可以采用更保守值，但不能无证据放宽。

### 7.3 本地 manifest

manifest 只保存：

- manifest schema version；
- active opaque asset ID；
- `kind: 'neutral' | 'static'`；
- 内部相对文件名；
- asset revision。

禁止保存原始绝对路径、原始文件名、聊天内容、消息 ID、run ID、display label、expression 或凭据。

### 7.4 素材加载

pet renderer 只使用固定 URL `pet-asset://active/current`，不接收也不拼接 asset ID。Electron 的受限只读自定义 scheme handler 从当前合法 manifest 解析 active opaque asset ID 和内部相对文件名，并在规范化后确认结果仍位于 `userData/assets` 内；neutral 状态返回仓库内原创 fixture。handler 必须拒绝任何其他 host/path、未知 ID、目录遍历、未登记文件和超出允许目录的解析结果。

`assetRevision` 只用于 renderer cache invalidation：活动素材切换、清除或恢复时递增；pet 以固定 URL 加受控 revision query（例如 `pet-asset://active/current?revision=<n>`）触发重新加载，scheme handler 忽略除已校验 revision 外的任意参数。projection snapshot 不包含 asset ID、相对路径或真实文件名。测试必须覆盖导入、清除、重启恢复、旧 revision、未知 URL/参数和缺失文件。

### 7.5 清除与失败降级

清除素材先原子切换 manifest 到 neutral，再 best-effort 删除不再引用的副本。删除失败只产生可恢复的固定错误，不恢复旧引用。

以下情况使用仓库内中性 fixture：

- manifest 缺失、损坏或版本不兼容；
- 素材副本缺失；
- 图片无法解码；
- 导入文件损坏、伪装、动画或超限；
- scheme 加载失败。

素材故障不得影响聊天、录音、TTS 或表现快照流。

## 8. 角色 renderer 适配器边界

本轮实际实现 `StaticImageRenderer`。它只消费 renderer-neutral `CharacterPresentation`：

- delivery；
- intensity；
- rate；
- phase；
- active run identity；
- asset revision。

静态 renderer 使用 `contain` 渲染透明图片；delivery 只映射有限 CSS 色调或容器姿态；speaking 只启用轻量呼吸/光晕；paused/idle 停止动态；`prefers-reduced-motion` 或应用级 reduced-motion 设置禁用动态。

未来 `Live2DRenderer` 可以消费同一业务输入，但必须另行完成：

- SDK 与模型许可证核验；
- Cubism 版本和 runtime 选型；
- 模型包清单和路径安全；
- expression/motion/parameter 白名单；
- speaking/口型映射；
- WebGL context loss 恢复；
- CPU/GPU/内存预算；
- fake model 与真实本地授权模型验收。

本轮不得引入 Live2D SDK、模型解析或动作代码。

## 9. 窗口与托盘生命周期

### 9.1 启动和显示

- 启动时创建 tray 并显示聊天窗口；
- 悬浮窗对用户默认隐藏，可延迟创建或创建后保持隐藏；
- 聊天按钮和 tray“显示桌宠”调用同一主进程幂等命令；
- 同一进程最多存在一个 chat renderer 和一个 pet renderer；
- 显示悬浮窗不抢聊天窗或其他应用焦点，除非用户直接与其交互。

### 9.2 关闭与退出

- 任一窗口 close 事件在非 quitting 状态下 `preventDefault()` 并隐藏；
- 只有 tray“退出”或开发生命周期明确终止时设置 quitting 标志并真实关闭两个窗口和 tray；
- Electron 不终止开发者单独启动的 Vite 或 FastAPI。

### 9.3 托盘菜单

固定菜单：

- 显示聊天窗口；
- 显示/隐藏桌宠；
- 桌宠置顶：开/关；
- 鼠标穿透：开/关；
- 退出。

菜单文案与 checked 状态必须反映实际窗口状态；命令失败后显示安全默认值，不伪报成功。

### 9.4 置顶、任务栏与拖动

- chat 窗口显示在任务栏，不默认置顶；
- pet 窗口不显示在任务栏，默认 always-on-top；
- chat 只在有限标题区允许拖动，输入与按钮明确 `no-drag`；
- pet 在 interactive 状态下通过明确的素材命中区域拖动；
- 不实现贴边吸附、全局快捷键或自动弹出。

### 9.5 鼠标穿透

状态：

```text
Interactive（默认） ↔ Click-through
```

- 首次运行和设置损坏时使用 Interactive；
- 用户从 tray 明确切换；
- Click-through 必须能从 tray 解除；
- 主进程调用窗口级鼠标穿透 API；调用失败回退 Interactive；
- tray 的状态只在原生 API 成功后更新；
- click-through 和 always-on-top 偏好可以写入 Electron settings，不进入 SQLite。

### 9.6 窗口位置恢复

- 拖动结束后保存逻辑 bounds 和 display 标识，不高频持续写盘；
- 重启时将 bounds clamp 到当前 display 的工作区；
- display 被移除、分辨率或缩放变化时，将窗口恢复到可见区域；
- pet 首次显示位于主屏幕右下安全边距内，不遮住任务栏；
- 不保存 selected message、expression、phase 或 active run；重启后从 Neutral/Idle 开始。

## 10. 安全模型

### 10.1 BrowserWindow 基线

两个窗口均必须：

- `nodeIntegration: false`；
- `contextIsolation: true`；
- `sandbox: true`；
- `webSecurity: true`；
- 不使用 Electron remote module；
- 阻止未知导航、弹窗和下载；
- 开发态只接受精确配置的 Vite origin，不接受通配 origin。

### 10.2 Content Security Policy 与网络出口

开发态 renderer 必须设置显式 CSP 和 Electron `webRequest`/导航策略，而不是只依赖 sandbox：

- `default-src 'none'` 作为基线；
- `script-src`、`style-src` 只允许 Vite 开发所需的精确来源和最小开发例外，实施计划必须记录 Vite 实际产生的 directive，禁止宽泛 `*`；
- `connect-src` 只允许精确 Vite origin、Vite HMR 的精确 `ws://127.0.0.1:<port>`/`ws://localhost:<port>`，以及经 Vite 同源 proxy 访问的 `/api` 与 `/health`；renderer 不直接连接任意远端或 FastAPI LAN 地址；
- `img-src` 只允许同源、`pet-asset:` 和必要的 `data:` fixture；
- `media-src` 只允许同源与现有 TTS playback 所需的 `blob:`；
- `frame-src 'none'`、`object-src 'none'`、`base-uri 'none'`、`form-action 'none'`；
- pet renderer 使用更严格策略：除自身 bundle/style 和 `pet-asset:` 外不允许网络连接、媒体、frame、form 或远端图片。

主进程对 renderer 请求增加 scheme/host/port 白名单并拒绝所有外部 HTTP(S)、WebSocket、图片、frame、下载和重定向出口。开发 HMR 只允许配置中已知的 loopback 端口；不接受任意 loopback 端口或通配域名。测试必须证明外部 `fetch`、图片 beacon、导航、popup 和 download 被拒绝，同时 Vite HMR、同源 API proxy、`blob:` 音频和 `pet-asset:` 仍工作。

### 10.3 IPC 校验

每个 IPC handler 必须验证：

- 固定 channel；
- 发送者是否为预期窗口的 `webContents`；
- frame 和来源 URL 是否属于精确 Vite origin/预期入口；
- schema version；
- 枚举成员；
- 字符串长度；
- 数值为有限安全整数或有界有限数；
- 对象不得带多余字段。

非法请求被拒绝；日志只记录固定错误码、窗口类型和 schema version，不记录 payload。

### 10.4 权限

- chat 窗口只允许现有用户明确触发的媒体权限路径；
- pet 窗口拒绝媒体、剪贴板、通知、地理位置、下载和任意文件权限；
- 不添加隐藏录音、后台监听或远程控制；
- renderer 不得访问 API key、环境变量、数据库或 Provider SDK。

### 10.5 持久化与日志

Electron settings 只允许：

- chat/pet 窗口 bounds；
- pet always-on-top；
- pet click-through。

素材 manifest 是 active asset ID、kind、内部相对文件名、revision 和 manifest schema 的唯一事实来源；settings 不复制这些字段。导入与清除事务只原子替换 manifest，因此不存在两个持久化来源的优先级或对账。

常规日志不得包含：

- presentation snapshot 或 IPC payload；
- display label、message ID、run ID 或消息文本；
- 绝对路径、原始文件名或用户素材；
- API key、环境变量、Provider payload、音频或数据库内容。

## 11. 错误处理与恢复

| Failure | Required behavior | Must remain usable |
|---|---|---|
| FastAPI unavailable | 复用现有聊天 API 可恢复错误；桌面壳不伪装后端成功 | tray、窗口、素材设置、退出 |
| Vite page load failure | 对应窗口显示固定本地错误或诊断页并提供重试 | 另一窗口与 tray |
| Chat renderer crash/reload | 主进程立即清除 latest snapshot；pet 回 Neutral/Idle；允许重载 chat | 素材与窗口 settings |
| Pet renderer crash/reload | 重建/重载后请求最新 snapshot；无快照则 Neutral/Idle | 聊天、录音、TTS、播放 |
| Invalid/stale IPC | 拒绝并记录固定错误码，不修改合法状态 | 当前合法 snapshot |
| Asset validation/copy/decode failure | 保留旧素材或 neutral fallback，允许重试 | 全部业务链路 |
| settings/manifest damage | 隔离坏文件并加载安全默认值，不猜测恢复 | SQLite 和聊天数据 |
| click-through/topmost native call failure | 回退真实安全状态并同步 tray | 其他窗口命令 |

不得因桌面展示故障丢失或回滚已成功持久化的聊天消息。

## 12. 测试策略

### 12.1 纯单元测试

- `PresentationSnapshotV1` parser 的合法、缺字段、多字段、错误 enum、非有限数和长度边界；
- projection epoch 握手、chat HMR/reload/crash reset、sequence 和 stale snapshot 拒绝；
- Stage 4E run/phase 一致性；
- settings schema、损坏降级和 bounds clamp；
- manifest schema、原子更新和损坏降级；
- PNG/WebP 签名、动画检测、大小/像素上限；
- opaque asset ID 与受限 scheme 路径解析。

### 12.2 Main/preload 集成测试

- chat/pet sender、frame 和 origin 校验；
- chat 与 pet preload 暴露的 API 白名单；
- tray 显示/隐藏、置顶、穿透和退出命令幂等；
- close-to-hide 与 quitting 语义；
- 单 chat/单 pet renderer 不变量；
- chat reload 分配新 epoch、清除快照并原子 reset pet watermark，pet reload 请求重放当前 epoch 的最新快照；
- 导入成功、失败回滚、清除和 manifest 恢复。

Electron 原生对象尽量通过小型适配器注入 fake，避免单元测试依赖真实桌面会话。

### 12.3 Renderer 测试

- 五种 delivery 和四种 phase；
- neutral/static asset；
- stale sequence 拒绝；
- chat 发布完整快照并使用主进程分配的 projection epoch；
- pet 对 epoch reset 后清除旧 watermark，并拒绝旧 epoch/旧 sequence；
- pet 只读消费且不访问业务 API；
- speaking/paused/replay/run switching；
- reduced motion；
- 素材加载失败 local boundary；
- 聊天按钮和桌面设置反馈不影响现有聊天、录音和 TTS。

### 12.4 Windows 11 smoke

使用 fake providers、唯一 SQLite、临时 Electron `userData` 和仓库内原创中性 PNG/WebP fixture：

1. 分别启动 FastAPI、Vite 和 Electron；默认只显示聊天窗口；
2. 聊天按钮和 tray 反复显示/隐藏同一 pet renderer；
3. 两窗口 close 都隐藏，tray“退出”才终止；
4. 创建会话并发送 fake 消息，精确 expression 和 play/pause/resume/stop/replay 状态同步；
5. 旧 epoch、旧 sequence 或旧 run 不能覆盖新状态；chat reload 必须先让 pet reset watermark，再接受新 epoch；
6. 录音打断、会话切换和 chat reload 后 pet 不残留 speaking/paused；
7. 导入原创测试 PNG/WebP，复制到临时 userData，重启后恢复；移动原文件不影响副本；
8. 损坏、伪装、动画、超限或缺失素材拒绝/降级；旧合法素材和聊天保持可用；
9. 拖动、always-on-top 和 click-through 工作；tray 能解除穿透；bounds 在屏幕变化后可见；
10. pet reload 不影响 chat/TTS，chat reload 使 pet 先回 Neutral/Idle；
11. pet 无 Node、文件和媒体权限；未知导航、外部 fetch/图片 beacon、popup、download、非法 sender/payload 被拒绝；Vite HMR、同源 API proxy、`blob:` 音频和 `pet-asset:` 保持可用；
12. 清理临时数据库、userData 和 sidecar，确认没有用户素材、业务状态或凭据残留。

tray、真实窗口层级和 click-through 必须在真实 Windows 桌面会话中验证；纯 headless 测试不能替代。

### 12.5 回归与完成门槛

必须同时通过：

- 现有 Python 全量回归；
- frontend Vitest；
- TypeScript typecheck；
- Vite production build；
- 现有 Playwright browser E2E；
- Electron 新增单元/集成测试；
- Windows 11 smoke；
- 数据库与临时 userData 清理检查；
- 密钥、路径、素材、日志和构建产物 hygiene；
- 提交前 Critical/High 代码审查。

任何未运行或失败的 Windows 场景必须明确记录为未验证，不能把桌面壳标记为完成。

## 13. 预期文件边界

实施计划预计涉及：

- `frontend/package.json`、`frontend/package-lock.json`：Electron 及开发/测试脚本；
- `frontend/electron/`：主进程、chat/pet preload、窗口/tray、IPC、settings、asset store 与 scheme；
- `frontend/src/desktop/`：共享协议 parser、bridge 类型、投影派生与桌面设置 hooks；
- `frontend/src/pet/`：独立 pet renderer 入口、状态容器和 `StaticImageRenderer`；
- `frontend/src/App.tsx`、相关 layout/style：最小桌面入口与表现投影接线；
- `frontend/vite.config.ts` 和入口 HTML：开发态 chat/pet 多入口与精确 origin；
- Electron/main/preload/renderer 单元与集成测试；
- Windows smoke 配置、原创 fixture 和隔离清理 verifier；
- `.gitignore`：只增加明确的 Electron 生成产物和本地 userData 测试目录规则；
- `README.md`、`CLAUDE.md` 和新的完成证据：只在真实验收后更新桌面壳状态。

本闭环不应修改 FastAPI domain、SQLite schema、Stage 4 expression API 或 Provider 接口。若实现探索证明必须修改这些边界，应停止并重新设计，而不是顺带扩大计划。

## 14. 交付顺序

已完成的历史前置：

- Stage 4 已于 2026-07-15 正式关闭并形成总体验收记录；
- 本 Electron 桌面壳设计已获对话设计批准并写入当前规格。

后续可执行顺序：

1. 用户复核本书面规格；
2. 调用 `writing-plans` 形成详细文件级实施计划；
3. 按计划 TDD 实现 Electron 开发态双窗口闭环；
4. 完成自动化、Windows smoke、隔离清理与代码审查；
5. 只有所有门槛通过后更新桌面壳完成状态；
6. Live2D 另起设计、计划、实施和验收循环。

## 15. 完成定义

本闭环完成时，用户能在 Windows 11 开发环境中启动现有 fake-first 内核和 Electron：默认使用聊天窗口；按需显示一个透明、置顶、可拖动、可切换鼠标穿透的角色窗口；导入本地有权使用的静态 PNG/WebP（推荐透明背景）；让该窗口准确消费当前 assistant message 和 playback run 的只读表现快照；任一展示或素材故障均不破坏聊天、录音、TTS、Stage 4 状态或持久化边界。

这仍不是可安装产品，也不是 Live2D 桌宠。它是后续动态角色 renderer 和生产打包工作的最小、可验证原生展示基础。
