> ## Documentation Index
> Fetch the complete documentation index at: https://platform.stepfun.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# StepAudio 2.5 ASR

> 基于 4B MTP 的极速语音识别模型

`stepaudio-2.5-asr` 是 4B 参数的语音识别模型。引入 Multi-Token Prediction（MTP）技术实现单步并行预测多个 Token，在保持 SOTA 转写精度的同时大幅削减串行等待周期——5 分钟音频可在 1 秒内完成转写。

<Columns cols={3}>
  <Card title="在线体验" icon="play" href="https://stepaudiollm.github.io/step-audio-2.5-asr/">
    访问官方 Demo 页面，快速感受模型效果。
  </Card>

  <Card title="API 快速开始" icon="rocket" href="#快速上手">
    查看最小可运行的 curl 调用示例。
  </Card>

  <Card title="Step Plan 接入" icon="link" href="/zh/step-plan/integrations/audio-api">
    Step Plan 订阅用户可直接使用。
  </Card>
</Columns>

## 关键信息

<Columns cols={3}>
  <Card title="模型架构">
    4B MTP
  </Card>

  <Card title="引擎侧 RTF">
    ≈ 0.0053<br />转写 1 小时音频约需 19 秒
  </Card>

  <Card title="API 定价">
    0.15 元 / 小时
  </Card>
</Columns>

## 核心能力

<Columns cols={2}>
  <Card title="⚡ 极速推理">
    引入 MTP（Multi-Token Prediction）技术，单步并行预测多个 Token，吞吐量较传统 ASR 提升 400%，时延降低 60%，5 分钟音频 1 秒内出完整转写结果。
  </Card>

  <Card title="🎯 SOTA 转写精度">
    基于 4B 参数深度优化，在新闻、会议、强噪声等多场景下，中英文错误率全面刷新行业基线。
  </Card>
</Columns>

## 适用场景

Voice Agent、大规模转写服务、实时字幕 / 直播。

## API 端点

StepAudio 2.5 ASR 通过 SSE 接入，模型字符串为 `stepaudio-2.5-asr`：

<Card title="语音识别（流式返回文本）" icon="file-lines" href="/zh/api-reference/audio/asr-sse">
  `POST /v1/audio/asr/sse`<br />一次性提交音频 Base64 数据，服务端通过 SSE 流式返回识别文本。支持 PCM / OGG / MP3 / WAV，支持中英文识别，支持 `enable_itn`、`enable_timestamp` 参数。
</Card>

## 定价

| 计费项    | 单价              |
| :----- | :-------------- |
| API 调用 | **0.15 元 / 小时** |

仅为上代 `step-asr` 系列的 1/10。Step Plan 用户可直接使用。具体规则见 [定价与限速](/zh/guides/pricing/details)。

## 快速上手

```bash theme={null}
curl https://api.stepfun.com/v1/audio/asr/sse \
  -H "Authorization: Bearer $STEP_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "audio": {
      "data": "base64_encoded_audio",
      "input": {
        "transcription": {
          "model": "stepaudio-2.5-asr",
          "language": "zh",
          "enable_itn": true
        },
        "format": {
          "type": "pcm",
          "codec": "pcm_s16le",
          "rate": 16000,
          "bits": 16,
          "channel": 1
        }
      }
    }
  }'
```

服务端会逐步发送 `transcript.text.delta` 事件并以 `transcript.text.done` 结束。

## 相关资源

<Columns cols={2}>
  <Card title="Demo Page" icon="flask" href="https://stepaudiollm.github.io/step-audio-2.5-asr/">
    产品 Demo 页面。
  </Card>

  <Card title="Model Card" icon="circle-info" href="https://stepaudiollm.github.io/step-audio-2.5-asr/model-card/">
    模型卡，查看架构与评测细节。
  </Card>

  <Card title="语音识别（流式返回文本）API" icon="file-lines" href="/zh/api-reference/audio/asr-sse">
    查看完整参数、响应事件、错误处理。
  </Card>

  <Card title="Step Plan 接入" icon="link" href="/zh/step-plan/integrations/audio-api">
    Step Plan 订阅下的 ASR 调用路径。
  </Card>
</Columns>

